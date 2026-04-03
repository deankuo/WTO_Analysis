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
#   Model 2 : + UN Voting Alignment (ideal point distance, ip-complete sample)
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
suppressPackageStartupMessages({
    library(network)
    library(sna)      # load before btergm so btergm::gof wins the namespace
    library(btergm)
    library(texreg)
    library(dplyr)
    library(tidyr)
})

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
YEAR_END   <- 2018

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

BTERGM_BOOTS <- 1000   # use 200 for testing, 1000 for final run

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
saveRDS(model0, "Data/Output/model0_robust.rds")
gc()

# --- Model 1: Full node set + structural + trade ---
cat("\n=== Model 1: Full (incl. EUN) — Structural + Trade ===\n")
start_time <- Sys.time()
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
end_time <- Sys.time()
execution_time <- end_time - start_time
print(execution_time)
cat("\n--- Model 1 ---\n"); summary(model1)
saveRDS(model1, "Data/Output/model1_robust.rds")
gc()

# --- Model 2: + UN Voting Alignment (IP-complete; novel geopolitical channel) ---
# IP-complete node set: non-UN members dropped because idealpointfp is
# structurally missing for them (0 is a valid value, so not imputed).
# No ATOP here — isolates the UN voting distance channel cleanly.
cat("\n=== Model 2: + UN Alignment (ip-complete, n =", n_nodes_ip, "nodes) ===\n")
start_time <- Sys.time()
model2 <- btergm(
  net_list_ip ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip) +
    edgecov(pta_cov_ip) +             # no ATOP alliance
    edgecov(hhi_cov_ip) +
    edgecov(export_conc_cov_ip) +
    edgecov(import_dep_cov_ip) +
    edgecov(ideal_dist_cov_ip) +      # UN voting distance (idealpointfp)
    nodeocov("log_gdppc") +
    nodeicov("log_gdppc") +
    nodeocov("log_pop") +
    nodeicov("log_pop") +
    absdiff("log_gdppc") +
    absdiff("log_pop") +
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
cat("\n--- Model 2 ---\n"); summary(model2)
saveRDS(model2, "Data/Output/model2_robust.rds")
gc()

# --- Model 3: + Alliance & UN Alignment (IP-complete; both political channels) ---
# Same IP-complete node set. Adds ATOP alongside UN IP to test whether both
# political channels operate jointly (combines M1 ally with M2 ideal point).
cat("\n=== Model 3: + Alliance & UN Alignment (ip-complete, n =", n_nodes_ip, "nodes) ===\n")
start_time <- Sys.time()
model3 <- btergm(
  net_list_ip ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip) +
    edgecov(ally_cov_ip) +            # ATOP alliance
    edgecov(pta_cov_ip) +
    edgecov(hhi_cov_ip) +
    edgecov(export_conc_cov_ip) +
    edgecov(import_dep_cov_ip) +
    edgecov(ideal_dist_cov_ip) +      # UN voting distance
    nodeocov("log_gdppc") +
    nodeicov("log_gdppc") +
    nodeocov("log_pop") +
    nodeicov("log_pop") +
    absdiff("log_gdppc") +
    absdiff("log_pop") +
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
cat("\n--- Model 3 ---\n"); summary(model3)
saveRDS(model3, "Data/Output/model3_robust.rds")
gc()

# --- Model 4: + Democracy (IP+dem-complete; ally + UN IP + democracy) ---
# Drops nodes missing EITHER idealpointfp OR v2x_polyarchy.
# Full specification: both political channels + democratic institution controls.
cat("\n=== Model 4: + Democracy (ip+dem-complete, n =", n_nodes_ip_dem, "nodes) ===\n")
start_time <- Sys.time()
model4 <- btergm(
  net_list_ip_dem ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip_dem) +
    edgecov(ally_cov_ip_dem) +        # ATOP alliance
    edgecov(pta_cov_ip_dem) +
    edgecov(hhi_cov_ip_dem) +
    edgecov(export_conc_cov_ip_dem) +
    edgecov(import_dep_cov_ip_dem) +
    edgecov(ideal_dist_cov_ip_dem) +  # UN voting distance
    nodeocov("log_gdppc") +
    nodeicov("log_gdppc") +
    nodeocov("log_pop") +
    nodeicov("log_pop") +
    absdiff("log_gdppc") +
    absdiff("log_pop") +
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
end_time <- Sys.time()
execution_time <- end_time - start_time
print(execution_time)
cat("\n--- Model 4 ---\n"); summary(model4)
saveRDS(model4, "Data/Output/model4_robust.rds")
gc()

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
#   Node set: nation-states + EUN (n = n_nodes), 1995–2018
#   Terms   : same as Model 0
#
# Model 2  — + UN Voting Alignment (IP-complete; novel geopolitical channel)
#   Dataset : ergm_dyad_year_eun (IP-complete: drops non-UN members)
#   Node set: UN-member states + EUN (n = n_nodes_ip), 1995–2024
#   Terms   : Model 1 + UN ideal point distance; no ATOP
#   Purpose : Isolates the novel geopolitical alignment channel independently
#
# Model 3  — + Alliance & UN Alignment (IP-complete; both political channels)
#   Dataset : ergm_dyad_year_eun (IP-complete: drops non-UN members)
#   Node set: UN-member states + EUN (n = n_nodes_ip), 1995–2024
#   Terms   : Model 1 + ATOP + UN ideal point distance
#   Purpose : Tests both political channels jointly; direct comparison with
#             M2 shows the marginal contribution of adding ATOP
#
# Model 4  — + Democracy (full model: ally + UN IP + democracy)
#   Dataset : ergm_dyad_year_eun (IP+V-Dem-complete)
#   Node set: countries with both idealpointfp & v2x_polyarchy (n = n_nodes_ip_dem), 1995–2024
#   Terms   : Model 3 + V-Dem polyarchy + election year
#   Purpose : Both political channels + democratic institution controls
#
# NOTE ON TIME PERIOD: Main analysis uses 1995–2024. ATOP is forward-filled
#   through 2024 in ergm_dyad_year_eun.csv. A separate robustness check on
#   1995–2018 (actual ATOP coverage) can be run by setting YEAR_END = 2018.
#   Model files are named model0.rds, model1.rds, etc. (no _robust suffix).
#
# OUTPUT STRATEGY
#   Paper : M0–M4 main table (5 cols)
#   Slides: M1, M2, M3, M4 — progressive
# ---------------------------------------------------------------------------

# Diagnostic: print coefficient names from each model for verification
cat("\n--- Coefficient names (for coef_map verification) ---\n")
cat("model0  :", paste(names(coef(model0)),  collapse=", "), "\n")
cat("model1  :", paste(names(coef(model1)),  collapse=", "), "\n")
cat("model2  :", paste(names(coef(model2)),  collapse=", "), "\n")
cat("model3  :", paste(names(coef(model3)),  collapse=", "), "\n")
cat("model4  :", paste(names(coef(model4)),  collapse=", "), "\n")

# ---------------------------------------------------------------------------
# HOW TO INSPECT SAVED MODELS (readRDS workflow)
# ---------------------------------------------------------------------------
# To reload and inspect a saved model:
#
#   m2 <- readRDS("Data/Output/model2.rds")
#   summary(m2)                        # full table with CIs
#   names(coef(m2))                    # raw btergm coefficient names
#   texreg::extract(m2)@coef.names    # names as texreg sees them
#
# Note: btergm sometimes names edgecov terms by the R list name verbatim,
# e.g., "edgecov.ideal_dist_cov_ip" instead of "edgecov.ideal_dist".
# That is why standardize_coef_names() normalises them before table assembly.
#
# For robustness check (1995–2018), set YEAR_END <- 2018 and re-run.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# standardize_coef_names: normalise all model-specific edgecov names to
# canonical names before table extraction, so texreg merges them into a
# single row across models without relying on duplicate-label behaviour.
#
# Uses fixed-string grepl (no regex anchors) so it works regardless of
# the exact prefix/suffix btergm appends to edgecov term names.
# ---------------------------------------------------------------------------
standardize_coef_names <- function(model_obj) {
  tr <- texreg::extract(model_obj)
  cn <- tr@coef.names

  # ---- Edge covariates (order matters: specific before general) ----
  # Lagged trade before contemporaneous (both contain "trade_cov")
  cn[grepl("trade_cov_t1",    cn, fixed = TRUE)] <- "edgecov.trade_t1"
  cn[grepl("trade_cov",       cn, fixed = TRUE) &
     cn != "edgecov.trade_t1"]                   <- "edgecov.trade"
  # Broader trade_t1 fallback: btergm sometimes uses the R variable name verbatim
  cn[grepl("trade_t1",        cn, fixed = TRUE) &
     startsWith(cn, "edgecov") &
     cn != "edgecov.trade_t1"]                   <- "edgecov.trade_t1"

  cn[grepl("ally_cov",        cn, fixed = TRUE)] <- "edgecov.ally"
  cn[grepl("pta_cov",         cn, fixed = TRUE)] <- "edgecov.pta"
  cn[grepl("hhi_cov",         cn, fixed = TRUE)] <- "edgecov.hhi"
  cn[grepl("export_conc_cov", cn, fixed = TRUE)] <- "edgecov.export_conc"
  cn[grepl("import_dep_cov",  cn, fixed = TRUE)] <- "edgecov.import_dep"
  cn[grepl("ideal_dist_cov",  cn, fixed = TRUE)] <- "edgecov.ideal_dist"
  # Broader ideal_dist fallback: catches ideal_dist_cov_ip / ideal_dist_cov_ip_dem
  cn[grepl("ideal_dist",      cn, fixed = TRUE) &
     startsWith(cn, "edgecov") &
     cn != "edgecov.ideal_dist"]                 <- "edgecov.ideal_dist"

  # ---- Temporal structure terms ----
  cn[grepl("delrecip",        cn, fixed = TRUE)] <- "delrecip"
  cn[grepl("edgecov.memory",  cn, fixed = TRUE)] <- "memory.stability"

  # ---- Node covariates: democracy & election (Model 3 only) ----
  # btergm may retain the full vertex-attribute name verbatim (nodeocov.v2x_polyarchy)
  # or parenthetical form (nodeocov("v2x_polyarchy")).  Both are caught here.
  cn[grepl("v2x_polyarchy", cn, fixed = TRUE) &
     (startsWith(cn, "nodeocov") | grepl("nodeocov", cn, fixed = TRUE))] <- "nodeocov.v2x_polyarchy"
  cn[grepl("v2x_polyarchy", cn, fixed = TRUE) &
     (startsWith(cn, "nodeicov") | grepl("nodeicov", cn, fixed = TRUE))] <- "nodeicov.v2x_polyarchy"
  cn[grepl("election_binary", cn, fixed = TRUE)]                         <- "nodeocov.election_binary"

  tr@coef.names <- cn
  tr
}

# ---------------------------------------------------------------------------
# Canonical coefficient map — one key per variable.
# Model-specific edgecov names are normalised by standardize_coef_names().
# ---------------------------------------------------------------------------
coef_map <- list(
  # --- Structural ---
  "edges"                         = "Edges (Baseline)",
  "mutual"                        = "Reciprocity",
  "gwideg.fixed.0.5"              = "GW In-degree",
  "gwodeg.fixed.0.5"              = "GW Out-degree",
  # --- Trade ---
  "edgecov.trade"                 = "Bilateral Trade",
  "edgecov.trade_t1"              = "Bilateral Trade (t$-$1)",
  # --- Dyadic political / institutional ---
  "edgecov.ally"                  = "ATOP Alliance",
  "edgecov.pta"                   = "PTA Exists",
  # --- Sector trade structure ---
  "edgecov.hhi"                   = "Trade Sector HHI",
  "edgecov.export_conc"           = "Max Export Concentration",
  "edgecov.import_dep"            = "Max Import Dependence",
  # --- Geopolitical alignment ---
  "edgecov.ideal_dist"            = "UN Voting Distance",
  # --- Node: complainant (sender / out-degree) ---
  "nodeocov.log_gdppc"            = "Complainant GDP/capita",
  "nodeocov.log_pop"              = "Complainant Population",
  "nodeocov.log_cum_complainant"  = "Complainant Past Cases",
  "nodeocov.v2x_polyarchy"        = "Complainant Democracy (V-Dem)",
  "nodeocov.election_binary"      = "Complainant Election Year",
  # --- Node: respondent (receiver / in-degree) ---
  "nodeicov.log_gdppc"            = "Respondent GDP/capita",
  "nodeicov.log_pop"              = "Respondent Population",
  "nodeicov.log_cum_respondent"   = "Respondent Past Cases",
  "nodeicov.v2x_polyarchy"        = "Respondent Democracy (V-Dem)",
  # --- Dyadic gap ---
  "absdiff.log_gdppc"             = "GDP/capita Gap",
  "absdiff.log_pop"               = "Population Gap",
  # --- Temporal ---
  "delrecip"                      = "Delayed Reciprocity",
  "memory.stability"              = "Network Stability (memory)"
)

# Informative model names
# Paper: M0, M1, M2 (+UN), M3 (+Alliance+UN), M4 (+Democracy)
model_names_short <- c(
  "M0: No-EUN",
  "M1: Baseline",
  "M2: +UN Align",
  "M3: +Ally+UN",
  "M4: +Democracy"
)
model_names_long <- c(
  "No-EUN",
  "Baseline",
  "+UN Align",
  "+Ally+UN",
  "+Democracy"
)

# Slides: M1, M2, M3, M4 — progressive channel addition
model_names_slides <- c(
  "Baseline",
  "+UN Align",
  "+Ally+UN",
  "+Democracy"
)

# Pre-extract and normalise coefficient names for all output formats
tr_list_full   <- lapply(list(model0, model1, model2, model3, model4),
                         standardize_coef_names)
tr_list_paper  <- tr_list_full          # M0–M4 main table
tr_list_slides <- lapply(list(model1, model2, model3, model4), standardize_coef_names)

# --- Diagnostic: verify normalisation worked and coef_map keys are reachable ---
cat("\n--- Normalised coef names per model ---\n")
model_labels <- c("M0","M1","M2","M3","M4")
for (i in seq_along(tr_list_full)) {
  cat(model_labels[i], ":", paste(tr_list_full[[i]]@coef.names, collapse = ", "), "\n")
}
all_norm <- unique(unlist(lapply(tr_list_full, function(tr) tr@coef.names)))
missing_from_map <- setdiff(all_norm, names(coef_map))
missing_in_models <- setdiff(names(coef_map), all_norm)
if (length(missing_from_map) > 0)
  cat("\nWARN — coefficients in models but NOT in coef_map:\n ",
      paste(missing_from_map, collapse = "\n  "), "\n")
if (length(missing_in_models) > 0)
  cat("\nWARN — coef_map keys not found in any model (will appear blank):\n ",
      paste(missing_in_models, collapse = "\n  "), "\n")
if (length(missing_from_map) == 0 && length(missing_in_models) == 0)
  cat("\nAll coef names matched — table will be complete.\n")
# -------------------------------------------------------------------------

# Add \phantom padding so significance stars align across cells in each column.
# Skips SE rows (parenthesised values like $(0.123)$) and CI rows ([lo; hi]).
# Rule: *** stays as-is; ** gets \phantom{^{*}}; * gets \phantom{^{**}};
#       bare numeric cells get \phantom{^{***}}.
pad_star_cells <- function(lines) {
  sapply(lines, function(line) {
    if (!grepl("&", line, fixed = TRUE))      return(line)  # not a data row
    if (grepl("\\(\\s*[0-9]", line))          return(line)  # SE row: (0.123)
    if (grepl("[", line, fixed = TRUE))       return(line)  # CI row: [lo; hi]
    # Trailing star phantoms (normalise cell width to ^{***})
    line <- gsub("(\\^\\{\\*\\*\\})(\\$)",   "\\1\\\\phantom{^{*}}\\2",   line)
    line <- gsub("(\\^\\{\\*\\})(\\$)",      "\\1\\\\phantom{^{**}}\\2",  line)
    line <- gsub("(\\$-?[0-9][^$^]*)(\\$)", "\\1\\\\phantom{^{***}}\\2", line)
    # Leading minus phantom for positive numbers (align with negatives)
    line <- gsub("\\$([0-9])",               "$\\\\phantom{-}\\1",        line)
    line
  }, USE.NAMES = FALSE)
}

# Convert a texreg-generated .tex to xltabular format matching result_example.tex.
# Replaces floating table/sidewaystable with a non-floating xltabular that
# supports page breaks and places the note below the closing brace.
# Two-row header: numbers row (repeated on continuation pages) + model names row.
# Significance footnote always added inside \endlastfoot.
post_process_tex <- function(filepath, arraystretch = 0.9, tabcolsep = "2pt") {
  lines <- readLines(filepath)

  # ---- 1. Extract caption ----
  cap_idx      <- grep("^\\\\caption\\{", lines)
  caption_text <- if (length(cap_idx) > 0)
    sub("^\\\\caption\\{(.+)\\}\\s*$", "\\1", lines[cap_idx[1]])
  else ""

  # ---- 2. Extract label ----
  lab_idx    <- grep("^\\\\label\\{", lines)
  label_text <- if (length(lab_idx) > 0)
    sub("^\\\\label\\{([^}]+)\\}\\s*$", "\\1", lines[lab_idx[1]])
  else ""

  # ---- 3. Column count from \begin{tabular}{spec} ----
  tab_idx <- grep("^\\\\begin\\{tabular", lines)
  n_cols  <- 2L
  if (length(tab_idx) > 0) {
    braces <- regmatches(lines[tab_idx[1]], gregexpr("\\{[^}]+\\}", lines[tab_idx[1]]))[[1]]
    if (length(braces) > 0) {
      spec   <- gsub("[{}]", "", braces[length(braces)])
      tokens <- strsplit(trimws(spec), "\\s+")[[1]]
      tokens <- tokens[nchar(tokens) > 0 & !grepl("^@", tokens)]
      n_cols <- length(tokens)
    }
  }
  n_dat <- max(1L, n_cols - 1L)

  # ---- 4. Header rows (between \toprule and first \midrule) ----
  toprule_idx   <- grep("^\\\\toprule",    lines)[1]
  all_midrule   <- grep("^\\\\midrule",    lines)
  first_midrule <- all_midrule[1]
  header_rows   <- if (!is.na(toprule_idx) && !is.na(first_midrule) &&
                       first_midrule > toprule_idx + 1L)
    lines[(toprule_idx + 1L):(first_midrule - 1L)]
  else character(0)

  # ---- 5. Body rows (first \midrule + 1 to \bottomrule - 1) ----
  bottomrule_idx <- grep("^\\\\bottomrule", lines)[1]
  body_rows <- if (!is.na(first_midrule) && !is.na(bottomrule_idx) &&
                   bottomrule_idx > first_midrule + 1L)
    lines[(first_midrule + 1L):(bottomrule_idx - 1L)]
  else character(0)
  body_rows <- pad_star_cells(body_rows)

  # ---- 6. Note text from \multicolumn{N}{l}{\tiny{...}} ----
  note_idx  <- grep("\\\\multicolumn.*\\\\tiny", lines)
  note_text <- if (length(note_idx) > 0)
    sub("^\\\\multicolumn\\{[0-9]+\\}\\{l\\}\\{\\\\tiny\\{(.+)\\}\\}\\s*$",
        "\\1", lines[note_idx[1]])
  else ""

  # ---- Build xltabular column spec ----
  # Use X (stretchy) only for 5+ model tables; fixed p{} for fewer models to
  # prevent the label column from consuming most of \textwidth.
  first_col <- if (n_dat >= 5L) {
    "X"
  } else {
    widths <- c("0.55", "0.48", "0.42", "0.38")
    w <- widths[min(n_dat, 4L)]
    sprintf(">{{\\raggedright\\arraybackslash}}p{%s\\textwidth}", w)
  }
  xlt_spec <- paste0("@{} ", first_col, " ", paste(rep("c", n_dat), collapse = " "), " @{}")

  # ---- Numbers row for multi-column tables (appears in both headers) ----
  numbers_row <- if (n_dat > 1L) {
    num_cells <- c("", paste0("(", seq_len(n_dat), ")"))
    paste0(paste(num_cells, collapse = " & "), " \\\\")
  } else character(0)

  # ---- Significance footnote for \endlastfoot ----
  sig_note <- sprintf(
    "\\multicolumn{%d}{@{}l}{\\rule{0pt}{1.5em}\\normalsize $^{*}p<0.05$; $^{**}p<0.01$; $^{***}p<0.001$} \\\\",
    n_cols
  )

  # ---- Assemble output ----
  out <- c(
    "% xltabular",
    "{ % replace \\begin{small}",
    "\\small",
    sprintf("\\renewcommand{\\arraystretch}{%.1f}", arraystretch),
    sprintf("\\setlength{\\tabcolsep}{%s}", tabcolsep),
    "",
    sprintf("\\begin{xltabular}{\\textwidth}{%s}", xlt_spec),
    sprintf("\\caption{%s} \\label{%s} \\\\", caption_text, label_text),
    "\\toprule",
    numbers_row,
    header_rows,
    "\\midrule",
    "\\endfirsthead",
    "",
    sprintf("\\multicolumn{%d}{c}{Table \\ref{%s} (Continued)} \\\\", n_cols, label_text),
    "\\toprule",
    numbers_row,
    "\\midrule",
    "\\endhead",
    "",
    "\\bottomrule",
    sig_note,
    "\\endlastfoot",
    "",
    body_rows,
    "\\end{xltabular}",
    "}"
  )
  if (nchar(trimws(note_text)) > 0)
    out <- c(out, sprintf("\\noindent \\normalsize %s", note_text))

  writeLines(out, filepath)
  invisible(filepath)
}

# Screen output (all models)
screenreg(
  tr_list_full,
  custom.model.names = model_names_short,
  custom.coef.map    = coef_map,
  digits             = 3
)

# HTML output (all models)
htmlreg(
  tr_list_full,
  file               = "Data/Output/tergm_results_robust.html",
  custom.model.names = model_names_long,
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "TERGM Results: WTO Dispute Initiation (Complainant $\\to$ Respondent), 1995--2024",
  caption.above      = TRUE
)
cat("HTML results saved to Data/Output/tergm_results.html\n")

paper_note <- paste0(
  "\\textit{Notes:} Bootstrapped TERGM via \\texttt{btergm} (R = ", BTERGM_BOOTS, " replications). ",
  "95\\% confidence intervals in brackets. ",
  "DV: directed binary edge = 1 if complainant filed a WTO dispute against respondent in year $t$. ",
  "``Complainant'' = sender node (out-degree); ``Respondent'' = receiver node (in-degree). ",
  "M0 excludes EUN; M1--M4 include EUN as a unitary EU actor. ",
  "M2--M4: IP-complete sample (non-UN members dropped; idealpointfp not imputed). ",
  "M2 adds UN voting distance (no ATOP, isolates geopolitical channel); ",
  "M3 adds ATOP alongside UN IP; ",
  "M4 adds V-Dem democracy controls (IP+V-Dem-complete sample). ",
  "Trade: BACI HS92, log-transformed. Cumulative past cases: log1p. ",
  "Analysis period: ", YEAR_START, "--", YEAR_END, "."
)

# LaTeX — main paper table (M0–M3, without M1L to keep width manageable)
texreg(
  tr_list_paper,
  file               = "Data/Output/tergm_results_robust.tex",
  custom.model.names = model_names_long,
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "TERGM Results: WTO Dispute Initiation (Complainant $\\to$ Respondent), 1995--2024",
  caption.above      = TRUE,
  label              = "tab:tergm_main",
  fontsize           = "scriptsize",
  use.packages       = FALSE,
  booktabs           = TRUE,
  dcolumn            = FALSE,
  longtable          = FALSE,
  custom.note        = paper_note
)
post_process_tex("Data/Output/tergm_results_robust.tex")
cat("LaTeX (paper) saved to Data/Output/tergm_results.tex\n")

# LaTeX — slides table (M1–M4: progressive channel addition)
texreg(
  tr_list_slides,
  file               = "Data/Output/tergm_results_slides.tex",
  custom.model.names = model_names_slides,
  custom.coef.map    = coef_map,
  digits             = 3,
  caption            = "WTO Dispute Initiation (TERGM), 1995--2024",
  caption.above      = TRUE,
  label              = "tab:tergm_slides",
  fontsize           = "scriptsize",
  use.packages       = FALSE,
  booktabs           = TRUE,
  dcolumn            = FALSE
)
post_process_tex("Data/Output/tergm_results_slides.tex")
cat("Slides LaTeX saved to Data/Output/tergm_results_slides.tex\n")

# ===========================================================================
# 8. GOODNESS-OF-FIT — All Models (M0–M4), Comparison Plots
# ===========================================================================
#
# Statistics used and why:
#   ideg, odeg        in/out-degree distributions — basic network structure
#   triad.directed    directed 16-type triad census:
#                       "102" = mutual dyad  → reciprocity check
#                       "030T"/"030C"        → transitive vs cyclic closure
#                       covers what the professor asked (reciprocity + triadic)
#   rocpr             ROC + precision-recall — predictive performance
#
# Statistics NOT used:
#   dsp / esp         require ensure_network() → fail for btergm list-of-networks
#   geodesic          Matrix sparse-matrix error; infeasible for large directed nets
#
# Comparison approach: for each statistic, one PDF with 5 panels (one per model)
# arranged side-by-side so the same indicator is visible across all specifications.
# ===========================================================================

suppressPackageStartupMessages({
    library(png)
    library(grid)
    library(gridExtra)
})

NGOF_ALL <- 200   # simulations per model

gof_model_list <- list(model0, model1, model2, model3, model4)
gof_model_lbls <- c("M0: No-EUN", "M1: Baseline", "M2: +UN Align",
                     "M3: +Ally+UN", "M4: +Democracy")

# ---------------------------------------------------------------------------
# Helper: capture a base R plot expression as a grid rasterGrob
# ---------------------------------------------------------------------------
capture_plot_grob <- function(plot_fn, width_px = 900, height_px = 600, res = 150) {
    tmp <- tempfile(fileext = ".png")
    on.exit(unlink(tmp), add = TRUE)
    png(tmp, width = width_px, height = height_px, res = res)
    tryCatch(
        plot_fn(),
        error = function(e) {
            plot.new()
            text(0.5, 0.5, paste("Error:", conditionMessage(e)),
                 cex = 0.7, col = "red")
        }
    )
    dev.off()
    img <- png::readPNG(tmp)
    grid::rasterGrob(img, interpolate = TRUE,
                     width  = unit(1, "npc"),
                     height = unit(1, "npc"))
}

# ---------------------------------------------------------------------------
# Helper: assemble 5-model comparison PDF for a given list of gof objects
# ---------------------------------------------------------------------------
make_gof_comparison_pdf <- function(gof_list, labels, outpath, main_title,
                                    panel_w = 4, panel_h = 4,
                                    width_px = 900, height_px = 650) {
    grobs <- lapply(seq_along(gof_list), function(i) {
        if (is.null(gof_list[[i]])) {
            return(grid::textGrob(paste0(labels[i], "\n(failed)"),
                                  gp = grid::gpar(fontsize = 9, col = "grey50")))
        }
        capture_plot_grob(
            function() {
                plot(gof_list[[i]])
                title(main = labels[i], cex.main = 0.9, line = 0.3)
            },
            width_px = width_px, height_px = height_px
        )
    })
    pdf(outpath, width = panel_w * length(gof_list), height = panel_h + 0.7)
    gridExtra::grid.arrange(
        grobs = grobs, nrow = 1,
        top   = grid::textGrob(main_title,
                               gp = grid::gpar(fontsize = 12, fontface = "bold"))
    )
    dev.off()
    cat("Saved:", outpath, "\n")
}

# ---------------------------------------------------------------------------
# (A) Degree distributions — ideg + odeg
# ---------------------------------------------------------------------------
cat("\n=== GOF (all models): in/out-degree distributions ===\n")
gof_deg_all <- lapply(seq_along(gof_model_list), function(i) {
    cat(sprintf("  %s ...\n", gof_model_lbls[i]))
    tryCatch(
        btergm::gof(gof_model_list[[i]], statistics = c(ideg, odeg),
                    nsim = NGOF_ALL),
        error = function(e) { cat("  FAILED:", conditionMessage(e), "\n"); NULL }
    )
})
saveRDS(gof_deg_all, "Data/Output/gof_degree_all.rds")
make_gof_comparison_pdf(
    gof_list   = gof_deg_all,
    labels     = gof_model_lbls,
    outpath    = "Data/Output/tergm_gof_degree_all.pdf",
    main_title = "GOF: In/Out-Degree Distributions (M0–M4)",
    panel_w = 4, panel_h = 3.5, width_px = 1000, height_px = 500
)

# Backward-compatible single plot for M2 (degree)
gof_deg <- gof_deg_all[[3]]   # model2 is index 3
if (!is.null(gof_deg)) {
    png("Data/Output/tergm_gof_deg.png", width = 10, height = 5,
        units = "in", res = 300)
    plot(gof_deg)
    dev.off()
    cat("Backward-compat M2 degree plot: Data/Output/tergm_gof_deg.png\n")
}

# ---------------------------------------------------------------------------
# (B) Triadic structure + reciprocity — triad.directed (16-type census)
#     The "102" mutual triad corresponds to dyadic reciprocity.
#     "030T" = transitive triple, "030C" = cyclic triple.
# ---------------------------------------------------------------------------
cat("\n=== GOF (all models): directed triad census (reciprocity + triadic structure) ===\n")
gof_triad_all <- lapply(seq_along(gof_model_list), function(i) {
    cat(sprintf("  %s ...\n", gof_model_lbls[i]))
    tryCatch(
        btergm::gof(gof_model_list[[i]], statistics = c(triad.directed),
                    nsim = NGOF_ALL),
        error = function(e) { cat("  FAILED:", conditionMessage(e), "\n"); NULL }
    )
})
saveRDS(gof_triad_all, "Data/Output/gof_triad_all.rds")
make_gof_comparison_pdf(
    gof_list   = gof_triad_all,
    labels     = gof_model_lbls,
    outpath    = "Data/Output/tergm_gof_triad_all.pdf",
    main_title = "GOF: Directed Triad Census — Reciprocity & Triadic Structure (M0–M4)",
    panel_w = 4, panel_h = 4.5, width_px = 1000, height_px = 750
)

# ---------------------------------------------------------------------------
# (C) Predictive performance — ROC + PR curves
# ---------------------------------------------------------------------------
cat("\n=== GOF (all models): ROC + precision-recall ===\n")
gof_roc_all <- lapply(seq_along(gof_model_list), function(i) {
    cat(sprintf("  %s ...\n", gof_model_lbls[i]))
    tryCatch(
        btergm::gof(gof_model_list[[i]], statistics = c(rocpr),
                    nsim = NGOF_ALL),
        error = function(e) { cat("  FAILED:", conditionMessage(e), "\n"); NULL }
    )
})
saveRDS(gof_roc_all, "Data/Output/gof_rocpr_all.rds")
make_gof_comparison_pdf(
    gof_list   = gof_roc_all,
    labels     = gof_model_lbls,
    outpath    = "Data/Output/tergm_gof_rocpr_all.pdf",
    main_title = "GOF: ROC + Precision-Recall Curves (M0–M4)",
    panel_w = 3.5, panel_h = 3.5, width_px = 800, height_px = 600
)

# Backward-compatible single plot for M2 (ROC/PR)
gof_roc <- gof_roc_all[[3]]
if (!is.null(gof_roc)) {
    png("Data/Output/tergm_gof_roc.png", width = 8, height = 5,
        units = "in", res = 300)
    par(mar = c(5, 4, 4, 2))
    plot(gof_roc)
    dev.off()
    cat("Backward-compat M2 ROC/PR plot: Data/Output/tergm_gof_roc.png\n")
}

cat("\n=== GOF outputs ===\n")
cat("  tergm_gof_degree_all.pdf    — in/out-degree distributions, all models\n")
cat("  tergm_gof_triad_all.pdf     — triad census (reciprocity + triadic closure), all models\n")
cat("  tergm_gof_rocpr_all.pdf     — ROC + PR curves, all models\n")
cat("  tergm_gof_deg.png           — M2 degree (backward-compat)\n")
cat("  tergm_gof_roc.png           — M2 ROC/PR (backward-compat)\n")
cat("  gof_degree_all.rds / gof_triad_all.rds / gof_rocpr_all.rds  — saved GOF objects\n")

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
