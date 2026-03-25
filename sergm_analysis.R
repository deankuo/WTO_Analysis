###############################################################################
# WTO Dispute SERGM Analysis (Signed Network)
# Author: Peng-Ting Kuo
# Date: March 2026
#
# Builds SIGNED networks for the Fritz et al. (2025) SERGM:
#   Negative edges: C->R (complainant vs respondent)  [strong negative]
#                   TP->R (third party vs respondent)  [weak negative]
#   Positive edges: C<->TP (complainant & third party) [positive alignment]
#   Zero: no dispute relationship that year
#
# Aggregation: negative (-1) wins over positive (+1) when both present.
#
# Models:
#   Model S0 : SERGM-NoEUN — national-state baseline (no EUN)
#   Model S1 : SERGM-Full  — structural balance + trade + node covariates
#   Model S2 : SERGM-Full  — + political alignment (ideal point distance)
#   Model S3 : SERGM-IpDem — + democracy (ip+dem-complete node set; drops nodes
#              missing EITHER idealpointfp OR v2x_polyarchy)
#
# ergm.sign API (Fritz et al. 2025, Political Analysis):
#   Main functions : tsergm() [temporal], sergm() [static]
#   LHS            : list of signed adjacency matrices (0/+1/-1)
#   Edge covariates: cov_dyad(data=M)     — same effect on + and - edges
#                    cov_dyad_pos(data=M) — positive edges only
#                    cov_dyad_neg(data=M) — negative edges only
#   Balance terms  : gwesf_pos/neg(data=matrix(alpha)) — shared friends
#                    gwese_pos/neg(data=matrix(alpha)) — shared enemies
#   Degree terms   : gwdegree_pos/neg(data=matrix(alpha))
#   Node covariates: NOT available — encode as dyadic sum M[i,j]=v[i]+v[j]
#   For tsergm: covariate data arguments should be lists of matrices
#               (one matrix per year, same index order as the network list)
#
# Severity covariate design:
#   severity_cov_s != 0 only on negative edges; conceptually independent
#   from the signed adjacency (sign = relationship type, severity = intensity).
#   C-R  : max dyadic_severity across cases (scale 1-5)
#   TP-R : 0.5 placeholder (no TP instrument yet)
#   C-TP : 0 (support relationships are a different dimension)
#
# Democracy-complete node set (Model S3):
#   Countries structurally missing v2x_polyarchy (micro-states, territories)
#   are dropped; carry-forward fills 1-year data lags first.
#
# Data notes:
#   - EUN node attrs in country_meta (via scripts/impute_eun_meta.py)
#   - Section covariates (trade_hhi, max_export_conc, max_reverse_dep)
#     in ergm_dyad_year_eun.csv (from build_ergm_data.py)
#   - atopally_t1 etc. NOT in dataset
#   - Ideal points: non-UN-member nodes dropped via ip-complete node set
#     (Models S2 & S3); 0 is a valid substantive value, so not imputed
#   - Severity NAs -> 0
#
# Required: ergm.sign (Fritz et al.), dplyr, tidyr
# Install : devtools::install_github("corneliusfritz/ergm.sign")
#         Replication: https://doi.org/10.7910/DVN/7ZRCS6
###############################################################################

# ===========================================================================
# 0. SETUP
# ===========================================================================

library(dplyr)
library(tidyr)

# ergm.sign is required for estimation; data preparation runs without it
ERGM_SIGN_AVAILABLE <- tryCatch({
  library(ergm.sign)
  cat("ergm.sign loaded.\n")
  TRUE
}, error = function(e) {
  cat("ergm.sign not installed. Data preparation will run; estimation skipped.\n")
  cat("Install: devtools::install_github('corneliusfritz/ergm.sign')\n")
  FALSE
})

# ===========================================================================
# 1. READ DATA
# ===========================================================================

wto_dyadic   <- read.csv("Data/wto_dyadic_enriched.csv",    stringsAsFactors = FALSE)
ergm_panel   <- read.csv("Data/ergm_dyad_year_eun.csv",     stringsAsFactors = FALSE)
country_meta <- read.csv("Data/country_meta_1995_2024.csv", stringsAsFactors = FALSE)

if (!"EUN" %in% country_meta$iso3c) {
  stop("EUN not found in country_meta. Run: python scripts/impute_eun_meta.py --write")
}

cat("WTO dyadic rows:", nrow(wto_dyadic), "\n")
cat("Relationships:\n"); print(table(wto_dyadic$relationship))

# ===========================================================================
# 2. CLEAN ERGM_PANEL COVARIATES
# ===========================================================================

# Trade
for (v in c("total_trade_ij", "export_dependence", "trade_dependence")) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# Section covariates (new; built by build_ergm_data.py)
for (v in c("trade_hhi", "max_export_conc", "max_reverse_dep")) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# PTA
if ("label" %in% names(ergm_panel)) {
  ergm_panel$pta_exists <- ifelse(is.na(ergm_panel$label), 0L, as.integer(ergm_panel$label))
}
if ("depth_index" %in% names(ergm_panel)) {
  ergm_panel$depth_index[is.na(ergm_panel$depth_index)] <- 0
}

# ATOP
for (v in c("atopally")) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# Node attributes
if ("election_binary" %in% names(country_meta)) {
  country_meta$election_binary[is.na(country_meta$election_binary)] <- 0
}
node_impute_vars <- c("gdp", "gdppc", "pop", "log_gdppc", "log_pop", "gdp_growth_rate")
country_meta <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(node_impute_vars, names(country_meta))), .direction = "downup") %>%
  ungroup()
for (v in grep("^cum_", names(country_meta), value = TRUE)) {
  country_meta[[v]][is.na(country_meta[[v]])] <- 0
}

# ===========================================================================
# 3. BUILD SIGNED EDGE LIST
# ===========================================================================

# Map: C-R -> -1 (strong), TP-R -> -1 (weak), C-TP -> +1
signed_edges <- wto_dyadic %>%
  filter(!is.na(consultation_year)) %>%
  mutate(
    sign = case_when(
      relationship == "complainant-respondent"  ~ -1L,
      relationship == "third_party-respondent"  ~ -1L,
      relationship == "complainant-third_party" ~ +1L,
      TRUE ~ NA_integer_
    ),
    node_a = pmin(iso3_1, iso3_2),   # alphabetical for undirected SERGM
    node_b = pmax(iso3_1, iso3_2),
    year   = as.integer(consultation_year)
  ) %>%
  filter(!is.na(sign)) %>%
  select(year, node_a, node_b, sign, relationship, case_id = case)

cat("\nSigned edges by type:\n")
print(table(signed_edges$sign, signed_edges$relationship))

# Aggregate: negative wins
signed_agg <- signed_edges %>%
  group_by(year, node_a, node_b) %>%
  summarise(
    sign    = ifelse(any(sign == -1L), -1L, +1L),
    n_cases = n(),
    has_cr  = any(relationship == "complainant-respondent"),
    has_tpr = any(relationship == "third_party-respondent"),
    has_ctp = any(relationship == "complainant-third_party"),
    .groups = "drop"
  )

cat("\nAggregated signed edges per year:\n")
signed_agg %>%
  group_by(year) %>%
  summarise(n_pos = sum(sign == 1), n_neg = sum(sign == -1), total = n(), .groups = "drop") %>%
  print(n = 35)

# ---------------------------------------------------------------------------
# Severity aggregation (negative edges only: C-R and TP-R)
#
# Design: severity_cov_s is SEPARATE from signed adjacency.
#   C-R  : max dyadic_severity (scale 1-5)
#   TP-R : 0.5 placeholder
#   C-TP : 0   (excluded from filter below)
# ---------------------------------------------------------------------------
severity_agg <- wto_dyadic %>%
  filter(!is.na(consultation_year),
         relationship %in% c("complainant-respondent", "third_party-respondent")) %>%
  mutate(
    node_a = pmin(iso3_1, iso3_2),
    node_b = pmax(iso3_1, iso3_2),
    year   = as.integer(consultation_year),
    sev    = ifelse(is.na(dyadic_severity), 0, dyadic_severity)
  ) %>%
  group_by(year, node_a, node_b) %>%
  summarise(severity = max(sev, na.rm = TRUE), .groups = "drop")

cat("\nSeverity aggregation rows:", nrow(severity_agg), "\n")
cat("Severity range:", range(severity_agg$severity), "\n")

# ===========================================================================
# 4. DEFINE NODE SETS
# ===========================================================================

YEAR_START <- 1995
YEAR_END   <- 2024
years      <- YEAR_START:YEAR_END

EXCLUDED   <- c("MAC", "HKG", "SOM", "PRK")

# Filter edge list, panel, and meta
signed_agg_clean <- signed_agg %>%
  filter(year >= YEAR_START, year <= YEAR_END,
         !node_a %in% EXCLUDED, !node_b %in% EXCLUDED)
ergm_panel <- ergm_panel %>%
  filter(year >= YEAR_START, year <= YEAR_END,
         !exporter %in% EXCLUDED, !importer %in% EXCLUDED)
country_meta <- country_meta %>% filter(!iso3c %in% EXCLUDED)
severity_agg_clean <- severity_agg %>%
  filter(year >= YEAR_START, year <= YEAR_END,
         !node_a %in% EXCLUDED, !node_b %in% EXCLUDED)

# Full node set (from signed edges)
all_nodes <- sort(unique(c(signed_agg_clean$node_a, signed_agg_clean$node_b)))
n_nodes   <- length(all_nodes)

# No-EUN node set
signed_agg_noeun   <- signed_agg_clean %>% filter(node_a != "EUN", node_b != "EUN")
ergm_panel_noeun   <- ergm_panel %>% filter(exporter != "EUN", importer != "EUN")
country_meta_noeun <- country_meta %>% filter(iso3c != "EUN")
severity_agg_noeun <- severity_agg_clean %>% filter(node_a != "EUN", node_b != "EUN")
all_nodes_noeun    <- sort(unique(c(signed_agg_noeun$node_a, signed_agg_noeun$node_b)))
n_nodes_noeun      <- length(all_nodes_noeun)

# ---------------------------------------------------------------------------
# Democracy-complete node set (diagnostic only)
# NOTE: Superseded by the ip-complete section below.
#   Both Models S2 and S3 now use ip-complete (which is also V-Dem complete).
#   This block is retained for diagnostics (n_nodes_dem_s, nodes_missing_vdem_s).
# ---------------------------------------------------------------------------
REQUIRED_NODE_VARS_DEM <- c("v2x_polyarchy")

country_meta_dem_s <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(REQUIRED_NODE_VARS_DEM, names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_vdem_s <- country_meta_dem_s %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_DEM, names(country_meta_dem_s))),
                is.na)) %>%
  pull(iso3c) %>% unique()

if (length(nodes_missing_vdem_s) > 0) {
  cat("\nDemocracy-complete (SERGM): dropping", length(nodes_missing_vdem_s),
      "nodes missing v2x_polyarchy:\n ",
      paste(sort(nodes_missing_vdem_s), collapse = ", "), "\n")
} else {
  cat("\nDemocracy-complete (SERGM): v2x_polyarchy complete for all nodes.\n")
}

signed_agg_dem_s   <- signed_agg_clean %>%
  filter(!node_a %in% nodes_missing_vdem_s, !node_b %in% nodes_missing_vdem_s)
ergm_panel_dem_s   <- ergm_panel %>%
  filter(!exporter %in% nodes_missing_vdem_s, !importer %in% nodes_missing_vdem_s)
country_meta_dem_s <- country_meta_dem_s %>%
  filter(!iso3c %in% nodes_missing_vdem_s)
severity_agg_dem_s <- severity_agg_clean %>%
  filter(!node_a %in% nodes_missing_vdem_s, !node_b %in% nodes_missing_vdem_s)
all_nodes_dem_s    <- sort(unique(c(signed_agg_dem_s$node_a, signed_agg_dem_s$node_b)))
n_nodes_dem_s      <- length(all_nodes_dem_s)

cat("\nFull node set:", n_nodes,
    "| No-EUN:", n_nodes_noeun,
    "| Democracy-complete:", n_nodes_dem_s, "\n")

# ---------------------------------------------------------------------------
# Ideal-point-complete node set (Model S2)
#
# Same rationale as TERGM: idealpointfp is structurally missing for non-UN
# members (Taiwan, Kosovo, micro-states). 0 is a valid value on the scale;
# we drop instead of imputing. Model S2 only needs ideal-point completeness.
# ---------------------------------------------------------------------------

REQUIRED_NODE_VARS_IP <- c("idealpointfp")

country_meta_ip_s <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(REQUIRED_NODE_VARS_IP, names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_ip_s <- country_meta_ip_s %>%
  filter(if_any(all_of(intersect(REQUIRED_NODE_VARS_IP, names(country_meta_ip_s))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_ip_s) > 0) {
  cat("\nIdeal-point-complete (Model S2): dropping", length(nodes_missing_ip_s),
      "nodes missing idealpointfp:\n ",
      paste(sort(nodes_missing_ip_s), collapse = ", "), "\n")
} else {
  cat("\nIdeal-point-complete (SERGM): no nodes dropped (idealpointfp complete).\n")
}

signed_agg_ip_s    <- signed_agg_clean %>%
  filter(!node_a %in% nodes_missing_ip_s, !node_b %in% nodes_missing_ip_s)
ergm_panel_ip_s    <- ergm_panel %>%
  filter(!exporter %in% nodes_missing_ip_s, !importer %in% nodes_missing_ip_s)
country_meta_ip_s  <- country_meta_ip_s %>% filter(!iso3c %in% nodes_missing_ip_s)
severity_agg_ip_s  <- severity_agg_clean %>%
  filter(!node_a %in% nodes_missing_ip_s, !node_b %in% nodes_missing_ip_s)
all_nodes_ip_s     <- sort(unique(c(signed_agg_ip_s$node_a, signed_agg_ip_s$node_b)))
n_nodes_ip_s       <- length(all_nodes_ip_s)

cat("Ideal-point-complete node set (SERGM):", n_nodes_ip_s,
    "(dropped", n_nodes - n_nodes_ip_s, "from full set)\n")

# ---------------------------------------------------------------------------
# Ip+Dem-complete node set (Model S3)
#
# Model S3 requires both idealpointfp and v2x_polyarchy.
# Some UN members have ideal points but no V-Dem (small island states).
# These appear in signed_net_list_ip_s (S2) but must be dropped for S3.
# ---------------------------------------------------------------------------

country_meta_ip_dem_s <- country_meta %>%
  group_by(iso3c) %>%
  arrange(year) %>%
  fill(all_of(intersect(c(REQUIRED_NODE_VARS_IP, REQUIRED_NODE_VARS_DEM),
                        names(country_meta))),
       .direction = "downup") %>%
  ungroup()

nodes_missing_ip_dem_s <- country_meta_ip_dem_s %>%
  filter(if_any(all_of(intersect(c(REQUIRED_NODE_VARS_IP, REQUIRED_NODE_VARS_DEM),
                                 names(country_meta_ip_dem_s))), is.na)) %>%
  pull(iso3c) %>%
  unique()

if (length(nodes_missing_ip_dem_s) > 0) {
  cat("\nIp+Dem-complete (Model S3): dropping", length(nodes_missing_ip_dem_s),
      "nodes missing idealpointfp or v2x_polyarchy:\n ",
      paste(sort(nodes_missing_ip_dem_s), collapse = ", "), "\n")
} else {
  cat("\nIp+Dem-complete (SERGM): no nodes dropped.\n")
}

signed_agg_ip_dem_s    <- signed_agg_clean %>%
  filter(!node_a %in% nodes_missing_ip_dem_s, !node_b %in% nodes_missing_ip_dem_s)
ergm_panel_ip_dem_s    <- ergm_panel %>%
  filter(!exporter %in% nodes_missing_ip_dem_s, !importer %in% nodes_missing_ip_dem_s)
country_meta_ip_dem_s  <- country_meta_ip_dem_s %>%
  filter(!iso3c %in% nodes_missing_ip_dem_s)
severity_agg_ip_dem_s  <- severity_agg_clean %>%
  filter(!node_a %in% nodes_missing_ip_dem_s, !node_b %in% nodes_missing_ip_dem_s)
all_nodes_ip_dem_s     <- sort(unique(c(signed_agg_ip_dem_s$node_a,
                                        signed_agg_ip_dem_s$node_b)))
n_nodes_ip_dem_s       <- length(all_nodes_ip_dem_s)

cat("Ip+Dem-complete node set (SERGM):", n_nodes_ip_dem_s,
    "(dropped", n_nodes - n_nodes_ip_dem_s, "from full set)\n")
cat("Nodes in S2 but not S3 (have idealpoint, lack V-Dem):",
    length(setdiff(all_nodes_ip_s, all_nodes_ip_dem_s)), ":",
    paste(sort(setdiff(all_nodes_ip_s, all_nodes_ip_dem_s)), collapse = ", "), "\n")

# ===========================================================================
# 5. SIGNED NETWORK BUILDER
# ===========================================================================

#' build_signed_nets
#'
#' @param edges_agg    Aggregated signed edge list (node_a, node_b, year, sign)
#' @param panel        Dyadic panel for edge covariates (ergm_dyad_year_eun.csv)
#' @param meta         Country-year panel for node attributes
#' @param nodes        Sorted character vector of node labels
#' @param severity_agg Severity data (year, node_a, node_b, severity);
#'                     C-R: 1-5; TP-R: 0.5; C-TP excluded (stays 0)
#' @return Named list of covariate lists (each a named list of matrices, one
#'         per year in chronological order — ready for tsergm() data args)

build_signed_nets <- function(edges_agg, panel, meta, nodes, severity_agg = NULL) {
  n <- length(nodes)

  # Covariate lists (each will hold one matrix per year)
  signed_net_list   <- list()
  trade_cov_s       <- list()
  ally_cov_s        <- list()
  pta_cov_s         <- list()
  ideal_dist_cov_s  <- list()
  hhi_cov_s         <- list()
  export_conc_cov_s <- list()
  import_dep_cov_s  <- list()
  severity_cov_s    <- list()
  # Node-level covariates encoded as dyadic sum matrices M[i,j] = v[i] + v[j]
  # (ergm.sign has no nodecov term; sum is equivalent to undirected nodecov)
  gdp_cov_s         <- list()
  pop_cov_s         <- list()
  activity_cov_s    <- list()   # cum_complainant + cum_respondent
  vdem_cov_s        <- list()   # v2x_polyarchy (NA -> 0 if not dem-complete set)
  # Absolute difference matrices M[i,j] = |v[i] - v[j]|
  # (analogous to absdiff() in btergm; captures economic/size gap between dyad)
  gdp_diff_cov_s    <- list()
  pop_diff_cov_s    <- list()
  node_attr_list    <- list()

  for (yr in years) {
    cat("\rBuilding signed network for year", yr, "...")

    # ---- Signed adjacency (+1 / -1 / 0) ----
    adj <- matrix(0L, n, n, dimnames = list(nodes, nodes))
    edges_yr <- edges_agg %>% filter(year == yr)
    for (r in seq_len(nrow(edges_yr))) {
      a <- edges_yr$node_a[r]; b <- edges_yr$node_b[r]
      if (a %in% nodes && b %in% nodes) {
        adj[a, b] <- edges_yr$sign[r]
        adj[b, a] <- edges_yr$sign[r]   # undirected (symmetric)
      }
    }

    # ---- Dyadic edge covariates ----
    df_yr <- panel %>% filter(year == yr)
    mk <- function() matrix(0, n, n, dimnames = list(nodes, nodes))
    trade_m    <- mk(); ally_m     <- mk(); pta_m     <- mk()
    hhi_m      <- mk(); exp_conc_m <- mk(); imp_dep_m <- mk()

    for (r in seq_len(nrow(df_yr))) {
      i <- df_yr$exporter[r]; j <- df_yr$importer[r]
      if (!(i %in% nodes && j %in% nodes)) next
      # Symmetrised (undirected SERGM; take max over both directions)
      trade_m[i,j] <- trade_m[j,i] <- max(trade_m[i,j], df_yr$total_trade_ij[r])
      ally_m[i,j]  <- ally_m[j,i]  <- max(ally_m[i,j],  df_yr$atopally[r])
      pta_m[i,j]   <- pta_m[j,i]   <- max(pta_m[i,j],   df_yr$pta_exists[r])
      if ("trade_hhi"       %in% names(df_yr))
        hhi_m[i,j]      <- hhi_m[j,i]      <- max(hhi_m[i,j],      df_yr$trade_hhi[r])
      if ("max_export_conc" %in% names(df_yr))
        exp_conc_m[i,j] <- exp_conc_m[j,i] <- max(exp_conc_m[i,j], df_yr$max_export_conc[r])
      if ("max_reverse_dep" %in% names(df_yr))
        imp_dep_m[i,j]  <- imp_dep_m[j,i]  <- max(imp_dep_m[i,j],  df_yr$max_reverse_dep[r])
    }

    # ---- Severity matrix ----
    # Non-zero only on negative edges; symmetric
    sev_m <- mk()
    if (!is.null(severity_agg)) {
      sev_yr <- severity_agg %>% filter(year == yr)
      for (r in seq_len(nrow(sev_yr))) {
        a <- sev_yr$node_a[r]; b <- sev_yr$node_b[r]
        if (a %in% nodes && b %in% nodes)
          sev_m[a, b] <- sev_m[b, a] <- sev_yr$severity[r]
      }
    }

    # ---- Node attributes ----
    meta_yr <- meta %>% filter(year == yr) %>% distinct(iso3c, .keep_all = TRUE)
    node_df  <- data.frame(iso3c = nodes, stringsAsFactors = FALSE) %>%
      left_join(meta_yr %>% select(iso3c,
        any_of(c("log_gdppc", "log_pop", "wto_member",
                 "v2x_polyarchy", "idealpointfp",
                 "cum_complainant", "cum_respondent",
                 "election_binary", "reg_quality"))),
        by = "iso3c")

    # ---- Ideal point distance (|ip_i - ip_j|) ----
    # For ip-complete datasets (Models S2 & S3) there are no NAs here;
    # the NA->0 below is a safety guard only (no-op for ip-complete sets).
    ip_vec  <- if ("idealpointfp" %in% names(node_df)) node_df$idealpointfp
               else rep(NA_real_, n)
    ideal_m <- outer(ip_vec, ip_vec, function(a, b) abs(a - b))
    ideal_m[is.na(ideal_m)] <- 0   # safety guard (no-op for ip-complete datasets)
    rownames(ideal_m) <- colnames(ideal_m) <- nodes

    # ---- Node-level -> dyadic sum matrices ----
    # M[i,j] = v[i] + v[j]  (analogous to undirected nodecov in ergm)
    # NA values set to 0 before summing (conservative: unknown = baseline)
    safe_sum_mat <- function(v) {
      v[is.na(v)] <- 0
      m <- outer(v, rep(1, n)) + outer(rep(1, n), v)
      rownames(m) <- colnames(m) <- nodes
      diag(m) <- 0
      m
    }
    # M[i,j] = |v[i] - v[j]|  (analogous to absdiff() in btergm)
    safe_diff_mat <- function(v) {
      v[is.na(v)] <- 0
      m <- outer(v, v, function(a, b) abs(a - b))
      rownames(m) <- colnames(m) <- nodes
      diag(m) <- 0
      m
    }

    gdp_vec      <- if ("log_gdppc" %in% names(node_df)) node_df$log_gdppc
                    else rep(0, n)
    pop_vec      <- if ("log_pop" %in% names(node_df)) node_df$log_pop
                    else rep(0, n)
    cc_vec       <- if ("cum_complainant" %in% names(node_df)) node_df$cum_complainant
                    else rep(0, n)
    cr_vec       <- if ("cum_respondent" %in% names(node_df)) node_df$cum_respondent
                    else rep(0, n)
    vdem_vec     <- if ("v2x_polyarchy" %in% names(node_df)) node_df$v2x_polyarchy
                    else rep(NA_real_, n)

    act_vec <- ifelse(is.na(cc_vec), 0, cc_vec) + ifelse(is.na(cr_vec), 0, cr_vec)

    yr_key <- as.character(yr)
    signed_net_list[[yr_key]]    <- adj
    trade_cov_s[[yr_key]]        <- log(trade_m + 1)
    ally_cov_s[[yr_key]]         <- ally_m
    pta_cov_s[[yr_key]]          <- pta_m
    ideal_dist_cov_s[[yr_key]]   <- ideal_m
    hhi_cov_s[[yr_key]]          <- hhi_m
    export_conc_cov_s[[yr_key]]  <- exp_conc_m
    import_dep_cov_s[[yr_key]]   <- imp_dep_m
    severity_cov_s[[yr_key]]     <- sev_m
    gdp_cov_s[[yr_key]]          <- safe_sum_mat(gdp_vec)
    pop_cov_s[[yr_key]]          <- safe_sum_mat(pop_vec)
    activity_cov_s[[yr_key]]     <- safe_sum_mat(act_vec)
    vdem_cov_s[[yr_key]]         <- safe_sum_mat(vdem_vec)
    gdp_diff_cov_s[[yr_key]]     <- safe_diff_mat(gdp_vec)
    pop_diff_cov_s[[yr_key]]     <- safe_diff_mat(pop_vec)
    node_attr_list[[yr_key]]     <- node_df
  }
  cat("\n")

  list(signed_net_list   = signed_net_list,
       trade_cov_s       = trade_cov_s,
       ally_cov_s        = ally_cov_s,
       pta_cov_s         = pta_cov_s,
       ideal_dist_cov_s  = ideal_dist_cov_s,
       hhi_cov_s         = hhi_cov_s,
       export_conc_cov_s = export_conc_cov_s,
       import_dep_cov_s  = import_dep_cov_s,
       severity_cov_s    = severity_cov_s,
       gdp_cov_s         = gdp_cov_s,
       pop_cov_s         = pop_cov_s,
       activity_cov_s    = activity_cov_s,
       vdem_cov_s        = vdem_cov_s,
       gdp_diff_cov_s    = gdp_diff_cov_s,
       pop_diff_cov_s    = pop_diff_cov_s,
       node_attr_list    = node_attr_list)
}

# ===========================================================================
# 6. BUILD NETWORK LISTS
# ===========================================================================

cat("\n=== Building FULL signed network list (incl. EUN) ===\n")
full_s <- build_signed_nets(signed_agg_clean, ergm_panel, country_meta,
                            all_nodes, severity_agg_clean)

cat("\n=== Building NO-EUN signed network list ===\n")
noeun_s <- build_signed_nets(signed_agg_noeun, ergm_panel_noeun,
                             country_meta_noeun, all_nodes_noeun,
                             severity_agg_noeun)

cat("\n=== Building IP-COMPLETE signed network list (Model S2) ===\n")
ip_s <- build_signed_nets(signed_agg_ip_s, ergm_panel_ip_s,
                          country_meta_ip_s, all_nodes_ip_s,
                          severity_agg_ip_s)

cat("\n=== Building IP+DEM-COMPLETE signed network list (Model S3) ===\n")
ip_dem_s <- build_signed_nets(signed_agg_ip_dem_s, ergm_panel_ip_dem_s,
                              country_meta_ip_dem_s, all_nodes_ip_dem_s,
                              severity_agg_ip_dem_s)

# Unpack full
signed_net_list    <- full_s$signed_net_list
trade_cov_s        <- full_s$trade_cov_s
ally_cov_s         <- full_s$ally_cov_s
pta_cov_s          <- full_s$pta_cov_s
ideal_dist_cov_s   <- full_s$ideal_dist_cov_s
hhi_cov_s          <- full_s$hhi_cov_s
export_conc_cov_s  <- full_s$export_conc_cov_s
import_dep_cov_s   <- full_s$import_dep_cov_s
severity_cov_s     <- full_s$severity_cov_s
gdp_cov_s          <- full_s$gdp_cov_s
pop_cov_s          <- full_s$pop_cov_s
activity_cov_s     <- full_s$activity_cov_s
vdem_cov_s         <- full_s$vdem_cov_s
gdp_diff_cov_s     <- full_s$gdp_diff_cov_s
pop_diff_cov_s     <- full_s$pop_diff_cov_s

# Unpack no-EUN
signed_net_list_noeun    <- noeun_s$signed_net_list
trade_cov_s_noeun        <- noeun_s$trade_cov_s
ally_cov_s_noeun         <- noeun_s$ally_cov_s
pta_cov_s_noeun          <- noeun_s$pta_cov_s
ideal_dist_cov_s_noeun   <- noeun_s$ideal_dist_cov_s
hhi_cov_s_noeun          <- noeun_s$hhi_cov_s
export_conc_cov_s_noeun  <- noeun_s$export_conc_cov_s
import_dep_cov_s_noeun   <- noeun_s$import_dep_cov_s
severity_cov_s_noeun     <- noeun_s$severity_cov_s
gdp_cov_s_noeun          <- noeun_s$gdp_cov_s
pop_cov_s_noeun          <- noeun_s$pop_cov_s
activity_cov_s_noeun     <- noeun_s$activity_cov_s
gdp_diff_cov_s_noeun     <- noeun_s$gdp_diff_cov_s
pop_diff_cov_s_noeun     <- noeun_s$pop_diff_cov_s

# Unpack ip-complete (Model S2)
signed_net_list_ip_s    <- ip_s$signed_net_list
trade_cov_s_ip_s        <- ip_s$trade_cov_s
ally_cov_s_ip_s         <- ip_s$ally_cov_s
pta_cov_s_ip_s          <- ip_s$pta_cov_s
ideal_dist_cov_s_ip_s   <- ip_s$ideal_dist_cov_s
hhi_cov_s_ip_s          <- ip_s$hhi_cov_s
export_conc_cov_s_ip_s  <- ip_s$export_conc_cov_s
import_dep_cov_s_ip_s   <- ip_s$import_dep_cov_s
severity_cov_s_ip_s     <- ip_s$severity_cov_s
gdp_cov_s_ip_s          <- ip_s$gdp_cov_s
pop_cov_s_ip_s          <- ip_s$pop_cov_s
activity_cov_s_ip_s     <- ip_s$activity_cov_s
vdem_cov_s_ip_s         <- ip_s$vdem_cov_s
gdp_diff_cov_s_ip_s     <- ip_s$gdp_diff_cov_s
pop_diff_cov_s_ip_s     <- ip_s$pop_diff_cov_s

# Unpack ip+dem-complete (Model S3)
signed_net_list_ip_dem_s   <- ip_dem_s$signed_net_list
trade_cov_s_ip_dem_s       <- ip_dem_s$trade_cov_s
ally_cov_s_ip_dem_s        <- ip_dem_s$ally_cov_s
pta_cov_s_ip_dem_s         <- ip_dem_s$pta_cov_s
ideal_dist_cov_s_ip_dem_s  <- ip_dem_s$ideal_dist_cov_s
hhi_cov_s_ip_dem_s         <- ip_dem_s$hhi_cov_s
export_conc_cov_s_ip_dem_s <- ip_dem_s$export_conc_cov_s
import_dep_cov_s_ip_dem_s  <- ip_dem_s$import_dep_cov_s
severity_cov_s_ip_dem_s    <- ip_dem_s$severity_cov_s
gdp_cov_s_ip_dem_s         <- ip_dem_s$gdp_cov_s
pop_cov_s_ip_dem_s         <- ip_dem_s$pop_cov_s
activity_cov_s_ip_dem_s    <- ip_dem_s$activity_cov_s
vdem_cov_s_ip_dem_s        <- ip_dem_s$vdem_cov_s
gdp_diff_cov_s_ip_dem_s    <- ip_dem_s$gdp_diff_cov_s
pop_diff_cov_s_ip_dem_s    <- ip_dem_s$pop_diff_cov_s

# Diagnostics
cat("\n--- Signed network diagnostics ---\n")
for (yr in c("1995","2000","2005","2010","2015","2020","2024")) {
  if (yr %in% names(signed_net_list)) {
    mat   <- signed_net_list[[yr]]
    upper <- mat[upper.tri(mat)]
    cat(yr, ": pos =", sum(upper == 1L),
        "| neg =", sum(upper == -1L),
        "| total =", sum(upper != 0L), "\n")
  }
}

# ===========================================================================
# 7. TSERGM ESTIMATION  (requires ergm.sign)
# ===========================================================================
#
# tsergm() models the joint likelihood across all years:
#   P(Y_1, ..., Y_T) = prod_t P(Y_t | theta)
# Covariates passed as lists of matrices are automatically matched to the
# corresponding year's network (by list index order, same as signed_net_list).
#
# Estimation:
#   method_est = "MPLE"   — pseudo-likelihood + parametric bootstrap SE
#                            (fast; recommended for initial run & specification search)
#   method_est = "RM"     — Robbins-Monroe MCMCMLE (more accurate; slower)
#   method_est = "MLE"    — standard MCMCMLE (most accurate; use for final results)
#
# Balance term alpha (decay parameter, fixed):
#   alpha = 0.5 is a common default; profile the log-likelihood over
#   alpha in {0.25, 0.5, 1.0, 2.0} and pick the maximising value if needed.
#
# Theoretical predictions (structural balance):
#   gwesf_pos > 0  : friends-of-friends-are-friends (balance)
#   gwese_pos > 0  : enemies-of-enemies-are-friends (balance)
#   gwesf_neg < 0  : friends-of-friends-are-enemies (imbalanced; may be + in WTO
#                    if alliance networks create shared conflict clusters)
#   gwese_neg < 0  : enemies-of-enemies-are-enemies (imbalanced)
#   ally/pta on -  : allies use WTO as costly signal (expected +)
#   ally/pta on +  : allies join as co-TPs (expected +)
#   severity on -  : aggressive disputes attract more TPs / escalate (expected +)
#   ideal_dist on -: political distance -> more disputes (expected +)
#   gdp on both    : richer dyads more WTO-active (expected +)
# ===========================================================================

if (ERGM_SIGN_AVAILABLE) {

  # Default control: MPLE for speed; switch to "RM" or "MLE" for final results
  SERGM_CONTROL <- control.sergm(method_est = "MPLE")
  ALPHA         <- 0.5   # GW decay parameter (fixed)

  # ---- Model S0: No-EUN baseline ----
  cat("\n=== Model S0: No-EUN Baseline (n =", n_nodes_noeun, "nodes) ===\n")
  sergm_s0 <- tsergm(
    signed_net_list_noeun ~
      edges_pos +
      edges_neg +
      gwdegree_pos(data = matrix(ALPHA)) +    # degree dist: positive edges
      gwdegree_neg(data = matrix(ALPHA)) +    # degree dist: negative edges
      gwesf_pos(data = matrix(ALPHA)) +       # friends-of-friends -> friend (balance)
      gwese_pos(data = matrix(ALPHA)) +       # enemies-of-enemies -> friend (balance)
      cov_dyad(data = trade_cov_s_noeun) +
      cov_dyad_pos(data = ally_cov_s_noeun) +  # alliance -> C-TP alignment
      cov_dyad_neg(data = ally_cov_s_noeun) +  # alliance -> C-R dispute (costly signal)
      cov_dyad_pos(data = pta_cov_s_noeun) +
      cov_dyad_neg(data = pta_cov_s_noeun) +
      cov_dyad_neg(data = severity_cov_s_noeun) +  # conflict intensity -> negative only
      cov_dyad(data = gdp_cov_s_noeun) +
      cov_dyad(data = pop_cov_s_noeun) +
      cov_dyad(data = gdp_diff_cov_s_noeun) +     # |log_gdppc_i - log_gdppc_j| (economic gap)
      cov_dyad(data = pop_diff_cov_s_noeun) +     # |log_pop_i - log_pop_j| (size gap)
      cov_dyad(data = activity_cov_s_noeun),
    control = SERGM_CONTROL
  )
  cat("\n--- Model S0 (No-EUN) ---\n"); print(sergm_s0)

  # ---- Model S1: Full (incl. EUN) — structural + trade + section covs ----
  cat("\n=== Model S1: Full (incl. EUN), n =", n_nodes, "nodes ===\n")
  sergm_s1 <- tsergm(
    signed_net_list ~
      edges_pos +
      edges_neg +
      gwdegree_pos(data = matrix(ALPHA)) +
      gwdegree_neg(data = matrix(ALPHA)) +
      gwesf_pos(data = matrix(ALPHA)) +
      gwese_pos(data = matrix(ALPHA)) +
      cov_dyad(data = trade_cov_s) +
      cov_dyad_pos(data = ally_cov_s) +
      cov_dyad_neg(data = ally_cov_s) +
      cov_dyad_pos(data = pta_cov_s) +
      cov_dyad_neg(data = pta_cov_s) +
      cov_dyad_neg(data = hhi_cov_s) +         # trade concentration -> disputes
      cov_dyad_neg(data = export_conc_cov_s) + # export dependence -> disputes
      cov_dyad_neg(data = import_dep_cov_s) +  # import leverage -> disputes
      cov_dyad_neg(data = severity_cov_s) +
      cov_dyad(data = gdp_cov_s) +
      cov_dyad(data = pop_cov_s) +
      cov_dyad(data = gdp_diff_cov_s) +           # |log_gdppc_i - log_gdppc_j|
      cov_dyad(data = pop_diff_cov_s) +           # |log_pop_i - log_pop_j|
      cov_dyad(data = activity_cov_s),
    control = SERGM_CONTROL
  )
  cat("\n--- Model S1 ---\n"); print(sergm_s1)

  # ---- Model S2: + Political alignment (ip-complete node set) ----
  # Uses ip-complete: non-UN-member nodes (Taiwan etc.) dropped.
  cat("\n=== Model S2: + Political Alignment (ip-complete, n =", n_nodes_ip_s, "nodes) ===\n")
  sergm_s2 <- tsergm(
    signed_net_list_ip_s ~
      edges_pos +
      edges_neg +
      gwdegree_pos(data = matrix(ALPHA)) +
      gwdegree_neg(data = matrix(ALPHA)) +
      gwesf_pos(data = matrix(ALPHA)) +
      gwese_pos(data = matrix(ALPHA)) +
      cov_dyad(data = trade_cov_s_ip_s) +
      cov_dyad_pos(data = ally_cov_s_ip_s) +
      cov_dyad_neg(data = ally_cov_s_ip_s) +
      cov_dyad_pos(data = pta_cov_s_ip_s) +
      cov_dyad_neg(data = pta_cov_s_ip_s) +
      cov_dyad_neg(data = hhi_cov_s_ip_s) +
      cov_dyad_neg(data = export_conc_cov_s_ip_s) +
      cov_dyad_neg(data = import_dep_cov_s_ip_s) +
      cov_dyad_neg(data = severity_cov_s_ip_s) +
      cov_dyad_neg(data = ideal_dist_cov_s_ip_s) +  # political distance -> disputes
      cov_dyad(data = gdp_cov_s_ip_s) +
      cov_dyad(data = pop_cov_s_ip_s) +
      cov_dyad(data = gdp_diff_cov_s_ip_s) +        # |log_gdppc_i - log_gdppc_j|
      cov_dyad(data = pop_diff_cov_s_ip_s) +        # |log_pop_i - log_pop_j|
      cov_dyad(data = activity_cov_s_ip_s),
    control = SERGM_CONTROL
  )
  cat("\n--- Model S2 ---\n"); print(sergm_s2)

  # ---- Model S3: + Democracy (ip+dem-complete node set) ----
  # Separate from S2: drops nodes missing EITHER idealpointfp OR v2x_polyarchy.
  # vdem_cov_s_ip_dem_s = sum of v2x_polyarchy for dyad (M[i,j] = vdem[i]+vdem[j]).
  cat("\n=== Model S3: + Democracy (ip+dem-complete, n =", n_nodes_ip_dem_s, "nodes) ===\n")
  sergm_s3 <- tsergm(
    signed_net_list_ip_dem_s ~
      edges_pos +
      edges_neg +
      gwdegree_pos(data = matrix(ALPHA)) +
      gwdegree_neg(data = matrix(ALPHA)) +
      gwesf_pos(data = matrix(ALPHA)) +
      gwese_pos(data = matrix(ALPHA)) +
      cov_dyad(data = trade_cov_s_ip_dem_s) +
      cov_dyad_pos(data = ally_cov_s_ip_dem_s) +
      cov_dyad_neg(data = ally_cov_s_ip_dem_s) +
      cov_dyad_pos(data = pta_cov_s_ip_dem_s) +
      cov_dyad_neg(data = pta_cov_s_ip_dem_s) +
      cov_dyad_neg(data = hhi_cov_s_ip_dem_s) +
      cov_dyad_neg(data = export_conc_cov_s_ip_dem_s) +
      cov_dyad_neg(data = import_dep_cov_s_ip_dem_s) +
      cov_dyad_neg(data = severity_cov_s_ip_dem_s) +
      cov_dyad_neg(data = ideal_dist_cov_s_ip_dem_s) +
      cov_dyad(data = gdp_cov_s_ip_dem_s) +
      cov_dyad(data = pop_cov_s_ip_dem_s) +
      cov_dyad(data = gdp_diff_cov_s_ip_dem_s) +    # |log_gdppc_i - log_gdppc_j|
      cov_dyad(data = pop_diff_cov_s_ip_dem_s) +    # |log_pop_i - log_pop_j|
      cov_dyad(data = activity_cov_s_ip_dem_s) +
      cov_dyad(data = vdem_cov_s_ip_dem_s),    # democracy dyadic sum (no NAs)
    control = SERGM_CONTROL
  )
  cat("\n--- Model S3 ---\n"); print(sergm_s3)

  # GOF (Model S2 — main specification)
  cat("\n=== Goodness-of-fit (Model S2) ===\n")
  gof_s2 <- gof_sign(sergm_s2)
  pdf("Data/Output/sergm_gof.pdf", width = 10, height = 8)
  plot(gof_s2)
  dev.off()
  cat("GOF plot saved to Data/Output/sergm_gof.pdf\n")

  # Save model objects
  save(sergm_s0, sergm_s1, sergm_s2, sergm_s3,
       file = "Data/Output/sergm_models.RData")
  cat("Model objects saved to Data/Output/sergm_models.RData\n")

} else {
  cat("\nSERGM estimation skipped: ergm.sign not loaded.\n")
  cat("Install: devtools::install_github('corneliusfritz/ergm.sign')\n")
}

# ===========================================================================
# 8. SAVE PREPARED DATA
# ===========================================================================

save(
  # Full
  signed_net_list,
  trade_cov_s, ally_cov_s, pta_cov_s, ideal_dist_cov_s,
  hhi_cov_s, export_conc_cov_s, import_dep_cov_s, severity_cov_s,
  gdp_cov_s, pop_cov_s, gdp_diff_cov_s, pop_diff_cov_s,
  activity_cov_s, vdem_cov_s,
  all_nodes, n_nodes,
  # No-EUN
  signed_net_list_noeun,
  trade_cov_s_noeun, ally_cov_s_noeun, pta_cov_s_noeun, ideal_dist_cov_s_noeun,
  hhi_cov_s_noeun, export_conc_cov_s_noeun, import_dep_cov_s_noeun,
  severity_cov_s_noeun, gdp_cov_s_noeun, pop_cov_s_noeun,
  gdp_diff_cov_s_noeun, pop_diff_cov_s_noeun, activity_cov_s_noeun,
  all_nodes_noeun, n_nodes_noeun,
  # Ip-complete (Model S2)
  signed_net_list_ip_s,
  trade_cov_s_ip_s, ally_cov_s_ip_s, pta_cov_s_ip_s, ideal_dist_cov_s_ip_s,
  hhi_cov_s_ip_s, export_conc_cov_s_ip_s, import_dep_cov_s_ip_s,
  severity_cov_s_ip_s, gdp_cov_s_ip_s, pop_cov_s_ip_s,
  gdp_diff_cov_s_ip_s, pop_diff_cov_s_ip_s, activity_cov_s_ip_s,
  vdem_cov_s_ip_s,
  all_nodes_ip_s, n_nodes_ip_s, nodes_missing_ip_s,
  # Ip+Dem-complete (Model S3)
  signed_net_list_ip_dem_s,
  trade_cov_s_ip_dem_s, ally_cov_s_ip_dem_s, pta_cov_s_ip_dem_s,
  ideal_dist_cov_s_ip_dem_s, hhi_cov_s_ip_dem_s, export_conc_cov_s_ip_dem_s,
  import_dep_cov_s_ip_dem_s, severity_cov_s_ip_dem_s, gdp_cov_s_ip_dem_s,
  pop_cov_s_ip_dem_s, gdp_diff_cov_s_ip_dem_s, pop_diff_cov_s_ip_dem_s,
  activity_cov_s_ip_dem_s, vdem_cov_s_ip_dem_s,
  all_nodes_ip_dem_s, n_nodes_ip_dem_s, nodes_missing_ip_dem_s,
  # Shared
  years,
  file = "Data/Output/sergm_prepared_data.RData"
)
cat("Signed network data saved to Data/Output/sergm_prepared_data.RData\n")
