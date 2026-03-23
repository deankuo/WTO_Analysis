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
#   Model 3 : + Democracy & governance — ip-complete node set (same as Model 2;
#             ip-complete is also V-Dem complete; verified at runtime)
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
                "total_trade_ij_t1", "export_dependence_t1", "trade_dependence_t1",
                "total_trade_ij_t2", "total_trade_ij_t3",
                "trade_hhi",       "max_export_conc",    "max_reverse_dep",
                "trade_hhi_t1",    "max_export_conc_t1", "max_reverse_dep_t1")
for (v in trade_vars) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2b. DESTA / PTA ---
# label==1 means a PTA exists; NA means not in DESTA universe → treat as 0.
# NOTE: label_t1/label_t2/depth_index_t1 etc. are NOT in the dataset.
if ("label" %in% names(ergm_panel)) {
  ergm_panel$pta_exists <- ifelse(is.na(ergm_panel$label), 0L, as.integer(ergm_panel$label))
}
if ("depth_index" %in% names(ergm_panel)) {
  ergm_panel$depth_index[is.na(ergm_panel$depth_index)] <- 0
}

# --- 2c. ATOP alliance: NA -> 0 ---
# NOTE: atopally_t1/t2/t3 are NOT pre-computed in ergm_dyad_year_eun.csv.
#       Only the contemporaneous atopally is available.
atop_vars <- c("atopally", "defense", "offense", "neutral", "nonagg", "consul")
for (v in atop_vars) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2d. Severity scores: NA -> 0 ---
sev_vars <- grep("severity|rhetorical|systemic|escalation|domestic_victim",
                 names(ergm_panel), value = TRUE)
for (v in sev_vars) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0

# --- 2e. Disputed sector trade: NA -> 0 ---
for (v in grep("^disputed_", names(ergm_panel), value = TRUE)) {
  ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# --- 2f. Node attributes ---
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

# cum_* / n_*_t: NA -> 0
for (v in grep("^cum_|^n_complainant_t|^n_respondent_t|^n_tp_t",
               names(country_meta), value = TRUE)) {
  country_meta[[v]][is.na(country_meta[[v]])] <- 0
}

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

ergm_panel_dem   <- ergm_panel     %>% filter(!exporter %in% nodes_missing_vdem,
                                               !importer %in% nodes_missing_vdem)
country_meta_dem <- country_meta_dem %>% filter(!iso3c %in% nodes_missing_vdem)
all_nodes_dem    <- sort(unique(c(ergm_panel_dem$exporter, ergm_panel_dem$importer)))
n_nodes_dem      <- length(all_nodes_dem)

cat("Democracy-complete node set:", n_nodes_dem,
    "(dropped", n_nodes - n_nodes_dem, "from full set)\n")
cat("Democracy-complete dyad-years:", nrow(ergm_panel_dem), "\n")

# ---------------------------------------------------------------------------
# Ideal-point-complete node set (Models 2 and 3)
#
# idealpointfp is structurally missing for non-UN members (Taiwan, Kosovo,
# Vatican, some micro-states). Because 0 is a valid substantive value on the
# -2 to +3 ideal-point scale, imputation is not appropriate; drop instead.
#
# V-Dem covers a wider country set than UN ideal points, so the ip-complete
# set is also V-Dem complete in practice. We verify this below and warn if
# any exceptions exist; any such nodes are additionally dropped before Model 3.
# ---------------------------------------------------------------------------

REQUIRED_NODE_VARS_IP <- c("idealpointfp")

country_meta_ip <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(c(REQUIRED_NODE_VARS_IP, REQUIRED_NODE_VARS_DEM),
                        names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_ip <- country_meta_ip %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_IP, names(country_meta_ip))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_ip) > 0) {
  cat("\nIdeal-point-complete: dropping", length(nodes_missing_ip),
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
cat("Ideal-point-complete dyad-years:", nrow(ergm_panel_ip), "\n")

# Verify ip-complete is also V-Dem complete (required for Model 3 v2x_polyarchy)
vdem_still_na <- country_meta_ip %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_DEM, names(country_meta_ip))), is.na)) %>%
  pull(iso3c) %>%
  unique()
if (length(vdem_still_na) > 0) {
  cat("WARNING: ip-complete set still has", length(vdem_still_na),
      "nodes missing V-Dem:", paste(sort(vdem_still_na), collapse = ", "), "\n")
  cat("  Dropping these additionally for Model 3 compatibility.\n")
  nodes_missing_ip <- union(nodes_missing_ip, vdem_still_na)
  ergm_panel_ip    <- ergm_panel %>% filter(!exporter %in% nodes_missing_ip,
                                             !importer %in% nodes_missing_ip)
  country_meta_ip  <- country_meta_ip %>% filter(!iso3c %in% nodes_missing_ip)
  all_nodes_ip     <- sort(unique(c(ergm_panel_ip$exporter, ergm_panel_ip$importer)))
  n_nodes_ip       <- length(all_nodes_ip)
  cat("  Final ip-complete node set:", n_nodes_ip, "\n")
} else {
  cat("V-Dem check: ip-complete set is also V-Dem complete.",
      "Models 2 and 3 share net_list_ip.\n")
}

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

cat("\n=== Building IP-COMPLETE network list (Models 2 & 3) ===\n")
ip <- build_net_list(ergm_panel_ip, country_meta_ip, all_nodes_ip, years)

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
model0 <- btergm(
  net_list_noeun ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_noeun) +
    edgecov(ally_cov_noeun) +
    edgecov(pta_cov_noeun) +
    # edgecov(hhi_cov_noeun) +          # trade concentration across HS sections
    # edgecov(export_conc_cov_noeun) +  # i's max section export share to j
    # edgecov(import_dep_cov_noeun) +   # j's max section export share to i (import leverage)
    nodecov("log_gdppc") +
    nodecov("log_pop") +
    nodeicov("cum_respondent") +
    nodeocov("cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
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
    # edgecov(hhi_cov) +               # trade concentration across HS sections
    # edgecov(export_conc_cov) +       # i's max section export share to j
    # edgecov(import_dep_cov) +        # j's max section export share to i (import leverage)
    nodecov("log_gdppc") +
    nodecov("log_pop") +
    nodeicov("cum_respondent") +
    nodeocov("cum_complainant") +
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
    # edgecov(hhi_cov_ip) +
    # edgecov(export_conc_cov_ip) +
    # edgecov(import_dep_cov_ip) +
    edgecov(ideal_dist_cov_ip) +      # UN voting distance (idealpointfp), no NAs
    nodecov("log_gdppc") +
    nodecov("log_pop") +
    nodeicov("cum_respondent") +
    nodeocov("cum_complainant") +
    delrecip +
    memory(type = "stability"),
  R       = BTERGM_BOOTS,
  parallel = "multicore",
  ncpus   = 4
)
cat("\n--- Model 2 ---\n"); summary(model2)

# --- Model 3: + Democracy (ip-complete node set) ---
# Reuses net_list_ip: ip-complete is also V-Dem complete (verified above),
# so no additional node dropping is needed. n_nodes_ip reported in console.
cat("\n=== Model 3: + Democracy (n =", n_nodes_ip, "nodes) ===\n")
model3 <- btergm(
  net_list_ip ~
    edges +
    mutual +
    gwidegree(decay = 0.5, fixed = TRUE) +
    gwodegree(decay = 0.5, fixed = TRUE) +
    edgecov(trade_cov_ip) +
    edgecov(ally_cov_ip) +
    edgecov(pta_cov_ip) +
    # edgecov(hhi_cov_ip) +
    # edgecov(export_conc_cov_ip) +
    # edgecov(import_dep_cov_ip) +
    edgecov(ideal_dist_cov_ip) +
    nodecov("log_gdppc") +
    nodecov("log_pop") +
    nodeicov("cum_respondent") +
    nodeocov("cum_complainant") +
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
    nodecov("log_gdppc") +
    nodecov("log_pop") +
    nodeicov("cum_respondent") +
    nodeocov("cum_complainant") +
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

screenreg(
  list(model0, model1, model2, model3),
  custom.model.names = c("M0: No-EUN", "M1: Full", "M2: +Align", "M3: +Demo"),
  digits = 3
)

htmlreg(
  list(model0, model1, model2, model3),
  file = "Data/Output/tergm_results.html",
  custom.model.names = c("No-EUN Baseline", "Full + Trade", "+ Alignment", "+ Democracy"),
  digits = 3,
  caption = "TERGM Results: WTO Dispute Initiation (C->R), 1995-2024"
)
cat("Results saved to Data/Output/tergm_results.html\n")

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
    "   Ideal-point-complete (Models 2 & 3):", n_nodes_ip, "countries\n",
    "   Dropped for missing idealpointfp:", paste(sort(nodes_missing_ip), collapse=", "), "\n",
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
