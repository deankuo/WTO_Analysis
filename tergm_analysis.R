###############################################################################
# WTO Dispute TERGM Analysis
# Author: Peng-Ting Kuo
# Date: March 2026
#
# This script:
#   1. Reads the ERGM panel dataset (ergm_dyad_year_eun.csv)
#   2. Cleans missing values according to documented rules
#   3. Constructs yearly network objects (directed, binary: C->R only)
#   4. Attaches node & edge attributes
#   5. Estimates TERGM models using btergm
#
# Models:
#   Model 0 : Baseline, EUN EXCLUDED (pure national-state benchmark)
#   Model 1 : Full node set (incl. EUN) — structural + trade
#   Model 2 : + Political alignment (ideal point distance)
#   Model 3 : + Democracy & governance — ip+dem-complete node set (drops nodes
#             missing EITHER idealpointfp OR v2x_polyarchy after carry-forward)
#   Model 1L: Model 1 + lagged trade (t-1) as robustness check
#
# Data issues fixed vs prior version:
#   - EUN node attrs now come directly from country_meta (imputed by
#     scripts/impute_eun_meta.py); old _1-suffix extraction block removed.
#   - atopally_t1/t2/t3 do NOT exist in ergm_dyad_year_eun.csv; removed.
#   - label_t1/depth_index_t1 etc. do NOT exist; removed.
#   - fdi (% of GDP) removed from node_impute_vars; ambiguous for EUN.
#   - ideal_dist_cov: non-UN-member nodes (Taiwan, some micro-states) dropped
#     via ip-complete node set; 0 is a valid substantive value so imputation
#     is not appropriate. Models 2 and 3 use ip-complete (net_list_ip).
#   - total_trade_ij_t1 available for lagged trade model.
#
# Required packages: network, btergm, sna, texreg, dplyr, tidyr
###############################################################################

# ===========================================================================
# 0. SETUP
# ===========================================================================

# install.packages(c("btergm", "network", "sna", "texreg", "dplyr", "tidyr"))
library(network)
library(btergm)
library(sna)
library(texreg)
library(dplyr)
library(tidyr)

# ===========================================================================
# 1. READ DATA
# ===========================================================================

ergm_panel   <- read.csv("Data/ergm_dyad_year_eun.csv",    stringsAsFactors = FALSE)
country_meta <- read.csv("Data/country_meta_1995_2024.csv", stringsAsFactors = FALSE)

# EUN is now directly in country_meta (imputed via scripts/impute_eun_meta.py).
# The following check guards against re-runs on older country_meta files.
if (!"EUN" %in% country_meta$iso3c) {
  stop("EUN not found in country_meta. Run: python scripts/impute_eun_meta.py --write")
}

cat("Panel rows:", nrow(ergm_panel), "\n")
cat("Year range:", range(ergm_panel$year), "\n")
cat("Dispute rate:", round(mean(ergm_panel$has_dispute, na.rm = TRUE), 5), "\n")
cat("EUN rows in country_meta:", sum(country_meta$iso3c == "EUN"), "\n")

# ===========================================================================
# 2. CLEAN MISSING VALUES
# ===========================================================================

# --- 2a. Trade + section variables: NA -> 0 ---
# total_trade_ij_t1 has ~50k NAs for year 1995 (no lagged data) — treated as 0.
# max_reverse_dep has ~9% NAs (one-way flows with no reverse trade) — treated as 0.
trade_vars <- c("total_trade_ij",  "export_dependence",  "trade_dependence",
                "n_products_ij",   "n_sections_ij",
                "trade_hhi",       "max_export_conc",    "max_reverse_dep")
for (v in trade_vars) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2b. DESTA / PTA ---
# label==1 means a PTA exists; NA means not in DESTA universe → treat as 0.
# NOTE: label_t1/label_t2/depth_index_t1 etc. are NOT in the dataset.
# Manual check: This approach make sense since it just the missing value basically means the PTA record is not accessible
# It has 4000 (<1% missing value)
if ("label" %in% names(ergm_panel)) {
  ergm_panel$pta_exists <- ifelse(is.na(ergm_panel$label), 0L, as.integer(ergm_panel$label))
}
if ("depth_index" %in% names(ergm_panel)) {
  ergm_panel$depth_index[is.na(ergm_panel$depth_index)] <- 0
}

# --- 2c. ATOP alliance: NA -> 0 ---
# NOTE: atopally_t1/t2/t3 are NOT pre-computed in ergm_dyad_year_eun.csv.
#       Only the contemporaneous atopally is available.
# Use atopally as the variable
atop_vars <- c("atopally")
for (v in atop_vars) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2d. Severity scores: NA -> 0 ---
# Not using all of the variables severity|rhetorical|systemic|escalation|domestic_victim\
# severity is the average of 4 dimensions
sev_vars <- grep("severity",
                 names(ergm_panel), value = TRUE)
for (v in sev_vars) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0

# --- 2e. Disputed sector trade: NA -> 0 ---
for (v in grep("^disputed_", names(ergm_panel), value = TRUE)) {
  ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2f. V-dem election node attributes ---
# election_binary: NA -> 0
if ("election_binary" %in% names(country_meta)) {
  country_meta$election_binary[is.na(country_meta$election_binary)] <- 0
}

# GDP / pop / growth: carry-forward for small gaps (late joiners, data lags)
# fdi (% of GDP) deliberately excluded: ambiguous for EUN and rarely used.
node_impute_vars <- c("gdp", "gdppc", "pop", "log_gdppc", "log_pop", "gdp_growth_rate")
country_meta <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(node_impute_vars, names(country_meta))), .direction = "downup") %>%
  ungroup()

# cum_* / n_*_t: NA -> 0 (some members joined after 1995)
for (v in grep("^cum_|^n_complainant_t|^n_respondent_t|^n_tp_t",
               names(country_meta), value = TRUE)) {
  country_meta[[v]][is.na(country_meta[[v]])] <- 0
}

# Log-transformed cumulative experience variables (log1p handles zeros)
# Three extra columns alongside the raw counts.
country_meta$log_cum_complainant <- log1p(country_meta$cum_complainant)
country_meta$log_cum_respondent  <- log1p(country_meta$cum_respondent)
country_meta$log_cum_third_party <- log1p(country_meta$cum_third_party)

# --- 2g. Drop nodes with residual NA in required node covariates ---
REQUIRED_NODE_VARS <- c("log_gdppc", "log_pop", "cum_complainant", "cum_respondent")
REQUIRED_NODE_VARS_DEM <- c("v2x_polyarchy")
avail_req <- intersect(REQUIRED_NODE_VARS, names(country_meta))

nodes_with_missing <- country_meta %>%
  filter(if_any(all_of(avail_req), is.na)) %>%
  pull(iso3c) %>%
  unique()

# Drop HKG, MAC, PRK, SOM
if (length(nodes_with_missing) > 0) {
  cat("\nDropping", length(nodes_with_missing), "nodes with residual NA:\n")
  for (n in sort(nodes_with_missing)) {
    bad <- avail_req[sapply(avail_req, function(v) any(is.na(country_meta[[v]][country_meta$iso3c == n])))]
    cat(" ", n, "-> NA in:", paste(bad, collapse = ", "), "\n")
  }
  ergm_panel   <- ergm_panel   %>% filter(!exporter %in% nodes_with_missing, !importer %in% nodes_with_missing)
  country_meta <- country_meta %>% filter(!iso3c %in% nodes_with_missing)
} else {
  cat("\nNo nodes dropped.\n")
}

cat("\n--- Missing data summary after cleaning ---\n")
cat("has_dispute NA  :", sum(is.na(ergm_panel$has_dispute)), "\n")
cat("atopally NA     :", sum(is.na(ergm_panel$atopally)), "\n")
cat("pta_exists NA   :", sum(is.na(ergm_panel$pta_exists)), "\n")
cat("total_trade NA  :", sum(is.na(ergm_panel$total_trade_ij)), "\n")

# ===========================================================================
# 3. DEFINE ANALYSIS PERIOD & NODE SETS
# ===========================================================================

YEAR_START <- 1995
YEAR_END   <- 2024

EXCLUDED_COUNTRIES <- c("MAC", "HKG", "SOM", "PRK")

ergm_panel   <- ergm_panel   %>% filter(year >= YEAR_START, year <= YEAR_END,
                                        !exporter %in% EXCLUDED_COUNTRIES,
                                        !importer %in% EXCLUDED_COUNTRIES)
country_meta <- country_meta %>% filter(!iso3c %in% EXCLUDED_COUNTRIES)

# Full node set (includes EUN)
all_nodes <- sort(unique(c(ergm_panel$exporter, ergm_panel$importer)))
n_nodes   <- length(all_nodes)

# No-EUN node set
ergm_panel_noeun   <- ergm_panel   %>% filter(exporter != "EUN", importer != "EUN")
country_meta_noeun <- country_meta %>% filter(iso3c != "EUN")
all_nodes_noeun    <- sort(unique(c(ergm_panel_noeun$exporter, ergm_panel_noeun$importer)))
n_nodes_noeun      <- length(all_nodes_noeun)

cat("\nFull analysis:  ", YEAR_START, "-", YEAR_END, " | nodes:", n_nodes,
    " | dyad-years:", nrow(ergm_panel), "\n")
cat("No-EUN analysis:", YEAR_START, "-", YEAR_END, " | nodes:", n_nodes_noeun,
    " | dyad-years:", nrow(ergm_panel_noeun), "\n")

# ---------------------------------------------------------------------------
# Democracy-complete node set
# NOTE: This section is now superseded by the ip-complete section below.
#   The ip-complete set drops non-UN members (including Taiwan); V-Dem
#   completeness of the remaining ip nodes is verified in that section.
#   Both Models 2 and 3 now use the ip-complete node set.
#   This block is retained for diagnostics (n_nodes_dem, nodes_missing_vdem).
# ---------------------------------------------------------------------------

REQUIRED_NODE_VARS_DEM <- c("v2x_polyarchy")

country_meta_dem <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(REQUIRED_NODE_VARS_DEM, names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_vdem <- country_meta_dem %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_DEM, names(country_meta_dem))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_vdem) > 0) {
  cat("\nDemocracy-complete: dropping", length(nodes_missing_vdem),
      "nodes missing v2x_polyarchy:\n ",
      paste(sort(nodes_missing_vdem), collapse = ", "), "\n")
} else {
  cat("\nDemocracy-complete: no nodes dropped (v2x_polyarchy complete).\n")
}
# drop 21 nodes from the country panel data (196countries): 
# AND, ATG, BHS, BLZ, BRN, DMA, FSM, GRD, KIR, KNA, LCA, LIE, MCO, MHL, NRU, PLW, SMR, TON, TUV, VCT, WSM 
ergm_panel_dem   <- ergm_panel     %>% filter(!exporter %in% nodes_missing_vdem,
                                               !importer %in% nodes_missing_vdem)
country_meta_dem <- country_meta_dem %>% filter(!iso3c %in% nodes_missing_vdem)
all_nodes_dem    <- sort(unique(c(ergm_panel_dem$exporter, ergm_panel_dem$importer)))
n_nodes_dem      <- length(all_nodes_dem)

cat("Democracy-complete node set:", n_nodes_dem,
    "(dropped", n_nodes - n_nodes_dem, "from full set)\n")
cat("Democracy-complete dyad-years:", nrow(ergm_panel_dem), "\n")

# ---------------------------------------------------------------------------
# Ideal-point-complete node set (Model 2)
#
# idealpointfp is structurally missing for non-UN members (Taiwan, Kosovo,
# Vatican, some micro-states). Because 0 is a valid substantive value on the
# -2 to +3 ideal-point scale, imputation is not appropriate; drop instead.
# Model 2 only needs ideal-point completeness; V-Dem is NOT required here.
# ---------------------------------------------------------------------------

REQUIRED_NODE_VARS_IP <- c("idealpointfp")

country_meta_ip <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(REQUIRED_NODE_VARS_IP, names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_ip <- country_meta_ip %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_IP, names(country_meta_ip))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_ip) > 0) {
  cat("\nIdeal-point-complete (Model 2): dropping", length(nodes_missing_ip),
      "nodes missing idealpointfp:\n ",
      paste(sort(nodes_missing_ip), collapse = ", "), "\n")
} else {
  cat("\nIdeal-point-complete: no nodes dropped (idealpointfp complete).\n")
}

ergm_panel_ip   <- ergm_panel %>% filter(!exporter %in% nodes_missing_ip,
                                          !importer %in% nodes_missing_ip)
country_meta_ip <- country_meta_ip %>% filter(!iso3c %in% nodes_missing_ip)
all_nodes_ip    <- sort(unique(c(ergm_panel_ip$exporter, ergm_panel_ip$importer)))
n_nodes_ip      <- length(all_nodes_ip)

cat("Ideal-point-complete node set:", n_nodes_ip,
    "(dropped", n_nodes - n_nodes_ip, "from full set)\n")

# ---------------------------------------------------------------------------
# Ideal-point-AND-V-Dem-complete node set (Model 3)
#
# Model 3 requires both idealpointfp and v2x_polyarchy.
# Some UN members (e.g., small Pacific island states, micro-states) have ideal
# points but no V-Dem coverage. These are IN net_list_ip (Model 2) but must be
# dropped for Model 3. The two sets are distinct and built separately.
# ---------------------------------------------------------------------------

country_meta_ip_dem <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(c(REQUIRED_NODE_VARS_IP, REQUIRED_NODE_VARS_DEM),
                        names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_ip_dem <- country_meta_ip_dem %>%
  filter(if_any(all_of(intersect(c(REQUIRED_NODE_VARS_IP, REQUIRED_NODE_VARS_DEM),
                                 names(country_meta_ip_dem))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_ip_dem) > 0) {
  cat("\nIp+Dem-complete (Model 3): dropping", length(nodes_missing_ip_dem),
      "nodes missing idealpointfp or v2x_polyarchy:\n ",
      paste(sort(nodes_missing_ip_dem), collapse = ", "), "\n")
} else {
  cat("\nIp+Dem-complete: no nodes dropped.\n")
}

ergm_panel_ip_dem   <- ergm_panel %>% filter(!exporter %in% nodes_missing_ip_dem,
                                               !importer %in% nodes_missing_ip_dem)
country_meta_ip_dem <- country_meta_ip_dem %>% filter(!iso3c %in% nodes_missing_ip_dem)
all_nodes_ip_dem    <- sort(unique(c(ergm_panel_ip_dem$exporter, ergm_panel_ip_dem$importer)))
n_nodes_ip_dem      <- length(all_nodes_ip_dem)

cat("Ip+Dem-complete node set:", n_nodes_ip_dem,
    "(dropped", n_nodes - n_nodes_ip_dem, "from full set)\n")
cat("Ip+Dem-complete dyad-years:", nrow(ergm_panel_ip_dem), "\n")
cat("Nodes in ip but not ip_dem (have idealpoint, lack V-Dem):",
    length(setdiff(all_nodes_ip, all_nodes_ip_dem)), ":",
    paste(sort(setdiff(all_nodes_ip, all_nodes_ip_dem)), collapse = ", "), "\n")

# ===========================================================================
# 4. NETWORK BUILDER HELPER
# ===========================================================================

#' build_net_list
#' Constructs yearly directed network objects with edge & node covariates.
#' @param panel   Filtered ergm_panel
#' @param meta    Filtered country_meta
#' @param nodes   Character vector of node labels (sorted)
#' @param years   Integer vector of years
#' @return Named list:
#'   net_list, trade_cov, trade_cov_t1, ally_cov, pta_cov, depth_cov,
#'   ideal_dist_cov, hhi_cov, export_conc_cov, import_dep_cov

build_net_list <- function(panel, meta, nodes, years) {
  n <- length(nodes)
  net_list        <- list()
  trade_cov       <- list()
  trade_cov_t1    <- list()
  ally_cov        <- list()
  pta_cov         <- list()
  depth_cov       <- list()
  ideal_dist_cov  <- list()
  hhi_cov         <- list()
  export_conc_cov <- list()
  import_dep_cov  <- list()

  for (yr in years) {
    cat("\rBuilding network for year", yr, "...")
    df_yr <- panel %>% filter(year == yr)

    # --- Adjacency matrix (C -> R only) ---
    # DIRECTION VERIFIED: in ergm_dyad_year_eun.csv,
    #   exporter = complainant (wto_dyadic iso3_1, the filing party)
    #   importer = respondent  (wto_dyadic iso3_2, the targeted party)
    # build_ergm_data.py line ~584:
    #   cr = cr.rename(columns={"iso3_1":"exporter","iso3_2":"importer"})
    # So adj[i, j] = 1 means i (exporter/complainant) filed against j (importer/respondent).
    # nodeocov = out-node = sender = complainant  (CORRECT)
    # nodeicov = in-node  = receiver = respondent (CORRECT)
    adj <- matrix(0L, n, n, dimnames = list(nodes, nodes))
    for (r in which(df_yr$has_dispute == 1)) {
      i <- df_yr$exporter[r]; j <- df_yr$importer[r]
      if (i %in% nodes && j %in% nodes) adj[i, j] <- 1L
    }
    net <- network(adj, directed = TRUE)

    # --- Node attributes ---
    meta_yr  <- meta %>% filter(year == yr) %>% distinct(iso3c, .keep_all = TRUE)
    node_df  <- data.frame(iso3c = nodes, stringsAsFactors = FALSE) %>%
      left_join(meta_yr %>% select(iso3c,
        any_of(c("log_gdppc", "log_pop", "wto_member",
                 "v2x_polyarchy", "v2x_libdem", "election_binary",
                 "reg_quality", "law", "voice",
                 "idealpointfp", "idealpointall",
                 "cum_complainant", "cum_respondent", "cum_third_party",
                 "log_cum_complainant", "log_cum_respondent", "log_cum_third_party",
                 "unemployment_rate", "gdp_growth_rate"))),
        by = "iso3c")
    for (a in setdiff(names(node_df), "iso3c")) {
      set.vertex.attribute(net, a, node_df[[a]])
    }

    # --- Edge covariate matrices ---
    mk <- function(fill = 0) matrix(fill, n, n, dimnames = list(nodes, nodes))

    trade_m        <- mk(); trade_t1_m  <- mk(); ally_m  <- mk()
    pta_m          <- mk(); depth_m     <- mk()
    hhi_m          <- mk(); exp_conc_m  <- mk(); imp_dep_m <- mk()

    for (r in seq_len(nrow(df_yr))) {
      i <- df_yr$exporter[r]; j <- df_yr$importer[r]
      if (!(i %in% nodes && j %in% nodes)) next
      trade_m[i, j]   <- df_yr$total_trade_ij[r]
      trade_t1_m[i,j] <- df_yr$total_trade_ij_t1[r]
      # Alliance & PTA: undirected
      ally_m[i, j]  <- ally_m[j, i]  <- max(ally_m[i,j],  df_yr$atopally[r])
      pta_m[i, j]   <- pta_m[j, i]   <- max(pta_m[i,j],   df_yr$pta_exists[r])
      if ("depth_index" %in% names(df_yr))
        depth_m[i,j] <- depth_m[j,i] <- max(depth_m[i,j], df_yr$depth_index[r])
      # Section covariates: DIRECTED (i -> j specific; no symmetrisation)
      if ("trade_hhi"       %in% names(df_yr)) hhi_m[i,j]      <- df_yr$trade_hhi[r]
      if ("max_export_conc" %in% names(df_yr)) exp_conc_m[i,j] <- df_yr$max_export_conc[r]
      if ("max_reverse_dep" %in% names(df_yr)) imp_dep_m[i,j]  <- df_yr$max_reverse_dep[r]
    }

    # --- Ideal point distance ---
    # Use idealpointfp (fewer NAs).
    # For ip-complete datasets (Models 2 & 3) there are no NAs here; the
    # NA->0 fallback below is a no-op and kept only as a safety guard for
    # full/noeun builds where ideal_dist_cov is not used in any model.
    ip_vec <- node_df$idealpointfp
    if (is.null(ip_vec)) ip_vec <- rep(NA_real_, n)
    ideal_m <- outer(ip_vec, ip_vec, function(a, b) abs(a - b))
    ideal_m[is.na(ideal_m)] <- 0   # safety guard (no-op for ip-complete datasets)
    rownames(ideal_m) <- colnames(ideal_m) <- nodes

    yr_key <- as.character(yr)
    net_list[[yr_key]]        <- net
    trade_cov[[yr_key]]       <- log(trade_m + 1)
    trade_cov_t1[[yr_key]]    <- log(trade_t1_m + 1)
    ally_cov[[yr_key]]        <- ally_m
    pta_cov[[yr_key]]         <- pta_m
    depth_cov[[yr_key]]       <- depth_m
    ideal_dist_cov[[yr_key]]  <- ideal_m
    hhi_cov[[yr_key]]         <- hhi_m
    export_conc_cov[[yr_key]] <- exp_conc_m
    import_dep_cov[[yr_key]]  <- imp_dep_m
  }

  cat("\n")
  list(net_list        = net_list,
       trade_cov       = trade_cov,
       trade_cov_t1    = trade_cov_t1,
       ally_cov        = ally_cov,
       pta_cov         = pta_cov,
       depth_cov       = depth_cov,
       ideal_dist_cov  = ideal_dist_cov,
       hhi_cov         = hhi_cov,
       export_conc_cov = export_conc_cov,
       import_dep_cov  = import_dep_cov)
}

# ===========================================================================
# 5. BUILD NETWORK LISTS
# ===========================================================================

years <- YEAR_START:YEAR_END

cat("\n=== Building FULL network list (includes EUN) ===\n")
full <- build_net_list(ergm_panel, country_meta, all_nodes, years)

cat("\n=== Building NO-EUN network list ===\n")
noeun <- build_net_list(ergm_panel_noeun, country_meta_noeun, all_nodes_noeun, years)

cat("\n=== Building IP-COMPLETE network list (Model 2) ===\n")
ip <- build_net_list(ergm_panel_ip, country_meta_ip, all_nodes_ip, years)

cat("\n=== Building IP+DEM-COMPLETE network list (Model 3) ===\n")
ip_dem <- build_net_list(ergm_panel_ip_dem, country_meta_ip_dem, all_nodes_ip_dem, years)

# Unpack for convenience
net_list        <- full$net_list
trade_cov       <- full$trade_cov
trade_cov_t1    <- full$trade_cov_t1
ally_cov        <- full$ally_cov
pta_cov         <- full$pta_cov
depth_cov       <- full$depth_cov
ideal_dist_cov  <- full$ideal_dist_cov
hhi_cov         <- full$hhi_cov
export_conc_cov <- full$export_conc_cov
import_dep_cov  <- full$import_dep_cov

net_list_noeun        <- noeun$net_list
trade_cov_noeun       <- noeun$trade_cov
trade_cov_t1_noeun    <- noeun$trade_cov_t1
ally_cov_noeun        <- noeun$ally_cov
pta_cov_noeun         <- noeun$pta_cov
ideal_dist_cov_noeun  <- noeun$ideal_dist_cov
hhi_cov_noeun         <- noeun$hhi_cov
export_conc_cov_noeun <- noeun$export_conc_cov
import_dep_cov_noeun  <- noeun$import_dep_cov

net_list_ip        <- ip$net_list
trade_cov_ip       <- ip$trade_cov
trade_cov_t1_ip    <- ip$trade_cov_t1
ally_cov_ip        <- ip$ally_cov
pta_cov_ip         <- ip$pta_cov
depth_cov_ip       <- ip$depth_cov
ideal_dist_cov_ip  <- ip$ideal_dist_cov
hhi_cov_ip         <- ip$hhi_cov
export_conc_cov_ip <- ip$export_conc_cov
import_dep_cov_ip  <- ip$import_dep_cov

net_list_ip_dem        <- ip_dem$net_list
trade_cov_ip_dem       <- ip_dem$trade_cov
trade_cov_t1_ip_dem    <- ip_dem$trade_cov_t1
ally_cov_ip_dem        <- ip_dem$ally_cov
pta_cov_ip_dem         <- ip_dem$pta_cov
depth_cov_ip_dem       <- ip_dem$depth_cov
ideal_dist_cov_ip_dem  <- ip_dem$ideal_dist_cov
hhi_cov_ip_dem         <- ip_dem$hhi_cov
export_conc_cov_ip_dem <- ip_dem$export_conc_cov
import_dep_cov_ip_dem  <- ip_dem$import_dep_cov

# Diagnostics
cat("\n--- Network diagnostics (full) ---\n")
for (yr in c("1995","2000","2005","2010","2015","2020","2024")) {
  if (yr %in% names(net_list)) {
    cat(yr, ": edges =", network.edgecount(net_list[[yr]]),
        " | density =", round(network.density(net_list[[yr]]), 5), "\n")
  }
}

# Check EUN node attributes in a sample year
net_check  <- net_list[["2010"]]
na_idx     <- which(is.na(get.vertex.attribute(net_check, "log_gdppc")))
node_names <- network.vertex.names(net_check)
if (length(na_idx) > 0) {
  cat("\nWARNING: NA log_gdppc in 2010 for:", paste(node_names[na_idx], collapse = ", "), "\n")
} else {
  cat("\nlog_gdppc: no NAs in 2010. EUN imputation confirmed.\n")
}

# ===========================================================================
# 6. TERGM ESTIMATION
# ===========================================================================

BTERGM_BOOTS <- 200   # use 200 for testing, 1000 for final run

# --- Model 0: No-EUN baseline ---
# The section dependence and concentration may need further
cat("\n=== Model 0: No-EUN Baseline ===\n")
start_time <- Sys.time()
model0 <- btergm(
  net_list_noeun ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_noeun) +
    edgecov(ally_cov_noeun) +
    edgecov(pta_cov_noeun) +
    edgecov(hhi_cov_noeun) +          # trade concentration across HS sections
    edgecov(export_conc_cov_noeun) +  # i's max section export share to j
    edgecov(import_dep_cov_noeun) +   # j's max section export share to i (import leverage)
    # sender & receiver
    nodeocov("log_gdppc") +     # complainant's economic standard
    nodeicov("log_gdppc") +     # respondent's economic standard
    nodeocov("log_pop") +       # complainant's country scale
    nodeicov("log_pop") +       # respondent's country scale
    # gap between sender and receiver
    absdiff("log_gdppc") +      # economic gap
    absdiff("log_pop") +        # population gap
    nodeicov("log_cum_respondent") +
    nodeocov("log_cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
end_time <- Sys.time()
execution_time <- end_time - start_time
print(execution_time)
cat("\n--- Model 0 (No-EUN) ---\n"); summary(model0)

# --- Model 1: Full node set + structural + trade ---
cat("\n=== Model 1: Full (incl. EUN) — Structural + Trade ===\n")
model1 <- btergm(
  net_list ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov) +
    edgecov(ally_cov) +
    edgecov(pta_cov) +
    edgecov(hhi_cov) +               # trade concentration across HS sections
    edgecov(export_conc_cov) +       # i's max section export share to j
    edgecov(import_dep_cov) +        # j's max section export share to i (import leverage)
    # sender & receiver
    nodeocov("log_gdppc") +     # complainant's economic standard
    nodeicov("log_gdppc") +     # respondent's economic standard
    nodeocov("log_pop") +       # complainant's country scale
    nodeicov("log_pop") +       # respondent's country scale
    # gap between sender and receiver
    absdiff("log_gdppc") +      # economic gap
    absdiff("log_pop") +        # population gap
    nodeicov("log_cum_respondent") +
    nodeocov("log_cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
cat("\n--- Model 1 ---\n"); summary(model1)

# --- Model 2: + Political alignment (ideal point distance) ---
# Uses ip-complete node set: drops non-UN members (Taiwan etc.) where
# idealpointfp is structurally missing. 0 is a valid value on the scale
# so imputation is not used.
cat("\n=== Model 2: + Political Alignment (ip-complete, n =", n_nodes_ip, "nodes) ===\n")
model2 <- btergm(
  net_list_ip ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip) +
    edgecov(ally_cov_ip) +
    edgecov(pta_cov_ip) +
    edgecov(hhi_cov_ip) +
    edgecov(export_conc_cov_ip) +
    edgecov(import_dep_cov_ip) +
    edgecov(ideal_dist_cov_ip) +      # UN voting distance (idealpointfp), no NAs
    # sender & receiver
    nodeocov("log_gdppc") +     # complainant's economic standard
    nodeicov("log_gdppc") +     # respondent's economic standard
    nodeocov("log_pop") +       # complainant's country scale
    nodeicov("log_pop") +       # respondent's country scale
    # gap between sender and receiver
    absdiff("log_gdppc") +      # economic gap
    absdiff("log_pop") +        # population gap
    nodeicov("log_cum_respondent") +
    nodeocov("log_cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
cat("\n--- Model 2 ---\n"); summary(model2)

# --- Model 2.1: only Political alignment (ideal point distance) ---
cat("\n=== Model 2: + Political Alignment (ip-complete, n =", n_nodes_ip, "nodes) ===\n")
model2.1 <- btergm(
    net_list_ip ~
        edges +
        mutual +
        gwidegree(decay = 0.5, fixed = TRUE) +
        gwodegree(decay = 0.5, fixed = TRUE) +
        edgecov(trade_cov_ip) +
        # edgecov(ally_cov_ip) +
        edgecov(pta_cov_ip) +
        edgecov(hhi_cov_ip) +
        edgecov(export_conc_cov_ip) +
        edgecov(import_dep_cov_ip) +
        edgecov(ideal_dist_cov_ip) +      # UN voting distance (idealpointfp), no NAs
        # sender & receiver
        nodeocov("log_gdppc") +     # complainant's economic standard
        nodeicov("log_gdppc") +     # respondent's economic standard
        nodeocov("log_pop") +       # complainant's country scale
        nodeicov("log_pop") +       # respondent's country scale
        # gap between sender and receiver
        absdiff("log_gdppc") +      # economic gap
        absdiff("log_pop") +        # population gap
        nodeicov("log_cum_respondent") +
        nodeocov("log_cum_complainant") +
        delrecip +
        memory(type = "stability"),
    R       = BTERGM_BOOTS,
    parallel = "multicore",
    ncpus   = 4
)
cat("\n--- Model 2.1 ---\n"); summary(model2.1)

# --- Model 3: + Democracy (ip+dem-complete node set) ---
# Separate node set from Model 2: drops nodes missing EITHER idealpointfp OR
# v2x_polyarchy. Some UN members (small Pacific islands, micro-states) have
# ideal points but no V-Dem — they appear in net_list_ip but not here.
cat("\n=== Model 3: + Democracy (ip+dem-complete, n =", n_nodes_ip_dem, "nodes) ===\n")
model3 <- btergm(
  net_list_ip_dem ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip_dem) +
    edgecov(ally_cov_ip_dem) +
    edgecov(pta_cov_ip_dem) +
    edgecov(hhi_cov_ip_dem) +
    edgecov(export_conc_cov_ip_dem) +
    edgecov(import_dep_cov_ip_dem) +
    edgecov(ideal_dist_cov_ip_dem) +
    # sender & receiver
    nodeocov("log_gdppc") +     # complainant's economic standard
    nodeicov("log_gdppc") +     # respondent's economic standard
    nodeocov("log_pop") +       # complainant's country scale
    nodeicov("log_pop") +       # respondent's country scale
    # gap between sender and receiver
    absdiff("log_gdppc") +      # economic gap
    absdiff("log_pop") +        # population gap
    nodeicov("log_cum_respondent") +
    nodeocov("log_cum_complainant") +
    nodeocov("v2x_polyarchy") +       # sender democracy
    nodeicov("v2x_polyarchy") +       # receiver democracy
    nodeocov("election_binary") +     # sender election year
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
cat("\n--- Model 3 ---\n"); summary(model3)

# --- Model 1L: Lagged trade robustness ---
# Drop 1995: total_trade_ij_t1 is all 0 for 1995 (no 1994 data). Keeping 1995
# would assign "zero prior trade" to every dyad equally, biasing the lag
# coefficient toward zero and creating spurious initialization-year effects.
# btergm uses t=1 as initialization regardless; starting at 1996 still gives
# 29 estimation years and avoids the degenerate 1995 trade_t1 slice.
years_lag           <- years[years != YEAR_START]                 # 1996–2024
years_lag_chr       <- as.character(years_lag)
net_list_lag        <- net_list[years_lag_chr]
trade_cov_t1_lag    <- trade_cov_t1[years_lag_chr]
ally_cov_lag        <- ally_cov[years_lag_chr]
pta_cov_lag         <- pta_cov[years_lag_chr]
hhi_cov_lag         <- hhi_cov[years_lag_chr]
export_conc_cov_lag <- export_conc_cov[years_lag_chr]
import_dep_cov_lag  <- import_dep_cov[years_lag_chr]

cat("\n=== Model 1L: Lagged Trade (t-1), 1996-2024 ===\n")
model1L <- btergm(
  net_list_lag ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_t1_lag) +       # trade at t-1 (no 1995 degenerate year)
    edgecov(ally_cov_lag) +
    edgecov(pta_cov_lag) +
    edgecov(hhi_cov_lag) +
    edgecov(export_conc_cov_lag) +
    edgecov(import_dep_cov_lag) +
    # sender & receiver
    nodeocov("log_gdppc") +     # complainant's economic standard
    nodeicov("log_gdppc") +     # respondent's economic standard
    nodeocov("log_pop") +       # complainant's country scale
    nodeicov("log_pop") +       # respondent's country scale
    # gap between sender and receiver
    absdiff("log_gdppc") +      # economic gap
    absdiff("log_pop") +        # population gap
    nodeicov("log_cum_respondent") +
    nodeocov("log_cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
cat("\n--- Model 1L ---\n"); summary(model1L)

# ===========================================================================
# 7. RESULTS TABLE
# ===========================================================================
#
# MODEL SPECIFICATIONS SUMMARY
# ---------------------------------------------------------------------------
# DV (all models): Directed binary edge = 1 if complainant (exporter) filed a
#   WTO dispute against respondent (importer) in year t; 0 otherwise.
#   NOTE on direction: "exporter" = complainant and "importer" = respondent
#   throughout. The naming is inherited from the trade universe dataset.
#   adj[i,j] = 1 means country i (exporter/complainant) filed against j
#   (importer/respondent). nodeocov = sender = complainant; nodeicov =
#   receiver = respondent. Direction is correct.
#
# Model 0  — No-EUN Baseline
#   Dataset : ergm_dyad_year_eun (EUN rows excluded)
#   Node set: nation-states only (n = n_nodes_noeun), 1995–2024
#   Terms   : edges, mutual, GWIDegree(0.5), GWODegree(0.5),
#             log trade, ATOP, PTA, trade HHI, export conc, import dep,
#             complainant/respondent log-GDP/cap, log-pop, |GDP gap|,
#             |pop gap|, log past cases (C & R), delrecip, memory(stability)
#
# Model 1  — Full Node Set (incl. EUN)
#   Dataset : ergm_dyad_year_eun (all rows)
#   Node set: nation-states + EUN (n = n_nodes), 1995–2024
#   Terms   : same as Model 0
#
# Model 2  — + Political Alignment
#   Dataset : ergm_dyad_year_eun (IP-complete: drops non-UN members)
#   Node set: UN-member states + EUN (n = n_nodes_ip), 1995–2024
#   Terms   : Model 1 + UN ideal point distance (idealpointfp)
#
# Model 3  — + Democracy
#   Dataset : ergm_dyad_year_eun (IP+V-Dem-complete)
#   Node set: countries with both idealpointfp & v2x_polyarchy (n = n_nodes_ip_dem), 1995–2024
#   Terms   : Model 2 + complainant/respondent V-Dem polyarchy + complainant election year
#
# Model 1L — Lagged Trade (Robustness)
#   Dataset : ergm_dyad_year_eun (full node set, 1996–2024; 1995 dropped)
#   Node set: n = n_nodes, 1996–2024 (29 years)
#   Terms   : Model 1 but trade replaced with trade(t-1)
# ---------------------------------------------------------------------------

# Diagnostic: print coefficient names from each model for verification
cat("\n--- Coefficient names (for coef_map verification) ---\n")
cat("model0:", paste(names(coef(model0)), collapse=", "), "\n")
cat("model1:", paste(names(coef(model1)), collapse=", "), "\n")
cat("model2:", paste(names(coef(model2)), collapse=", "), "\n")
cat("model3:", paste(names(coef(model3)), collapse=", "), "\n")
cat("model1L:", paste(names(coef(model1L)), collapse=", "), "\n")

# ---------------------------------------------------------------------------
# Unified coefficient map: maps btergm internal names -> informative labels.
# Different models use different list-object names for the same covariate
# (e.g., trade_cov_noeun vs trade_cov vs trade_cov_ip), so each variant is
# explicitly mapped to the same display label. Run the diagnostic block above
# and compare to names(coef(modelX)) if any rows appear misaligned.
# ---------------------------------------------------------------------------
coef_map <- list(
  # --- Structural terms ---
  "edges"                           = "Edges (Baseline)",
  "mutual"                          = "Reciprocity",
  "gwidegree.fixed.0.5"             = "GW In-degree (decay=0.5)",
  "gwodegree.fixed.0.5"             = "GW Out-degree (decay=0.5)",

  # --- Trade edge covariate (log): all model variants ---
  "edgecov.trade_cov_noeun"         = "Log Bilateral Trade",      # M0
  "edgecov.trade_cov"               = "Log Bilateral Trade",      # M1
  "edgecov.trade_cov_ip"            = "Log Bilateral Trade",      # M2
  "edgecov.trade_cov_ip_dem"        = "Log Bilateral Trade",      # M3
  "edgecov.trade_cov_t1_lag"        = "Log Bilateral Trade (t$-$1)", # M1L

  # --- Alliance ---
  "edgecov.ally_cov_noeun"          = "ATOP Alliance",
  "edgecov.ally_cov"                = "ATOP Alliance",
  "edgecov.ally_cov_ip"             = "ATOP Alliance",
  "edgecov.ally_cov_ip_dem"         = "ATOP Alliance",
  "edgecov.ally_cov_lag"            = "ATOP Alliance",

  # --- PTA ---
  "edgecov.pta_cov_noeun"           = "PTA Exists",
  "edgecov.pta_cov"                 = "PTA Exists",
  "edgecov.pta_cov_ip"              = "PTA Exists",
  "edgecov.pta_cov_ip_dem"          = "PTA Exists",
  "edgecov.pta_cov_lag"             = "PTA Exists",

  # --- Sector concentration ---
  "edgecov.hhi_cov_noeun"           = "Trade Sector HHI",
  "edgecov.hhi_cov"                 = "Trade Sector HHI",
  "edgecov.hhi_cov_ip"              = "Trade Sector HHI",
  "edgecov.hhi_cov_ip_dem"          = "Trade Sector HHI",
  "edgecov.hhi_cov_lag"             = "Trade Sector HHI",

  "edgecov.export_conc_cov_noeun"   = "Max Export Concentration (C$\\to$R)",
  "edgecov.export_conc_cov"         = "Max Export Concentration (C$\\to$R)",
  "edgecov.export_conc_cov_ip"      = "Max Export Concentration (C$\\to$R)",
  "edgecov.export_conc_cov_ip_dem"  = "Max Export Concentration (C$\\to$R)",
  "edgecov.export_conc_cov_lag"     = "Max Export Concentration (C$\\to$R)",

  "edgecov.import_dep_cov_noeun"    = "Max Import Dependence (R$\\to$C)",
  "edgecov.import_dep_cov"          = "Max Import Dependence (R$\\to$C)",
  "edgecov.import_dep_cov_ip"       = "Max Import Dependence (R$\\to$C)",
  "edgecov.import_dep_cov_ip_dem"   = "Max Import Dependence (R$\\to$C)",
  "edgecov.import_dep_cov_lag"      = "Max Import Dependence (R$\\to$C)",

  # --- Political alignment (Model 2+) ---
  "edgecov.ideal_dist_cov_ip"       = "UN Voting Distance",
  "edgecov.ideal_dist_cov_ip_dem"   = "UN Voting Distance",

  # --- Node: complainant (out-degree / sender) ---
  "nodeocov.log_gdppc"              = "Complainant GDP/capita (log)",
  "nodeocov.log_pop"                = "Complainant Population (log)",
  "nodeocov.log_cum_complainant"    = "Complainant Past Cases (log)",
  "nodeocov.v2x_polyarchy"          = "Complainant Democracy (V-Dem)",
  "nodeocov.election_binary"        = "Complainant Election Year",

  # --- Node: respondent (in-degree / receiver) ---
  "nodeicov.log_gdppc"              = "Respondent GDP/capita (log)",
  "nodeicov.log_pop"                = "Respondent Population (log)",
  "nodeicov.log_cum_respondent"     = "Respondent Past Cases (log)",
  "nodeicov.v2x_polyarchy"          = "Respondent Democracy (V-Dem)",

  # --- Dyadic gap ---
  "absdiff.log_gdppc"               = "|GDP/capita Gap| (log)",
  "absdiff.log_pop"                 = "|Population Gap| (log)",

  # --- Temporal ---
  "delrecip"                        = "Delayed Reciprocity",
  "memory.stability"                = "Network Stability (memory)"
)

# Informative model names
model_names_short <- c(
  "M0: No-EUN",
  "M1: Full",
  "M2: +Alignment",
  "M3: +Democracy",
  "M1L: Lagged Trade"
)
model_names_long <- c(
  "No-EUN Baseline",
  "Full + Trade",
  "+ UN Alignment",
  "+ Democracy",
  "Lagged Trade (t-1)"
)

# Screen output
screenreg(
  list(model0, model1, model2, model3, model1L),
  custom.model.names = model_names_short,
  custom.coef.map    = coef_map,
  digits             = 3
)

# HTML output
htmlreg(
  list(model0, model1, model2, model3, model1L),
  file               = "Data/Output/tergm_results.html",
  custom.model.names = model_names_long,
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "TERGM Results: WTO Dispute Initiation (Complainant $\\to$ Respondent), 1995--2024",
  caption.above      = TRUE
)
cat("HTML results saved to Data/Output/tergm_results.html\n")

# LaTeX output — full table for paper
texreg(
  list(model0, model1, model2, model3, model1L),
  file               = "Data/Output/tergm_results.tex",
  custom.model.names = model_names_long,
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "TERGM Results: WTO Dispute Initiation (Complainant $\\to$ Respondent), 1995--2024",
  caption.above      = TRUE,
  label              = "tab:tergm_main",
  fontsize           = "small",
  use.packages       = FALSE,        # add \usepackage{booktabs} etc. in preamble
  booktabs           = TRUE,
  dcolumn            = FALSE,
  sideways           = FALSE,
  longtable          = FALSE,
  custom.note       = paste0(
    "\\textit{Notes:} Bootstrapped TERGM via \\texttt{btergm} (R = ", BTERGM_BOOTS, " replications). ",
    "95\\% confidence intervals in brackets. ",
    "DV: directed binary edge = 1 if complainant filed a WTO dispute against respondent in year $t$. ",
    "``Complainant'' = exporter node (out-degree/sender); ``Respondent'' = importer node (in-degree/receiver). ",
    "M0 excludes the EU as a unitary actor (EUN); M1--M1L include EUN. ",
    "M2--M3 restrict to UN-member states where UN ideal point scores are available; M3 additionally requires V-Dem coverage. ",
    "Trade variables: BACI HS92, log-transformed. ",
    "Cumulative past cases log-transformed (log1p). ",
    "M1L: year 1995 dropped (no t-1 trade data)."
  )
)
cat("LaTeX results saved to Data/Output/tergm_results.tex\n")

# LaTeX output — compact table for slides (core models only: M1, M2, M3)
texreg(
  list(model1, model2, model3),
  file               = "Data/Output/tergm_results_slides.tex",
  custom.model.names = c("Baseline", "+ UN Alignment", "+ Democracy"),
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "WTO Dispute Initiation (TERGM), 1995--2024",
  caption.above      = TRUE,
  label              = "tab:tergm_slides",
  fontsize           = "footnotesize",
  use.packages       = FALSE,
  booktabs           = TRUE,
  dcolumn            = FALSE,
  custom.note       = paste0(
    "\\textit{Notes:} Bootstrapped TERGM, R = ", BTERGM_BOOTS, " replications. ",
    "95\\% CIs in brackets. DV = WTO dispute filing (Complainant $\\to$ Respondent). ",
    "Cumulative past cases log-transformed."
  )
)
cat("Slides LaTeX saved to Data/Output/tergm_results_slides.tex\n")

# ===========================================================================
# 8. GOODNESS-OF-FIT  (Model 2 — main specification)
# ===========================================================================

cat("\n=== Goodness-of-fit (Model 2) ===\n")
gof2 <- gof(model2,
            statistics = c(dsp, esp, ideg, odeg, geodesic),
            nsim = 100)
pdf("Data/Output/tergm_gof.pdf", width = 10, height = 8)
plot(gof2)
dev.off()
cat("GOF plot saved to Data/Output/tergm_gof.pdf\n")

# ===========================================================================
# 9. SAVE PREPARED DATA
# ===========================================================================

save(net_list, trade_cov, trade_cov_t1, ally_cov, pta_cov, depth_cov,
     ideal_dist_cov, all_nodes, n_nodes, years,
     file = "Data/Output/tergm_prepared_data.RData")

save(net_list_noeun, trade_cov_noeun, trade_cov_t1_noeun,
     ally_cov_noeun, pta_cov_noeun, ideal_dist_cov_noeun,
     all_nodes_noeun, n_nodes_noeun, years,
     file = "Data/Output/tergm_prepared_data_noeun.RData")

save(net_list_ip, trade_cov_ip, trade_cov_t1_ip, ally_cov_ip, pta_cov_ip,
     depth_cov_ip, ideal_dist_cov_ip, hhi_cov_ip, export_conc_cov_ip,
     import_dep_cov_ip, all_nodes_ip, n_nodes_ip, nodes_missing_ip, years,
     file = "Data/Output/tergm_prepared_data_ip.RData")

save(net_list_ip_dem, trade_cov_ip_dem, trade_cov_t1_ip_dem, ally_cov_ip_dem,
     pta_cov_ip_dem, depth_cov_ip_dem, ideal_dist_cov_ip_dem, hhi_cov_ip_dem,
     export_conc_cov_ip_dem, import_dep_cov_ip_dem,
     all_nodes_ip_dem, n_nodes_ip_dem, nodes_missing_ip_dem, years,
     file = "Data/Output/tergm_prepared_data_ip_dem.RData")

cat("Network data saved to Data/Output/tergm_prepared_data*.RData\n")

# ===========================================================================
# 10. NOTES FOR PAPER
# ===========================================================================

cat("\n",
    "==========================================================\n",
    "NOTES FOR PAPER:\n",
    "==========================================================\n",
    "1. Analysis period:", YEAR_START, "-", YEAR_END, "\n",
    "2. Full node set:", n_nodes, "countries/entities (fixed across years)\n",
    "3. No-EUN node set:", n_nodes_noeun, "countries\n",
    "   Ideal-point-complete (Model 2):", n_nodes_ip, "countries\n",
    "   Ip+Dem-complete (Model 3):", n_nodes_ip_dem, "countries\n",
    "   Dropped for missing idealpointfp:", paste(sort(nodes_missing_ip), collapse=", "), "\n",
    "   Additionally dropped for missing v2x_polyarchy (Model 3 only):",
    paste(sort(setdiff(nodes_missing_ip_dem, nodes_missing_ip)), collapse=", "), "\n",
    "4. Network type: directed binary (C->R disputes only)\n",
    "5. Missing data:\n",
    "   - Trade: NA -> 0 (no bilateral trade on record)\n",
    "   - ATOP: NA -> 0; no lagged ATOP in dataset\n",
    "   - PTA: NA -> 0 (not in DESTA universe)\n",
    "   - Ideal point distance: nodes dropped (not imputed) — 0 is a valid\n",
    "     substantive value; Models 2 & 3 use ip-complete node set.\n",
    "     idealpointall is universally missing for 2024; idealpointfp used.\n",
    "   - V-Dem: ip-complete set is also V-Dem complete (verified at runtime).\n",
    "   - Model 1L: 1995 dropped (lagged trade all 0 for 1995 — no 1994 data).\n",
    "   - GDP/pop: carry-forward for <2% gaps\n",
    "   - election_binary: NA -> 0\n",
    "   - CINC: NOT included (COW ends 2016)\n",
    "   - fdi (% GDP): NOT included (ambiguous for EUN)\n",
    "6. EUN node attrs: GDP/pop/GDPPC/WGI/V-Dem/ideal points imputed\n",
    "   from GDP-weighted member-state aggregation (scripts/impute_eun_meta.py)\n",
    "7. Section covariates (from bilateral_trade_section_wto.csv via build_ergm_data.py):\n",
    "   - trade_hhi: HHI of dyadic trade across HS sections (within-dyad concentration)\n",
    "     High = trade concentrated in few sectors; low = diversified\n",
    "   - max_export_conc: i's max section export share going to j across all sections\n",
    "     High = j is a dominant destination for i's most important export sector\n",
    "   - max_reverse_dep: j's max section export share going to i (import leverage proxy)\n",
    "     High = i is a dominant destination for j's most important export sector\n",
    "   All three are DIRECTED (not symmetrised); NA -> 0 for one-way flows\n",
    "8. Estimation: bootstrapped TERGM via btergm, R =", BTERGM_BOOTS, "replications\n",
    "==========================================================\n")
