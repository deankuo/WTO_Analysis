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
# Models prepared:
#   SERGM-Full  : all countries including EUN
#   SERGM-NoEUN : EUN excluded (national-state benchmark)
#
# Data notes (aligned with tergm_analysis.R):
#   - EUN node attrs in country_meta (via scripts/impute_eun_meta.py)
#   - atopally_t1/label_t1 etc. NOT in ergm_dyad_year_eun.csv
#   - ideal_dist NAs -> 0
#   - Outputs saved to Data/Output/sergm_prepared_data.RData
#
# Required: ergm.sign (Fritz et al.), network, sna, dplyr
# Install : devtools::install_github("corneliusfritz/ergm.sign")
#         Replication: https://doi.org/10.7910/DVN/7ZRCS6
###############################################################################

# ===========================================================================
# 0. SETUP
# ===========================================================================

library(network)
library(sna)
library(dplyr)
library(tidyr)

tryCatch({
  library(ergm.sign)
  cat("ergm.sign loaded.\n")
}, error = function(e) {
  cat("ergm.sign not installed. Preparation will continue; estimation skipped.\n")
  cat("Install: devtools::install_github('corneliusfritz/ergm.sign')\n")
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
# 2. CLEAN ERGM_PANEL COVARIATES  (mirrors tergm_analysis.R §2)
# ===========================================================================

# Trade
for (v in c("total_trade_ij", "export_dependence", "trade_dependence",
            "total_trade_ij_t1", "total_trade_ij_t2", "total_trade_ij_t3")) {
  if (v %in% names(ergm_panel)) ergm_panel[[v]][is.na(ergm_panel[[v]])] <- 0
}

# PTA
if ("label" %in% names(ergm_panel)) {
  ergm_panel$pta_exists <- ifelse(is.na(ergm_panel$label), 0L, as.integer(ergm_panel$label))
}
if ("depth_index" %in% names(ergm_panel)) {
  ergm_panel$depth_index[is.na(ergm_panel$depth_index)] <- 0
}

# ATOP (no lagged ATOP in dataset)
for (v in c("atopally", "defense", "offense", "neutral", "nonagg", "consul")) {
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
# Design (per reviewer suggestion):
#   severity_cov_s is a SEPARATE covariate from the signed adjacency.
#   It captures conflict *intensity* only on negative dyads.
#   C-R  : max dyadic_severity across cases in that year (scale 1-5)
#   TP-R : 0.5 (placeholder; no TP severity instrument available yet)
#   C-TP : 0   (support relationships are a different dimension)
#   Zero : no information about conflict strength
#
# This keeps the sign (who is positive/negative) and the intensity (how
# aggressive the dispute was) as conceptually independent covariates.
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

# Filter edge list and panel
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
all_nodes   <- sort(unique(c(signed_agg_clean$node_a, signed_agg_clean$node_b)))
n_nodes     <- length(all_nodes)

# No-EUN node set
signed_agg_noeun   <- signed_agg_clean %>% filter(node_a != "EUN", node_b != "EUN")
ergm_panel_noeun   <- ergm_panel %>% filter(exporter != "EUN", importer != "EUN")
country_meta_noeun <- country_meta %>% filter(iso3c != "EUN")
severity_agg_noeun <- severity_agg_clean %>% filter(node_a != "EUN", node_b != "EUN")
all_nodes_noeun    <- sort(unique(c(signed_agg_noeun$node_a, signed_agg_noeun$node_b)))
n_nodes_noeun      <- length(all_nodes_noeun)

cat("\nFull node set:", n_nodes, "| No-EUN:", n_nodes_noeun, "\n")

# ===========================================================================
# 5. SIGNED NETWORK BUILDER
# ===========================================================================

#' build_signed_nets
#' @param edges_agg    Aggregated signed edge list (node_a, node_b, year, sign)
#' @param panel        Dyadic panel for edge covariates
#' @param meta         Country-year panel for node attributes
#' @param nodes        Sorted character vector of node labels
#' @param severity_agg Severity aggregation (year, node_a, node_b, severity);
#'                     only negative edges (C-R: 1-5, TP-R: 0.5); C-TP -> 0
#' @return List: signed_net_list, trade_cov_s, ally_cov_s, pta_cov_s,
#'               ideal_dist_cov_s, hhi_cov_s, export_conc_cov_s, import_dep_cov_s,
#'               severity_cov_s, node_attr_list

build_signed_nets <- function(edges_agg, panel, meta, nodes, severity_agg = NULL) {
  n <- length(nodes)
  signed_net_list   <- list()
  trade_cov_s       <- list()
  ally_cov_s        <- list()
  pta_cov_s         <- list()
  ideal_dist_cov_s  <- list()
  hhi_cov_s         <- list()
  export_conc_cov_s <- list()
  import_dep_cov_s  <- list()
  severity_cov_s    <- list()
  node_attr_list    <- list()

  for (yr in years) {
    cat("\rBuilding signed network for year", yr, "...")

    # Signed adjacency (+1 / -1 / 0)
    adj <- matrix(0L, n, n, dimnames = list(nodes, nodes))
    edges_yr <- edges_agg %>% filter(year == yr)
    for (r in seq_len(nrow(edges_yr))) {
      a <- edges_yr$node_a[r]; b <- edges_yr$node_b[r]
      if (a %in% nodes && b %in% nodes) {
        adj[a, b] <- edges_yr$sign[r]
        adj[b, a] <- edges_yr$sign[r]   # undirected
      }
    }

    # Dyadic covariates from ergm_panel
    df_yr <- panel %>% filter(year == yr)
    mk <- function() matrix(0, n, n, dimnames = list(nodes, nodes))
    trade_m    <- mk(); ally_m     <- mk(); pta_m      <- mk()
    hhi_m      <- mk(); exp_conc_m <- mk(); imp_dep_m  <- mk()

    for (r in seq_len(nrow(df_yr))) {
      i <- df_yr$exporter[r]; j <- df_yr$importer[r]
      if (!(i %in% nodes && j %in% nodes)) next
      # Trade, alliance, PTA: symmetrised for undirected SERGM
      trade_m[i,j] <- trade_m[j,i] <- max(trade_m[i,j], df_yr$total_trade_ij[r])
      ally_m[i,j]  <- ally_m[j,i]  <- max(ally_m[i,j],  df_yr$atopally[r])
      pta_m[i,j]   <- pta_m[j,i]   <- max(pta_m[i,j],   df_yr$pta_exists[r])
      # Section covariates: symmetrised (take max over both directions)
      if ("trade_hhi"       %in% names(df_yr))
        hhi_m[i,j]      <- hhi_m[j,i]      <- max(hhi_m[i,j],      df_yr$trade_hhi[r])
      if ("max_export_conc" %in% names(df_yr))
        exp_conc_m[i,j] <- exp_conc_m[j,i] <- max(exp_conc_m[i,j], df_yr$max_export_conc[r])
      if ("max_reverse_dep" %in% names(df_yr))
        imp_dep_m[i,j]  <- imp_dep_m[j,i]  <- max(imp_dep_m[i,j],  df_yr$max_reverse_dep[r])
    }

    # Severity matrix: non-zero only on negative edges (C-R and TP-R)
    # Symmetric (SERGM is undirected); 0 for C-TP and non-edges
    sev_m <- mk()
    if (!is.null(severity_agg)) {
      sev_yr <- severity_agg %>% filter(year == yr)
      for (r in seq_len(nrow(sev_yr))) {
        a <- sev_yr$node_a[r]; b <- sev_yr$node_b[r]
        if (a %in% nodes && b %in% nodes) {
          sev_m[a, b] <- sev_m[b, a] <- sev_yr$severity[r]
        }
      }
    }

    # Node attributes
    meta_yr <- meta %>% filter(year == yr) %>% distinct(iso3c, .keep_all = TRUE)
    node_df <- data.frame(iso3c = nodes, stringsAsFactors = FALSE) %>%
      left_join(meta_yr %>% select(iso3c,
        any_of(c("log_gdppc", "log_pop", "wto_member",
                 "v2x_polyarchy", "idealpointfp",
                 "cum_complainant", "cum_respondent",
                 "election_binary", "reg_quality"))),
        by = "iso3c")

    # Ideal point distance (undirected; NA -> 0)
    ip_vec  <- node_df$idealpointfp
    if (is.null(ip_vec)) ip_vec <- rep(NA_real_, n)
    ideal_m <- outer(ip_vec, ip_vec, function(a, b) abs(a - b))
    ideal_m[is.na(ideal_m)] <- 0
    rownames(ideal_m) <- colnames(ideal_m) <- nodes

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
       node_attr_list    = node_attr_list)
}

# ===========================================================================
# 6. BUILD BOTH VARIANTS
# ===========================================================================

cat("\n=== Building FULL signed network list (incl. EUN) ===\n")
full_s <- build_signed_nets(signed_agg_clean, ergm_panel, country_meta, all_nodes,
                            severity_agg_clean)

cat("\n=== Building NO-EUN signed network list ===\n")
noeun_s <- build_signed_nets(signed_agg_noeun, ergm_panel_noeun,
                             country_meta_noeun, all_nodes_noeun,
                             severity_agg_noeun)

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
# 7. SERGM ESTIMATION  (requires ergm.sign)
# ===========================================================================

if (exists("ergm.sign") || "ergm.sign" %in% loadedNamespaces()) {

  cat("\n=== SERGM FULL (incl. EUN) ===\n")
  # Placeholder — adapt to Fritz et al. replication API.
  # The key function is typically ergm.sign::sergm() or similar.
  # Refer to: https://doi.org/10.7910/DVN/7ZRCS6
  #
  # Suggested signed statistics:
  #   edges_pos / edges_neg          (intercepts)
  #   gwese_pos (enemy-of-enemy -> friend : balanced)
  #   gwesf_pos (friend-of-friend -> friend : balanced)
  #   gwese_neg (enemy-of-enemy -> enemy : imbalanced)
  #   gwesf_neg (friend-of-friend -> enemy : imbalanced)
  #   Exogenous: edgecov(trade_cov_s), edgecov(ally_cov_s), edgecov(pta_cov_s),
  #              edgecov(hhi_cov_s), edgecov(export_conc_cov_s), edgecov(import_dep_cov_s),
  #              edgecov(severity_cov_s)
  #
  # severity_cov_s design (per Fritz et al. suggestion):
  #   Sign (positive/negative relationship) and conflict intensity are
  #   conceptually independent — keep them as separate covariates.
  #   severity_cov_s != 0 only on negative edges:
  #     C-R  : severity_score (1-5, complainant aggressiveness)
  #     TP-R : 0.5 (placeholder until TP severity instrument is available)
  #     C-TP : 0   (support relationships are a different dimension)
  #   Expected sign: severity_cov_s > 0 on negative edges (more aggressive
  #   disputes attract more third-party TP-R engagement / balance-of-power logic)
  #
  # Theoretical predictions:
  #   gwese_pos > 0  (structural balance: enemy of enemy = friend)
  #   gwesf_pos > 0  (structural balance: friend of friend = friend)
  #   alliance on negative edges > 0  (allies use WTO as costly signal)
  #   alliance on positive edges > 0  (allies support each other as TP)

  cat("(Adapt with actual ergm.sign API)\n")
  cat("\n=== SERGM NO-EUN ===\n")
  cat("(Same specification, using signed_net_list_noeun etc.)\n")

} else {
  cat("\nSERGM estimation skipped: ergm.sign not loaded.\n")
  cat("Install: devtools::install_github('corneliusfritz/ergm.sign')\n")
}

# ===========================================================================
# 8. SAVE
# ===========================================================================

save(
  # Full
  signed_net_list, trade_cov_s, ally_cov_s, pta_cov_s, ideal_dist_cov_s,
  hhi_cov_s, export_conc_cov_s, import_dep_cov_s, severity_cov_s,
  all_nodes, n_nodes,
  # No-EUN
  signed_net_list_noeun, trade_cov_s_noeun, ally_cov_s_noeun,
  pta_cov_s_noeun, ideal_dist_cov_s_noeun,
  hhi_cov_s_noeun, export_conc_cov_s_noeun, import_dep_cov_s_noeun,
  severity_cov_s_noeun,
  all_nodes_noeun, n_nodes_noeun,
  # Shared
  years,
  file = "Data/Output/sergm_prepared_data.RData"
)
cat("Signed network data saved to Data/Output/sergm_prepared_data.RData\n")
