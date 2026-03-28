###############################################################################
# WTO Alliance Dispute Behavior — Regression Analysis
# Author: Peng-Ting Kuo
# Date: March 2026
#
# Hypothesis 2: Ally disputes settle earlier — particularly at the consultation
#               phase (Cox PH survival analysis, outcome = time to panel).
# Hypothesis 3: Allies initiate disputes at lower economic stakes compared to
#               non-allies (case-level OLS regression).
#
# Unit of analysis: Complainant-Respondent dyad per case (C-R pair).
#   Some DS numbers have multiple complainants (e.g., DS27); each C-R pair
#   is retained as a separate observation. Clustered SEs by complainant
#   account for within-complainant serial correlation.
#
# Key IV: atopally — formal military alliance (ATOP v5.1), time-varying,
#         matched at consultation year from bilateral_trade_wto.csv.
#
# Interpretation notes:
#   H2 Cox PH: negative coefficient on atopally = lower hazard of reaching
#     panel = ally disputes stay in consultation longer = earlier settlement.
#   H3 OLS: negative coefficient on atopally = allies dispute proportionally
#     smaller product trade flows (after controlling for total trade volume).
#
# Required packages: tidyverse, survival, lubridate, sandwich, lmtest, texreg
###############################################################################

suppressPackageStartupMessages({
  library(tidyverse)
  library(survival)    # Surv(), coxph(), survfit(), cox.zph()
  library(lubridate)   # date parsing helpers
  library(sandwich)    # vcovCL (clustered SEs)
  library(lmtest)      # coeftest
  library(texreg)      # screenreg / texreg / htmlreg
})

# =============================================================================
# 1. LOAD DATA
# =============================================================================

dyadic <- read.csv("Data/wto_dyadic_enriched.csv",
                   stringsAsFactors = FALSE, fileEncoding = "UTF-8")
trade  <- read.csv("Data/bilateral_trade_wto.csv",  stringsAsFactors = FALSE)
meta   <- read.csv("Data/country_meta_1995_2024.csv", stringsAsFactors = FALSE)

cat("Dyadic rows total:", nrow(dyadic), "\n")

# =============================================================================
# 2. BUILD CASE-LEVEL DATASET (one row per C-R pair)
# =============================================================================

case_cr <- dyadic %>%
  filter(relationship == "complainant-respondent") %>%
  rename(iso3_c = iso3_1, iso3_r = iso3_2)

cat("C-R observations:", nrow(case_cr), "\n")

# ---------------------------------------------------------------------------
# 2a. Alliance status + bilateral trade covariates
#
# Join from bilateral_trade_wto at consultation year.
# Direction: exporter = C (complainant), importer = R (respondent).
# ATOP is symmetric — if C->R direction missing, fall back to R->C.
# depth_index: DESTA PTA depth score (0 = no PTA).
# ---------------------------------------------------------------------------

trade_cr <- trade %>%
  select(exporter, importer, year,
         total_trade_ij, export_dependence, atopally, depth_index) %>%
  rename(iso3_c         = exporter,
         iso3_r         = importer,
         total_trade_cr = total_trade_ij,
         exp_dep_cr     = export_dependence)   # C's overall export dep on R

trade_cr_rev <- trade %>%
  select(exporter, importer, year, atopally) %>%
  rename(iso3_r       = exporter,
         iso3_c       = importer,
         atopally_rev = atopally)

case_cr <- case_cr %>%
  left_join(trade_cr,
            by = c("iso3_c", "iso3_r", "consultation_year" = "year")) %>%
  left_join(trade_cr_rev,
            by = c("iso3_c", "iso3_r", "consultation_year" = "year")) %>%
  mutate(atopally  = coalesce(atopally, atopally_rev),
         pta_depth = replace_na(depth_index, 0)) %>%
  select(-atopally_rev, -depth_index)

cat("Alliance coverage:", sum(!is.na(case_cr$atopally)), "/",
    nrow(case_cr), "C-R pairs\n")
cat("Ally C-R pairs:", sum(case_cr$atopally == 1, na.rm = TRUE), "\n")

# ---------------------------------------------------------------------------
# 2b. Node-level attributes — complainant (C) and respondent (R)
#     Joined at consultation year.
#
#   log_gdppc      : log GDP per capita  (economic capacity)
#   log_pop        : log population      (country size)
#   v2x_polyarchy  : V-Dem electoral democracy (0-1)
#   idealpointfp   : UN voting ideal point (1st PC; non-UN members are NA)
#   cum_complainant: cumulative WTO complaints filed (experience)
#   cum_respondent : cumulative times named respondent
#   reg_quality    : WGI regulatory quality (legal institutional capacity)
# ---------------------------------------------------------------------------

meta_vars <- c("iso3c", "year", "log_gdppc", "log_pop",
               "v2x_polyarchy", "idealpointfp",
               "cum_complainant", "cum_respondent", "reg_quality")

meta_c <- meta %>%
  select(any_of(meta_vars)) %>%
  rename_with(~ paste0(., "_c"), .cols = -c(iso3c, year)) %>%
  rename(iso3_c = iso3c)

meta_r <- meta %>%
  select(any_of(meta_vars)) %>%
  rename_with(~ paste0(., "_r"), .cols = -c(iso3c, year)) %>%
  rename(iso3_r = iso3c)

case_cr <- case_cr %>%
  left_join(meta_c, by = c("iso3_c", "consultation_year" = "year")) %>%
  left_join(meta_r, by = c("iso3_r", "consultation_year" = "year"))

# ---------------------------------------------------------------------------
# 2c. Third-party count per case (dispute salience / political importance)
# ---------------------------------------------------------------------------

tp_count <- dyadic %>%
  filter(relationship == "third_party-respondent") %>%
  distinct(case, iso3_2) %>%           # count distinct TP countries
  count(case, name = "n_third_parties")

case_cr <- case_cr %>%
  left_join(tp_count, by = "case") %>%
  mutate(n_third_parties = replace_na(n_third_parties, 0L))

# ---------------------------------------------------------------------------
# 2d. Derived covariates
# ---------------------------------------------------------------------------

case_cr <- case_cr %>%
  mutate(
    # Political alignment: |UN voting ideal-point distance|
    # Larger = more politically opposed; controls for geopolitical rivalry
    ip_distance     = abs(idealpointfp_c - idealpointfp_r),

    # Power asymmetry: |log GDP/cap gap|
    # Larger asymmetry = more unequal; weaker party may settle faster or lack
    # capacity to sustain a panel process
    gdppc_diff      = abs(log_gdppc_c - log_gdppc_r),

    # Joint democracy (weakest-link): min of C and R polyarchy scores
    # Captures that the less democratic actor constrains rule-following
    democracy_min   = pmin(v2x_polyarchy_c, v2x_polyarchy_r, na.rm = TRUE),

    # Complainant democracy: initiator's domestic political constraints
    democracy_c     = v2x_polyarchy_c,

    # Log total bilateral trade (economic ties; controls scale of relationship)
    log_total_trade = log(replace_na(total_trade_cr, 0) + 1),

    # Economic stakes (H3 primary outcome):
    # Disputed product trade C->R at consultation year (t0)
    log_disp_trade  = log(replace_na(disputed_trade_ij_t0, 0) + 1),

    # Economic stakes (H3 alternative outcome):
    # Complainant's export dependency in the disputed sector (normalised)
    disp_dep_cr     = replace_na(disputed_dep_ij_t0, 0),

    # WTO experience of complainant and respondent
    log_cum_comp    = log(replace_na(cum_complainant_c, 0) + 1),
    log_cum_resp    = log(replace_na(cum_respondent_r,  0) + 1),

    # Product case dummy (= 1 if specific traded goods; 0 = policy/regulation)
    is_product_case = as.integer(case_type == "product"),

    # Decade for survival stratification (flexible era-specific baseline hazard)
    decade = factor(paste0(floor(consultation_year / 10) * 10, "s"))
  )

cat("\n--- Sample summary ---\n")
cat("Total C-R pairs:", nrow(case_cr), "\n")
cat("Ally pairs:", sum(case_cr$atopally == 1, na.rm = TRUE), "\n")
cat("Product cases:", sum(case_cr$is_product_case, na.rm = TRUE), "\n")
cat("Cases with panel established:", sum(!is.na(case_cr$panel_established)), "\n")
cat("Median severity:", round(median(case_cr$severity_score, na.rm = TRUE), 2), "\n")

# =============================================================================
# 3. SURVIVAL ANALYSIS — Hypothesis 2
# =============================================================================
#
# DESIGN:
#   Event   : Panel established (binary; date-based = objective)
#   Time    : Months from consultations_requested to panel_established
#   Censoring:
#     - Mutually Agreed Solution (MAS) reached without panel -> censor at MAS
#     - No resolution by 2024-12-31 -> right-censor at end of study
#   Strata  : Decade (1990s/2000s/2010s/2020s) -> allows baseline hazard to
#             differ by era without imposing parametric time-trend
#   Cluster : iso3_c (complainant) -> accounts for serial correlation among
#             repeat litigants (USA, EU, Brazil etc.)
#
# H2 PREDICTION: atopally coefficient < 0
#   = allies face lower instantaneous hazard of panel establishment
#   = disputes more likely to resolve within consultation phase
#
# CONTROLS:
#   log_total_trade  : higher interdependence -> more pressure/capacity to settle
#   gdppc_diff       : large asymmetry -> weaker party may lack panel capacity
#   log_gdppc_c/r    : individual legal and economic capacity
#   ip_distance      : political distance -> less cooperative settlement incentive
#   democracy_min    : democracies prefer rule-based resolution (comply faster)
#   pta_depth        : deep PTA -> alternative dispute channel available
#   severity_score   : aggressive consultation signals intent to escalate
#   log_cum_comp     : experienced complainants escalate strategically
#   n_third_parties  : coalition attention -> may entrench or pressure settlement

# Parse WTO procedural date strings:
# Format "10-Jan-95" (%d-%b-%y) is the common format; fallback for "10 Jan 2004"
parse_wto_date <- function(x) {
  d <- suppressWarnings(as.Date(x, format = "%d-%b-%y"))
  d[is.na(d)] <- suppressWarnings(
    as.Date(x[is.na(d)], format = "%d %B %Y"))
  d
}

case_cr <- case_cr %>%
  mutate(
    consult_date = parse_wto_date(consultations_requested),
    panel_date   = parse_wto_date(panel_established),
    mas_date     = parse_wto_date(mutually_agreed_solution_notified)
  )

# Construct survival time and event indicator
case_cr <- case_cr %>%
  mutate(
    # Event: panel was ever established (date-based)
    event_panel = as.integer(!is.na(panel_date)),

    # Censoring date hierarchy: panel date > MAS date > end-of-study
    censor_date = case_when(
      !is.na(panel_date) ~ panel_date,
      !is.na(mas_date)   ~ mas_date,
      TRUE               ~ as.Date("2024-12-31")
    ),

    # Duration in months (days / 30.44); avoids spurious day-of-month variation
    time_months = as.numeric(censor_date - consult_date) / 30.44
  )

# Survival sample: requires valid consultation date, positive time, ally status
surv_data <- case_cr %>%
  filter(!is.na(consult_date),
         time_months > 0,
         !is.na(atopally))

cat("\n=== H2: Survival sample ===\n")
cat("N:", nrow(surv_data), "\n")
cat("Events (panel established):", sum(surv_data$event_panel), "\n")
cat("Censored:", sum(!surv_data$event_panel), "\n")
cat("Event rate:", round(mean(surv_data$event_panel) * 100, 1), "%\n")
cat("Median follow-up (months):",
    round(median(surv_data$time_months, na.rm = TRUE), 1), "\n")

# ---- Kaplan-Meier: stratified by alliance status (descriptive) ----
km_ally <- survfit(Surv(time_months, event_panel) ~ atopally, data = surv_data)
cat("\n--- Kaplan-Meier (ally=0 vs ally=1) ---\n")
print(summary(km_ally, times = c(6, 12, 24, 48)))

# ---- Cox Proportional Hazards Models ----

# H2.1 — Baseline: alliance + trade + decade strata
cox_h2_1 <- coxph(
  Surv(time_months, event_panel) ~
    atopally +
    log_total_trade +
    strata(decade) +
    cluster(iso3_c),
  data  = surv_data,
  ties  = "efron"
)

# H2.2 — + Power, capacity, and institutional controls
cox_h2_2 <- coxph(
  Surv(time_months, event_panel) ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    pta_depth +
    log_cum_comp +
    n_third_parties +
    strata(decade) +
    cluster(iso3_c),
  data  = surv_data,
  ties  = "efron"
)

# H2.3 — Full specification: + political alignment + democracy + severity
cox_h2_3 <- coxph(
  Surv(time_months, event_panel) ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    democracy_min +
    pta_depth +
    severity_score +
    log_cum_comp +
    n_third_parties +
    strata(decade) +
    cluster(iso3_c),
  data  = surv_data,
  ties  = "efron"
)

cat("\n--- Model H2.1 (Cox, baseline) ---\n");  print(summary(cox_h2_1))
cat("\n--- Model H2.2 (Cox, +capacity) ---\n"); print(summary(cox_h2_2))
cat("\n--- Model H2.3 (Cox, full) ---\n");      print(summary(cox_h2_3))

# Proportional hazards test (Schoenfeld residuals)
# A significant p-value flags a time-varying effect; may need cox.zph interaction
cat("\n--- PH assumption test: Schoenfeld residuals (H2.3) ---\n")
tryCatch(print(cox.zph(cox_h2_3, transform = "km")),
         error = function(e) cat("cox.zph failed:", e$message, "\n"))

# ---- Robustness: Binary logit on whether case reached panel ----
# Drops time information but immune to distributional assumptions of Cox.
# Useful if PH assumption is violated.

logit_h2_1 <- glm(
  event_panel ~
    atopally +
    log_total_trade +
    factor(decade),
  data   = surv_data,
  family = binomial(link = "logit")
)

logit_h2_2 <- glm(
  event_panel ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    democracy_min +
    pta_depth +
    severity_score +
    log_cum_comp +
    n_third_parties +
    factor(decade),
  data   = surv_data,
  family = binomial(link = "logit")
)

logit_cl_1 <- coeftest(logit_h2_1, vcov = vcovCL(logit_h2_1, cluster = ~ iso3_c))
logit_cl_2 <- coeftest(logit_h2_2, vcov = vcovCL(logit_h2_2, cluster = ~ iso3_c))

cat("\n--- Logit robustness H2.1 (clustered SE) ---\n"); print(logit_cl_1)
cat("\n--- Logit robustness H2.2 (clustered SE) ---\n"); print(logit_cl_2)

# =============================================================================
# 4. OLS REGRESSION — Hypothesis 3
# =============================================================================
#
# DESIGN:
#   Primary outcome  : log_disp_trade — log(disputed sector trade C->R at t0 + 1)
#     Captures absolute product trade at stake in the dispute.
#   Alt. outcome     : disp_dep_cr — complainant's export dependency in disputed
#     sector (normalized; fraction of C's total exports destined for R's market
#     in the disputed HS section). Accounts for country-size differences.
#
# NOTE: Conditioning on dispute being filed (INTENSIVE MARGIN only).
#   We do not model the decision to file (selection into WTO litigation).
#   Controlling for log_total_trade is critical: allies trade more due to
#   alliance-induced trade creation. Without this control, any negative
#   coefficient on atopally could be driven by mechanical differences in
#   trade volumes, not by signaling behavior.
#
# H3 PREDICTION: atopally coefficient < 0
#   = after conditioning on total bilateral trade, allies dispute proportionally
#     smaller product flows -> consistent with reputational signaling motive
#     (willing to incur dispute costs at lower economic thresholds)
#
# SE STRUCTURE: cluster by complainant (iso3_c).
#   Major complainants (USA, EU, Canada, Brazil) file dozens of disputes;
#   their cases share unobserved complainant-level factors.

reg_data <- case_cr %>%
  filter(!is.na(atopally),
         !is.na(log_gdppc_c),
         !is.na(log_gdppc_r),
         !is.na(log_disp_trade))

cat("\n=== H3: Regression sample ===\n")
cat("N:", nrow(reg_data), "\n")
cat("Ally pairs:", sum(reg_data$atopally == 1), "\n")
cat("Product cases:", sum(reg_data$is_product_case, na.rm = TRUE), "\n")
cat("Mean log_disp_trade (ally):",
    round(mean(reg_data$log_disp_trade[reg_data$atopally == 1], na.rm = TRUE), 3), "\n")
cat("Mean log_disp_trade (non-ally):",
    round(mean(reg_data$log_disp_trade[reg_data$atopally == 0], na.rm = TRUE), 3), "\n")

# H3.1 — Baseline: alliance + trade scale + year FE
lm_h3_1 <- lm(
  log_disp_trade ~
    atopally +
    log_total_trade +
    factor(consultation_year),
  data = reg_data
)

# H3.2 — + Power asymmetry + capacity + institutional controls
lm_h3_2 <- lm(
  log_disp_trade ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    democracy_c +
    pta_depth +
    log_cum_comp +
    n_third_parties +
    is_product_case +
    factor(consultation_year),
  data = reg_data
)

# H3.3 — Full specification: + political alignment (UN voting distance)
lm_h3_3 <- lm(
  log_disp_trade ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    democracy_c +
    pta_depth +
    log_cum_comp +
    n_third_parties +
    is_product_case +
    factor(consultation_year),
  data = reg_data
)

# H3.4 — Robustness: product cases only
# Policy/regulation disputes may have disputed_trade_ij_t0 = 0 or very low
# because the disputed measure is not sector-specific. Restricting to product
# cases ensures the outcome cleanly measures goods-trade at stake.
lm_h3_4 <- lm(
  log_disp_trade ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    democracy_c +
    pta_depth +
    log_cum_comp +
    n_third_parties +
    factor(consultation_year),
  data = reg_data %>% filter(is_product_case == 1)
)

# H3.5 — Alternative outcome: export dependency (normalized economic stakes)
# Tests whether allies dispute sectors where C is RELATIVELY less dependent
# on R's market — lower normalized stakes even beyond scale effects
lm_h3_5 <- lm(
  disp_dep_cr ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    democracy_c +
    pta_depth +
    log_cum_comp +
    n_third_parties +
    is_product_case +
    factor(consultation_year),
  data = reg_data
)

# ---- Clustered SEs by complainant (iso3_c) ----
data_prod <- reg_data %>% filter(is_product_case == 1)

clust_h3_1 <- coeftest(lm_h3_1, vcov = vcovCL(lm_h3_1, cluster = ~ iso3_c))
clust_h3_2 <- coeftest(lm_h3_2, vcov = vcovCL(lm_h3_2, cluster = ~ iso3_c))
clust_h3_3 <- coeftest(lm_h3_3, vcov = vcovCL(lm_h3_3, cluster = ~ iso3_c))
clust_h3_4 <- coeftest(lm_h3_4, vcov = vcovCL(lm_h3_4, cluster = ~ iso3_c,
                                               data = data_prod))
clust_h3_5 <- coeftest(lm_h3_5, vcov = vcovCL(lm_h3_5, cluster = ~ iso3_c))

cat("\n--- Model H3.3 Full (clustered SE) ---\n");           print(clust_h3_3)
cat("\n--- Model H3.4 Product cases (clustered SE) ---\n");  print(clust_h3_4)
cat("\n--- Model H3.5 Export dependency (clustered SE) ---\n"); print(clust_h3_5)

# =============================================================================
# 5. OUTPUT TABLES
# =============================================================================

# Post-process a texreg-generated .tex to reduce line spacing and column padding
compress_tex <- function(filepath, arraystretch = 0.82, tabcolsep = "3pt") {
  lines <- readLines(filepath)
  tab_idx <- grep("\\\\begin\\{tabular", lines)[1]
  if (!is.na(tab_idx)) {
    insert <- c(
      sprintf("\\renewcommand{\\arraystretch}{%.2f}", arraystretch),
      sprintf("\\setlength{\\tabcolsep}{%s}", tabcolsep)
    )
    lines <- c(lines[seq_len(tab_idx - 1)], insert, lines[tab_idx:length(lines)])
    writeLines(lines, filepath)
  }
  invisible(filepath)
}

# Helper: extract coxph (with cluster) into texreg object
# cluster() in coxph() causes summary() to report robust SEs automatically
extract_cox_robust <- function(mod) {
  s     <- summary(mod)
  coefs <- s$coefficients[, "coef"]
  # Column label varies by survival package version
  se_col <- if ("robust se" %in% colnames(s$coefficients)) "robust se" else "se(coef)"
  ses   <- s$coefficients[, se_col]
  pvs   <- s$coefficients[, ncol(s$coefficients)]
  createTexreg(
    coef.names  = names(coefs),
    coef        = unname(coefs),
    se          = unname(ses),
    pvalues     = unname(pvs),
    gof.names   = c("N", "N events", "Log-lik."),
    gof         = c(mod$n, mod$nevent, as.numeric(logLik(mod))),
    gof.decimal = c(FALSE, FALSE, TRUE)
  )
}

# Coefficient label maps
coef_map_h2 <- list(
  "atopally"        = "ATOP Alliance (C-R)",
  "log_total_trade" = "Log Bilateral Trade",
  "gdppc_diff"      = "|GDP/cap Gap|",
  "log_gdppc_c"     = "Log GDP/cap: Complainant",
  "log_gdppc_r"     = "Log GDP/cap: Respondent",
  "ip_distance"     = "UN Voting Distance",
  "democracy_min"   = "Joint Democracy (min)",
  "pta_depth"       = "PTA Depth",
  "severity_score"  = "Dispute Severity",
  "log_cum_comp"    = "Log Cumul. Complaints",
  "n_third_parties" = "N Third Parties"
)

coef_map_h3 <- list(
  "atopally"        = "ATOP Alliance (C-R)",
  "log_total_trade" = "Log Bilateral Trade",
  "gdppc_diff"      = "|GDP/cap Gap|",
  "log_gdppc_c"     = "Log GDP/cap: Complainant",
  "log_gdppc_r"     = "Log GDP/cap: Respondent",
  "ip_distance"     = "UN Voting Distance",
  "democracy_c"     = "Complainant Democracy",
  "pta_depth"       = "PTA Depth",
  "log_cum_comp"    = "Log Cumul. Complaints",
  "n_third_parties" = "N Third Parties",
  "is_product_case" = "Product Case"
)

# Clustered SE overrides for texreg (applied to all H3 OLS models)
h3_ses <- list(
  clust_h3_1[, "Std. Error"],
  clust_h3_2[, "Std. Error"],
  clust_h3_3[, "Std. Error"],
  clust_h3_4[, "Std. Error"],
  clust_h3_5[, "Std. Error"]
)
h3_pvs <- list(
  clust_h3_1[, "Pr(>|t|)"],
  clust_h3_2[, "Pr(>|t|)"],
  clust_h3_3[, "Pr(>|t|)"],
  clust_h3_4[, "Pr(>|t|)"],
  clust_h3_5[, "Pr(>|t|)"]
)

# ---- Screen output ----

cat("\n====== H2: Cox PH — Time to Panel Escalation ======\n")
screenreg(
  list(extract_cox_robust(cox_h2_1),
       extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3)),
  custom.model.names = c("H2.1 Baseline", "H2.2 +Capacity", "H2.3 Full"),
  custom.coef.map    = coef_map_h2,
  digits             = 3,
  caption = "Cox PH: Alliance and Time to Panel Escalation (H2)"
)

cat("\n====== H3: OLS — Economic Stakes ======\n")
screenreg(
  list(lm_h3_1, lm_h3_2, lm_h3_3, lm_h3_4, lm_h3_5),
  override.se      = h3_ses,
  override.pvalues = h3_pvs,
  custom.model.names = c("H3.1 Baseline", "H3.2 +Node",
                         "H3.3 Full",     "H3.4 Products", "H3.5 Dep"),
  custom.coef.map  = coef_map_h3,
  omit.coef        = "factor\\(consultation_year\\)",
  digits           = 3,
  caption = "OLS: Alliance and Economic Stakes of Disputes (H3)"
)

# ---- LaTeX: H2 ----
texreg(
  list(extract_cox_robust(cox_h2_1),
       extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3)),
  file               = "Data/Output/h2_cox_results.tex",
  custom.model.names = c("H2.1", "H2.2", "H2.3"),
  custom.coef.map    = coef_map_h2,
  digits             = 3,
  caption            = "Alliance and Time to Panel Escalation: Cox PH (H2)",
  caption.above      = TRUE,
  label              = "tab:h2_cox",
  fontsize           = "footnotesize",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = paste0(
    "\\textit{Notes:} Cox proportional hazards, Efron method. ",
    "Outcome: months from consultation request to panel establishment. ",
    "Censored at MAS date (if settled pre-panel) or 2024-12-31 (if ongoing). ",
    "Decade strata (1990s--2020s) allow era-specific baseline hazard. ",
    "Cluster-robust SEs by complainant. ",
    "Negative coefficient $=$ lower hazard of panel escalation $=$ earlier settlement. ",
    "H2 predicts $\\hat{\\beta}_{\\text{ally}} < 0$."
  )
)
compress_tex("Data/Output/h2_cox_results.tex")
cat("H2 LaTeX saved to Data/Output/h2_cox_results.tex\n")

# ---- LaTeX: H3 ----
texreg(
  list(lm_h3_1, lm_h3_2, lm_h3_3, lm_h3_4, lm_h3_5),
  override.se        = h3_ses,
  override.pvalues   = h3_pvs,
  file               = "Data/Output/h3_ols_results.tex",
  custom.model.names = c("H3.1", "H3.2", "H3.3", "H3.4 Products", "H3.5 Dep"),
  custom.coef.map    = coef_map_h3,
  omit.coef          = "factor\\(consultation_year\\)",
  digits             = 3,
  caption            = "Alliance and Economic Stakes of WTO Disputes: OLS (H3)",
  caption.above      = TRUE,
  label              = "tab:h3_ols",
  fontsize           = "footnotesize",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = paste0(
    "\\textit{Notes:} OLS with year fixed effects (suppressed). ",
    "Outcome: log disputed sector trade C$\\to$R at consultation year (H3.1--H3.4); ",
    "complainant export dependency in disputed sector (H3.5). ",
    "H3.4 restricted to product disputes (excludes horizontal policy cases). ",
    "Cluster-robust SEs by complainant. ",
    "H3 predicts $\\hat{\\beta}_{\\text{ally}} < 0$ after conditioning on ",
    "total bilateral trade."
  )
)
compress_tex("Data/Output/h3_ols_results.tex")
cat("H3 LaTeX saved to Data/Output/h3_ols_results.tex\n")

# ---- HTML: joint summary ----
htmlreg(
  list(extract_cox_robust(cox_h2_1), extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3),
       lm_h3_1, lm_h3_3, lm_h3_4),
  override.se      = c(list(NULL, NULL, NULL), h3_ses[c(1, 3, 4)]),
  override.pvalues = c(list(NULL, NULL, NULL), h3_pvs[c(1, 3, 4)]),
  file               = "Data/Output/h2_h3_results.html",
  custom.model.names = c("H2.1", "H2.2", "H2.3 Cox",
                         "H3.1", "H3.3 OLS", "H3.4 OLS"),
  custom.coef.map    = c(coef_map_h2,
                         coef_map_h3[!names(coef_map_h3) %in% names(coef_map_h2)]),
  omit.coef          = "factor\\(consultation_year\\)|factor\\(decade\\)",
  digits             = 3,
  caption            = "Alliance Effects on WTO Dispute Behavior (H2 & H3)",
  caption.above      = TRUE
)
cat("HTML saved to Data/Output/h2_h3_results.html\n")

cat("\n=== Done ===\n")
