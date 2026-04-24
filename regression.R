###############################################################################
# WTO Alliance Dispute Behavior — Regression Analysis
# Author: Peng-Ting Kuo
# Date: March 2026
#
# Hypothesis 2: Allied disputants escalate less — disputes between ATOP allies
#   are less likely to advance through WTO procedural stages beyond consultation.
#   PRIMARY  : Ordinal logistic regression (polr); DV = final_stage (0–3).
#   ROBUSTNESS: Cox PH survival; DV = time to panel establishment.
#
# Hypothesis 3: Allies initiate disputes at lower economic stakes compared to
#   non-allies (case-level OLS regression).
#
# Unit of analysis: Complainant-Respondent dyad per case (C-R pair).
#   Some DS numbers have multiple complainants (e.g., DS27); each C-R pair
#   is a separate observation. Clustered SEs by complainant (iso3_c).
#
# Key IV: atopally — formal military alliance (ATOP v5.1), time-varying,
#         matched at consultation year from bilateral_trade_wto.csv.
#
# H2 DV — final_stage (ordered, 4 levels):
#   0 = Consultation only  (never reached panel)
#   1 = Panel stage        (panel established)
#   2 = Appellate stage    (appellate body proceeding)
#   3 = Implementation / Retaliation
#
#   MAS coding: assign to the stage at which settlement occurred using dates.
#     MAS before/at panel establishment     → stage 0
#     MAS after panel, before panel report  → stage 1
#     MAS after panel report, before AB     → stage 2
#     MAS after AB report                   → stage 3
#
# H2 prediction: atopally < 0 (negative log-odds of reaching a higher stage).
# H3 prediction: atopally < 0 (smaller disputed trade after conditioning on
#   total bilateral trade volume).
#
# Required packages: tidyverse, MASS, survival, lubridate, sandwich, lmtest,
#                    texreg, brant (optional)
###############################################################################
rm(list = ls())

suppressPackageStartupMessages({
    library(MASS)        # polr() — ordered logistic regression
    library(survival)    # Surv(), coxph(), survfit(), cox.zph()
    library(lubridate)
    library(sandwich)    # vcovCL
    library(lmtest)      # coeftest
    library(texreg)
    library(tidyverse)
    library(conflicted)
    library(lme4)        # mixed models (dyad random effects)
    library(broom.mixed) # tidy() for lme4 objects
    library(modelsummary)
    library(fixest)
    conflicts_prefer(dplyr::select)
    conflicts_prefer(dplyr::filter)
})

# =============================================================================
# 1. LOAD DATA
# =============================================================================

dyadic <- read.csv("Data/wto_dyadic_enriched.csv",
                   stringsAsFactors = FALSE, fileEncoding = "UTF-8")
trade  <- read.csv("Data/bilateral_trade_wto.csv",  stringsAsFactors = FALSE)
meta   <- read.csv("Data/country_meta_1995_2024.csv", stringsAsFactors = FALSE)

cat("Dyadic rows total:", nrow(dyadic), "\n")

# Factor Analysis
dimensions <- dyadic %>%
    filter(!(relationship %in% c("complainant-third_party", "third_party-respondent"))) %>%
    select(rhetorical_aggressiveness, escalation_ultimatum, domestic_victimhood) %>%
    na.omit() # drop cases after 2024
fa <- factanal(dimensions,
               factors = 1,
               scores = "regression",
               rotation = "varimax"
               )

print(fa)


# =============================================================================
# 2. BUILD CASE-LEVEL DATASET (one row per C-R pair)
# =============================================================================

case_cr <- dyadic %>%
  filter(relationship == "complainant-respondent") %>%
  rename(iso3_c = iso3_1, iso3_r = iso3_2) %>%
  mutate(severity_score_v2 = (rhetorical_aggressiveness + escalation_ultimatum + domestic_victimhood) / 3)

cat("C-R observations:", nrow(case_cr), "\n")

# ---------------------------------------------------------------------------
# 2a. Alliance status + bilateral trade covariates
#
# Join from bilateral_trade_wto at consultation year.
# ATOP is symmetric — fall back to R->C direction if C->R missing.
# ---------------------------------------------------------------------------

trade_cr <- trade %>%
  select(exporter, importer, year, total_trade_ij, export_dependence, atopally, depth_index) %>%
  rename(iso3_c         = exporter,
         iso3_r         = importer,
         total_trade_cr = total_trade_ij,
         exp_dep_cr     = export_dependence)

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
# 2b. Node-level attributes (joined at consultation year)
# ---------------------------------------------------------------------------

meta_vars <- c("iso3c", "year", "log_gdppc", "log_pop",
               "v2x_polyarchy", "idealpointfp",
               "cum_complainant", "cum_respondent")

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
# 2c. Third-party count per case (dispute salience)
# ---------------------------------------------------------------------------

tp_count <- dyadic %>%
  dplyr::filter(relationship == "third_party-respondent") %>%
  distinct(case, iso3_2) %>%
  count(case, name = "n_third_parties")

case_cr <- case_cr %>%
  left_join(tp_count, by = "case") %>%
  mutate(n_third_parties = replace_na(n_third_parties, 0L))

# ---------------------------------------------------------------------------
# 2d. Derived covariates
# ---------------------------------------------------------------------------

case_cr <- case_cr %>%
  mutate(
    ip_distance     = abs(idealpointfp_c - idealpointfp_r),
    gdppc_diff      = abs(log_gdppc_c - log_gdppc_r),
    # democracy_min   = pmin(v2x_polyarchy_c, v2x_polyarchy_r, na.rm = TRUE),
    democracy_c     = v2x_polyarchy_c,
    log_total_trade = log(replace_na(total_trade_cr, 0) + 1),
    log_disp_trade  = log(replace_na(disputed_trade_ij_t0, 0) + 1),
    disp_dep_cr     = replace_na(disputed_dep_ij_t0, 0),
    log_cum_comp    = log(replace_na(cum_complainant_c, 0) + 1),
    log_cum_resp    = log(replace_na(cum_respondent_r,  0) + 1),
    is_product_case = as.integer(case_type == "product"),
    decade = factor(paste0(floor(consultation_year / 10) * 10, "s"))
  )

cat("\n--- Sample summary ---\n")
cat("Total C-R pairs:", nrow(case_cr), "\n")
cat("Ally pairs:", sum(case_cr$atopally == 1, na.rm = TRUE), "\n")
cat("Product cases:", sum(case_cr$is_product_case, na.rm = TRUE), "\n")
cat("Cases with panel established:", sum(!is.na(case_cr$panel_established)), "\n")
cat("Median severity:", round(median(case_cr$severity_score, na.rm = TRUE), 2), "\n")

# =============================================================================
# 3. HYPOTHESIS 2 — PRIMARY: Ordinal Logistic Regression
# =============================================================================

# ---------------------------------------------------------------------------
# Step 1 — Confirm exact column names for date/stage fields
# ---------------------------------------------------------------------------
cat("\n--- Columns in case_cr matching panel/appellate/mutually/stage/report ---\n")
h2_cols <- grep(
  "panel|appellate|mutually|agreed|solution|stage|report|reasonable|implementation",
  names(case_cr), value = TRUE, ignore.case = TRUE
)
cat(paste(h2_cols, collapse = "\n"), "\n")

# ---------------------------------------------------------------------------
# Step 2 — Parse procedural date columns
# Format "%d-%b-%y" (07-Nov-96) primary; fallback "%d %B %Y" (07 November 1996)
# ---------------------------------------------------------------------------
parse_wto_date <- function(x) {
  d <- suppressWarnings(as.Date(x, format = "%d-%b-%y"))
  d[is.na(d)] <- suppressWarnings(
    as.Date(x[is.na(d)], format = "%d %B %Y"))
  d
}

# Parse conditionally — graceful fallback to NA column if field absent
parse_if_exists <- function(df, col) {
  if (col %in% names(df)) parse_wto_date(df[[col]])
  else as.Date(rep(NA_character_, nrow(df)))
}

case_cr$consult_date    <- parse_if_exists(case_cr, "consultations_requested")
case_cr$panel_date      <- parse_if_exists(case_cr, "panel_established")
case_cr$panel_report_dt <- parse_if_exists(case_cr, "panel_report_circulated")
case_cr$ab_report_dt    <- parse_if_exists(case_cr,
                             "appellate_body_report_circulated")
case_cr$mas_date        <- parse_if_exists(case_cr,
                             "mutually_agreed_solution_notified")
case_cr$rpt_date        <- parse_if_exists(case_cr,
                             "reasonable_period_of_time")

cat("\nDate coverage after parsing:\n")
cat("  consult_date   :", sum(!is.na(case_cr$consult_date)), "\n")
cat("  panel_date     :", sum(!is.na(case_cr$panel_date)), "\n")
cat("  panel_report_dt:", sum(!is.na(case_cr$panel_report_dt)), "\n")
cat("  ab_report_dt   :", sum(!is.na(case_cr$ab_report_dt)), "\n")
cat("  mas_date       :", sum(!is.na(case_cr$mas_date)), "\n")
cat("  rpt_date       :", sum(!is.na(case_cr$rpt_date)), "\n")

# ---------------------------------------------------------------------------
# Step 3 — Construct final_stage
#
# For non-MAS cases: map dispute_stage directly to numeric level.
# For MAS cases: assign to the highest stage reached BEFORE the MAS was
#   notified, using date comparisons.
#   • is.na(panel_date) OR mas ≤ panel  → settled at consultation (0)
#   • is.na(panel_report) OR mas ≤ panel_report → settled during panel (1)
#   • is.na(ab_report) OR mas ≤ ab_report → settled during appellate (2)
#   • otherwise (mas after AB report)   → settled at implementation (3)
# ---------------------------------------------------------------------------
case_cr <- case_cr %>%
  mutate(
    final_stage_int = case_when(
      # MAS cases: assign by stage at which MAS was notified
      dispute_stage == "Mutually Agreed" & is.na(mas_date)                              ~ 0L,
      dispute_stage == "Mutually Agreed" &
        (is.na(panel_date)      | mas_date <= panel_date)                               ~ 0L,
      dispute_stage == "Mutually Agreed" &
        (is.na(panel_report_dt) | mas_date <= panel_report_dt)                         ~ 1L,
      dispute_stage == "Mutually Agreed" &
        (is.na(ab_report_dt)    | mas_date <= ab_report_dt)                            ~ 2L,
      dispute_stage == "Mutually Agreed"                                                ~ 3L,
      # Non-MAS: direct mapping from dispute_stage
      dispute_stage == "Consultation"                                                   ~ 0L,
      dispute_stage == "Panel"                                                          ~ 1L,
      dispute_stage == "Appellate Body"                                                 ~ 2L,
      dispute_stage %in% c("Implementation", "Retaliation")                            ~ 3L,
      TRUE ~ NA_integer_   # "Other" → exclude
    ),
    final_stage = factor(
      final_stage_int,
      levels  = 0:3,
      labels  = c("Consultation", "Panel", "Appellate", "Implementation"),
      ordered = TRUE
    )
  )

# ---------------------------------------------------------------------------
# Step 4 — Verification
# ---------------------------------------------------------------------------
cat("\n=== final_stage distribution (all C-R pairs) ===\n")
fs_tab <- table(case_cr$final_stage, useNA = "ifany")
print(fs_tab)
cat("Proportions (non-NA):\n")
print(round(prop.table(fs_tab[!is.na(names(fs_tab))]) * 100, 1))

cat("\n--- Cross-tab: dispute_stage × final_stage ---\n")
print(table(case_cr$dispute_stage, case_cr$final_stage, useNA = "ifany"))
cat("\n--- MAS cases → final_stage ---\n")
print(table(
  case_cr$final_stage[case_cr$dispute_stage == "Mutually Agreed"],
  useNA = "ifany"
))

cat("\n--- final_stage × atopally (row %) ---\n")
ct_ally <- table(case_cr$final_stage, case_cr$atopally)
print(ct_ally)
cat("Row proportions:\n")
print(round(prop.table(ct_ally, margin = 1) * 100, 1))

# =============================================================================
# 3a. ORDINAL LOGISTIC REGRESSION — OL1–OL4
# =============================================================================
#
# Sample restriction: consultation_year <= 2024.
#   Disputes filed in 2024 are excluded entirely (not even as censored obs).
#   Cases filed in 2024 have not had enough time to advance through procedural
#   stages, so including them would artificially inflate the "Consultation"
#   category and bias the atopally estimate toward zero.
# =============================================================================

ord_data <- case_cr %>%
  dplyr::filter(!is.na(atopally),
         !is.na(final_stage),
         consultation_year <= 2024)

cat("\n=== H2: Ordinal logit sample ===\n")
cat("N:", nrow(ord_data), "\n")
cat("Ally pairs:", sum(ord_data$atopally == 1), "\n")
cat("final_stage distribution:\n")
print(table(ord_data$final_stage))
cat("\nfinal_stage × atopally:\n")
print(table(ord_data$final_stage, ord_data$atopally))
cat("Row %:\n")
print(round(prop.table(table(ord_data$final_stage, ord_data$atopally),
                       margin = 1) * 100, 1))

# OL1 — Baseline: alliance + trade + decade FE
ol1 <- polr(
  final_stage ~
    atopally +
    log_total_trade +
    decade,
  data   = ord_data,
  Hess   = TRUE,
  method = "logistic"
)

# OL2 — + Capacity, power asymmetry, institutional controls
ol2 <- polr(
  final_stage ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    pta_depth +
    log_cum_comp +
    log_cum_resp +
    n_third_parties +
    decade,
  data   = ord_data,
  Hess   = TRUE,
  method = "logistic"
)

# OL3 — + Political alignment controls
#
# ip_distance is added here as a CONTROL to isolate the alliance channel:
# if atopally remains stable from OL2 to OL3, the effect is distinct from
# general UN voting alignment (i.e., treaty commitment, not ideology).
# If atopally shrinks substantially (>20%), part of the effect may operate
# through political proximity rather than the formal alliance obligation itself.
ord_data_ip <- ord_data %>%
  dplyr::filter(!is.na(ip_distance))

ol3 <- polr(
  final_stage ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    democracy_c +
    ip_distance +
    pta_depth +
    log_cum_comp +
    log_cum_resp +
    n_third_parties +
    decade,
  data   = ord_data_ip,
  Hess   = TRUE,
  method = "logistic"
)

# OL4 — + Dispute severity (paper's measurement contribution)
#
# severity_score from LLM-RAG pipeline captures how aggressively the complaint
# was filed. If escalation is driven by initial rhetoric/stakes, this should
# absorb part of the atopally effect — or leave it unchanged if ally behaviour
# operates independently of filing tone.
ord_data_full <- ord_data_ip %>%
  dplyr::filter(!is.na(severity_score))

ol4 <- polr(
  final_stage ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    democracy_c +
    ip_distance +
    pta_depth +
    log_cum_comp +
    log_cum_resp +
    n_third_parties +
    severity_score +
    decade,
  data   = ord_data_full,
  Hess   = TRUE,
  method = "logistic"
)

cat("\n--- OL1 ---\n"); print(summary(ol1))
cat("\n--- OL2 ---\n"); print(summary(ol2))
cat("\n--- OL3 ---\n"); print(summary(ol3))
cat("\n--- OL4 ---\n"); print(summary(ol4))

# Atopally stability check: OL2 → OL3
coef_ol2 <- coef(ol2)["atopally"]
coef_ol3 <- coef(ol3)["atopally"]
pct_change <- (coef_ol3 - coef_ol2) / abs(coef_ol2) * 100
cat(sprintf(
  "\n--- atopally: OL2 = %.4f  |  OL3 = %.4f  |  change = %.1f%%\n",
  coef_ol2, coef_ol3, pct_change
))
if (abs(pct_change) > 20) {
  cat("NOTE: atopally shrinks >20% when ip_distance is added (OL2 -> OL3).\n",
      "      Part of the alliance effect may operate through political alignment.\n")
} else {
  cat("NOTE: atopally is stable (OL2 -> OL3).\n",
      "      Alliance effect is independent of UN voting alignment.\n")
}

# --- Proportional odds assumption: Brant test ---
cat("\n--- Brant test (proportional odds assumption): OL4 ---\n")
tryCatch({
  library(brant)
  print(brant(ol4))
}, error = function(e) {
  cat("brant not available:", e$message, "\n")
  cat("Install: install.packages('brant')\n")
})

# ---------------------------------------------------------------------------
# Clustered SE extraction helper for polr
#
# sandwich::vcovCL supports polr via estfun.polr / bread.polr (sandwich >= 2.5).
# Matches by name because polr's vcov() includes thresholds appended after
# predictor coefficients; texreg's extract may order them differently.
# ---------------------------------------------------------------------------
extract_polr_cl <- function(model, data) {
  tr <- tryCatch(texreg::extract(model), error = function(e) NULL)
  if (is.null(tr)) return(NULL)

  cl_vc <- tryCatch(
    vcovCL(model, cluster = ~ iso3_c, data = data),
    error = function(e) {
      warning("vcovCL failed, using model vcov: ", e$message)
      vcov(model)
    }
  )
  cl_se   <- sqrt(diag(cl_vc))
  fb_se   <- sqrt(diag(vcov(model)))

  matched <- cl_se[match(tr@coef.names, names(cl_se))]
  # Fall back to model SE for thresholds that may not be in vcovCL names
  unmatched <- is.na(matched)
  if (any(unmatched)) {
    matched[unmatched] <- fb_se[match(tr@coef.names[unmatched], names(fb_se))]
  }

  tr@se      <- unname(matched)
  tr@pvalues <- 2 * pnorm(-abs(tr@coef / tr@se))
  tr
}

tr_ol1 <- extract_polr_cl(ol1, ord_data)
tr_ol2 <- extract_polr_cl(ol2, ord_data)
tr_ol3 <- extract_polr_cl(ol3, ord_data_ip)
tr_ol4 <- extract_polr_cl(ol4, ord_data_full)

coef_map_ol <- list(
  "atopally"        = "ATOP Alliance",
  "log_total_trade" = "Bilateral Trade",
  "gdppc_diff"      = "GDP/cap Gap",
  "log_gdppc_c"     = "GDP/cap: Complainant",
  "log_gdppc_r"     = "GDP/cap: Respondent",
  "democracy_c"     = "Democracy: Complainant",
  "ip_distance"     = "UN Voting Distance",
  "pta_depth"       = "PTA Depth",
  "severity_score"  = "Dispute Severity",
  "log_cum_comp"    = "Cumul. Complaints",
  "log_cum_resp"    = "Cumul. Respondent",
  "n_third_parties" = "N Third Parties"
)

cat("\n====== H2: Ordered Logit — Escalation Stage ======\n")
screenreg(
  list(tr_ol1, tr_ol2, tr_ol3, tr_ol4),
  custom.model.names = c("OL1 Baseline", "OL2 +Capacity",
                         "OL3 +Alignment", "OL4 +Severity"),
  custom.coef.map    = coef_map_ol,
  omit.coef          = "decade",
  digits             = 3,
  caption = "Ordered Logit: Alliance and WTO Dispute Escalation (H2)"
)

# =============================================================================
# 3b. ROBUSTNESS — Cox Proportional Hazards
# =============================================================================
#
# Event   : Panel established (objective date-based indicator)
# Time    : Months from consultation request to panel establishment
# Censoring (corrected):
#   • MAS notified BEFORE panel established → censor at MAS date
#     (dispute ended without escalation; not a panel-reaching event)
#   • No panel, no MAS, no resolution by study end → censor 2024-12-31
# Strata  : Decade → era-specific baseline hazard
# Cluster : iso3_c → repeat-litigant serial correlation
# Sample  : consultation_year <= 2023 (same restriction as ordinal models)
# =============================================================================

case_cr <- case_cr %>%
  mutate(
    event_panel = as.integer(!is.na(panel_date)),
    censor_date = case_when(
      !is.na(panel_date)                   ~ panel_date,
      !is.na(mas_date) & is.na(panel_date) ~ mas_date,
      TRUE                                 ~ as.Date("2024-12-31")
    ),
    time_months = as.numeric(censor_date - consult_date) / 30.44
  )

surv_data <- case_cr %>%
  dplyr::filter(!is.na(consult_date),
         time_months > 0,
         !is.na(atopally),
         consultation_year <= 2023)

cat("\n=== H2 Robustness: Cox PH sample ===\n")
cat("N:", nrow(surv_data), "\n")
cat("Events (panel):", sum(surv_data$event_panel), "\n")
cat("Censored:", sum(!surv_data$event_panel), "\n")
cat("Event rate:", round(mean(surv_data$event_panel) * 100, 1), "%\n")
cat("Median follow-up (months):",
    round(median(surv_data$time_months, na.rm = TRUE), 1), "\n")

# KM descriptive
km_ally <- survfit(Surv(time_months, event_panel) ~ atopally, data = surv_data)
cat("\n--- Kaplan-Meier (ally=0 vs ally=1) ---\n")
print(summary(km_ally, times = c(6, 12, 24, 48)))

# Cox H2.1 — Baseline
cox_h2_1 <- coxph(
  Surv(time_months, event_panel) ~
    atopally +
    log_total_trade +
    strata(decade) +
    cluster(iso3_c),
  data = surv_data, ties = "efron"
)

# Cox H2.2 — + Capacity & institutional controls
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
  data = surv_data, ties = "efron"
)

# Cox H2.3 — Full
cox_h2_3 <- coxph(
  Surv(time_months, event_panel) ~
    atopally +
    log_total_trade +
    gdppc_diff +
    log_gdppc_c +
    log_gdppc_r +
    ip_distance +
    pta_depth +
    severity_score +
    log_cum_comp +
    n_third_parties +
    strata(decade) +
    cluster(iso3_c),
  data = surv_data, ties = "efron"
)

cat("\n--- Cox H2.1 ---\n"); print(summary(cox_h2_1))
cat("\n--- Cox H2.2 ---\n"); print(summary(cox_h2_2))
cat("\n--- Cox H2.3 ---\n"); print(summary(cox_h2_3))

# PH assumption
cat("\n--- PH test: Schoenfeld residuals (cox_h2_3) ---\n")
tryCatch(print(cox.zph(cox_h2_3, transform = "km")),
         error = function(e) cat("cox.zph failed:", e$message, "\n"))

# Logit robustness (panel vs no-panel, drops time dimension)
logit_h2_1 <- glm(
  event_panel ~ atopally + log_total_trade + factor(decade),
  data = surv_data, family = binomial(link = "logit")
)
logit_h2_2 <- glm(
  event_panel ~
    atopally + log_total_trade +
    gdppc_diff + log_gdppc_c + log_gdppc_r +
    ip_distance + democracy_c +
    pta_depth + severity_score +
    log_cum_comp + n_third_parties + factor(decade),
  data = surv_data, family = binomial(link = "logit")
)
logit_cl_1 <- coeftest(logit_h2_1, vcov = vcovCL(logit_h2_1, cluster = ~ iso3_c))
logit_cl_2 <- coeftest(logit_h2_2, vcov = vcovCL(logit_h2_2, cluster = ~ iso3_c))
cat("\n--- Logit robustness H2.1 (clustered SE) ---\n"); print(logit_cl_1)
cat("\n--- Logit robustness H2.2 (clustered SE) ---\n"); print(logit_cl_2)

# =============================================================================
# H3 Dyad-year panel interaction test
# 
# DESIGN:
#   Unit    : directed dyad-year (complainant i, respondent j, year t)
#   DV      : dispute_ij_t (binary: did i file against j in year t?)
#   Key test: atopally × log_total_trade
#             If β < 0: ally effect is stronger when trade is LOW
#             → consistent with signaling theory (H3)
#             If β > 0: ally effect is stronger when trade is HIGH
#             → consistent with economic grievance / domestic pressure
#
# NOTE: This uses the same bilateral_trade_wto panel as TERGM (H1),
#       restricted to dyad-years where both countries are WTO members
#       and consultation_year <= 2023.
# =============================================================================

# -----------------------------------------------------------------------------
# STEP 1: Construct dyad-year panel
# -----------------------------------------------------------------------------
# 'bilateral_trade_wto' is your existing panel used for TERGM
# It should have one row per directed dyad-year (exporter, importer, year)
# with columns: atopally, total_trade_ij, export_dependence, etc.
#
# Add dispute indicator: did exporter file against importer in this year?
# -----------------------------------------------------------------------------

# Build dispute indicator from case_cr
dispute_indicator <- case_cr %>%
    filter(consultation_year <= 2024) %>%
    select(iso3_c, iso3_r, consultation_year) %>%
    distinct() %>%
    mutate(dispute = 1L)

# Merge into dyad-year panel
dyad_panel_h3 <- trade %>%
    filter(year >= 1995, year <= 2023) %>%
    left_join(
        dispute_indicator,
        by = c("exporter" = "iso3_c",
               "importer" = "iso3_r",
               "year"     = "consultation_year")
    ) %>%
    mutate(
        dispute          = replace_na(dispute, 0L),
        log_total_trade  = log(replace_na(total_trade_ij, 0) + 1),
        # Center log_total_trade for interpretable interaction
        log_trade_c      = log_total_trade - mean(log_total_trade, na.rm = TRUE),
        # Dyad identifier (undirected: always sort so smaller iso3 comes first)
        dyad_id          = paste(pmin(exporter, importer),
                                 pmax(exporter, importer), sep = "_")
    ) %>%
    filter(!is.na(atopally))

cat("Dyad-year panel:\n")
cat("  Rows:", nrow(dyad_panel_h3), "\n")
cat("  Dispute-years:", sum(dyad_panel_h3$dispute), "\n")
cat("  Dispute rate:", round(mean(dyad_panel_h3$dispute) * 100, 3), "%\n")
cat("  Ally dyad-years:", sum(dyad_panel_h3$atopally == 1), "\n")

# ---------------------------------------------------------------------------
# Impute meta for H3 (matching TERGM imputation strategy):
#   1. Carry-forward (downup) for GDP, democracy, ideal points — fills small
#      gaps due to late data releases or late WTO accession.
#   2. cum_complainant / cum_respondent: NA → 0 (pre-accession years).
#   3. idealpointfp: still NA for structural non-UN members (Taiwan, Kosovo,
#      Vatican) after fill; those dyads are dropped by the model's listwise
#      deletion, which is correct (same as TERGM ip-complete set).
# ---------------------------------------------------------------------------
h3_impute_vars <- c("log_gdppc", "log_pop", "v2x_polyarchy", "idealpointfp", "pta")
meta_h3 <- meta %>%
    group_by(iso3c) %>%
    arrange(year) %>%
    fill(all_of(intersect(h3_impute_vars, names(meta))), .direction = "downup") %>%
    ungroup() %>%
    mutate(
        cum_complainant = replace_na(cum_complainant, 0),
        cum_respondent  = replace_na(cum_respondent,  0)
    )

cat("\nH3 meta imputation (carry-forward only):\n")
cat("  idealpointfp NAs:", sum(is.na(meta$idealpointfp)),
    "->", sum(is.na(meta_h3$idealpointfp)), "\n")
cat("  log_gdppc    NAs:", sum(is.na(meta$log_gdppc)),
    "->", sum(is.na(meta_h3$log_gdppc)), "\n")
cat("  v2x_polyarchy NAs:", sum(is.na(meta$v2x_polyarchy)),
    "->", sum(is.na(meta_h3$v2x_polyarchy)), "\n")

# Join node-level controls from meta (complainant = exporter side)
meta_c_h3 <- meta_h3 %>%
    select(iso3c, year, log_gdppc, log_pop, v2x_polyarchy,
           idealpointfp, cum_complainant) %>%
    rename(exporter     = iso3c,
           log_gdppc_c  = log_gdppc,
           log_pop_c    = log_pop,
           democracy_c  = v2x_polyarchy,
           idealpoint_c = idealpointfp,
           log_cum_comp = cum_complainant)

meta_r_h3 <- meta_h3 %>%
    select(iso3c, year, log_gdppc, v2x_polyarchy, idealpointfp,
           cum_respondent) %>%
    rename(importer     = iso3c,
           log_gdppc_r  = log_gdppc,
           democracy_r  = v2x_polyarchy,
           idealpoint_r = idealpointfp,
           log_cum_resp = cum_respondent)

dyad_panel_h3 <- dyad_panel_h3 %>%
    left_join(meta_c_h3, by = c("exporter", "year")) %>%
    left_join(meta_r_h3, by = c("importer", "year")) %>%
    mutate(
        ip_distance   = abs(idealpoint_c - idealpoint_r),
        democracy_min = pmin(democracy_c, democracy_r, na.rm = TRUE),
        decade        = factor(floor(year / 10) * 10)
    )

# Missingness diagnostic after join
# M1 vars (no ip_distance): full sample
# M2/M3 vars (with ip_distance): ip-complete sample only, same as TERGM M2/M3
h3_vars_m1 <- c("atopally", "log_trade_c", "log_gdppc_c", "log_gdppc_r",
                "democracy_c", "log_cum_comp", "log_cum_resp")
h3_vars_m2 <- c(h3_vars_m1, "ip_distance")
cat("\nH3 panel missingness after imputed join:\n")
for (v in h3_vars_m2) {
    n_na <- sum(is.na(dyad_panel_h3[[v]]))
    cat(sprintf("  %-18s: %d NAs (%.2f%%)\n", v, n_na,
                100 * n_na / nrow(dyad_panel_h3)))
}
cat("  M1 complete cases (no ip_distance):",
    sum(complete.cases(dyad_panel_h3[h3_vars_m1])), "/", nrow(dyad_panel_h3), "\n")
cat("  M2/M3 complete cases (with ip_distance):",
    sum(complete.cases(dyad_panel_h3[h3_vars_m2])), "/", nrow(dyad_panel_h3), "\n")

# -----------------------------------------------------------------------------
# STEP 2: Three logistic models (glm + cluster-robust SEs by dyad)
#
# feglm with dyad FE drops all dyad-years where dispute is always 0
# (no within-dyad variation), excluding most non-dispute pairs.
# glm with decade FE retains all dyads as the natural counterfactual.
# Cluster-robust SEs via sandwich::vcovCL correct for within-dyad correlation.
# -----------------------------------------------------------------------------

# M1 — full sample (no ip_distance, mirrors TERGM M1)
m_h3_1_glm <- glm(
    dispute ~ atopally + log_trade_c +
        log_gdppc_c + log_gdppc_r +
        ip_distance + democracy_c +
        log_cum_comp + log_cum_resp +
        factor(year),
    data   = dyad_panel_h3,
    family = binomial()
)

m_h3_2_glm <- glm(
    dispute ~ atopally * log_trade_c +
        log_gdppc_c + log_gdppc_r +
        ip_distance + democracy_c +
        log_cum_comp + log_cum_resp +
        factor(year),
    data   = dyad_panel_h3,
    family = binomial()
)

m_h3_3_glm <- glm(
    dispute ~ atopally * log_trade_c +
        atopally * democracy_c +
        log_gdppc_c + log_gdppc_r +
        ip_distance + log_cum_comp + log_cum_resp +
        factor(year),
    data   = dyad_panel_h3,
    family = binomial()
)

clust_h3_1 <- coeftest(m_h3_1_glm,
                       vcov = vcovCL(m_h3_1_glm,
                                     cluster = ~dyad_id,
                                     data    = dyad_panel_h3))

clust_h3_2 <- coeftest(m_h3_2_glm,
                       vcov = vcovCL(m_h3_2_glm,
                                     cluster = ~dyad_id,
                                     data    = dyad_panel_h3))

clust_h3_3 <- coeftest(m_h3_3_glm,
                       vcov = vcovCL(m_h3_3_glm,
                                     cluster = ~dyad_id,
                                     data    = dyad_panel_h3))

modelsummary(
    list("M1 Main"    = m_h3_1_glm,
         "M2 H3 Core" = m_h3_2_glm,
         "M3 Mechan." = m_h3_3_glm),
    vcov  = list(vcovCL(m_h3_1_glm, cluster = ~dyad_id,
                        data = dyad_panel_h3),
                 vcovCL(m_h3_2_glm, cluster = ~dyad_id,
                        data = dyad_panel_h3),
                 vcovCL(m_h3_3_glm, cluster = ~dyad_id,
                        data = dyad_panel_h3)),
    stars   = c("*" = 0.05, "**" = 0.01, "***" = 0.001),
    gof_map = c("nobs", "logLik", "AIC", "BIC", "r.square")
)

# -----------------------------------------------------------------------------
# STEP 3: Output — tex table + modelsummary
# -----------------------------------------------------------------------------

coef_map_h3_out <- list(
    "atopally"             = "ATOP Alliance",
    "log_trade_c"          = "Bilateral Trade (centered)",
    "atopally:log_trade_c" = "Alliance × Trade",
    "atopally:democracy_c" = "Alliance × Democracy",
    "log_gdppc_c"          = "GDP/cap: Complainant",
    "log_gdppc_r"          = "GDP/cap: Respondent",
    "ip_distance"          = "UN Voting Distance",
    "democracy_c"          = "Complainant Democracy",
    "log_cum_comp"         = "Cumul. Complaints",
    "log_cum_resp"         = "Cumul. Respondent"
)

# Store vcov matrices (already computed above; reuse to avoid recalculation)
vcov_h3_1 <- vcovCL(m_h3_1_glm, cluster = ~ dyad_id, data = dyad_panel_h3)
vcov_h3_2 <- vcovCL(m_h3_2_glm, cluster = ~ dyad_id, data = dyad_panel_h3)
vcov_h3_3 <- vcovCL(m_h3_3_glm, cluster = ~ dyad_id, data = dyad_panel_h3)

modelsummary(
    list("(1) Baseline"     = m_h3_1_glm,
         "(2) +Interaction" = m_h3_2_glm,
         "(3) +Democracy"   = m_h3_3_glm),
    vcov     = list(vcov_h3_1, vcov_h3_2, vcov_h3_3),
    coef_map = coef_map_h3_out,
    coef_omit = "^factor\\(decade\\)",
    stars    = c("*" = 0.05, "**" = 0.01, "***" = 0.001),
    gof_map  = c("nobs", "logLik", "AIC", "BIC"),
    title    = "Alliance and WTO Dispute Initiation: Logit (H3)"
)

# =============================================================================
# H3 MARGINAL EFFECTS PLOT — atopally × log_trade_c (M3 final model)
#
# Two predicted-probability lines (ally vs non-ally) across the 5th–95th
# percentile of log bilateral trade. X-axis shows uncentered log_total_trade
# (more interpretable than the centered version used in the model).
# CIs via delta method on eta scale, then transformed to probability.
# =============================================================================

# Complete-case means for controls (matches M3 estimation sample)
m3_cc <- dyad_panel_h3[complete.cases(
    dyad_panel_h3[c("dispute", "atopally", "log_trade_c",
                    "log_gdppc_c", "log_gdppc_r", "ip_distance",
                    "democracy_c", "log_cum_comp", "log_cum_resp")]
), ]

trade_seq <- seq(
    quantile(dyad_panel_h3$log_trade_c, 0.05, na.rm = TRUE),
    quantile(dyad_panel_h3$log_trade_c, 0.95, na.rm = TRUE),
    length.out = 200
)

base_row <- list(
    log_gdppc_c  = mean(m3_cc$log_gdppc_c,  na.rm = TRUE),
    log_gdppc_r  = mean(m3_cc$log_gdppc_r,  na.rm = TRUE),
    ip_distance  = mean(m3_cc$ip_distance,   na.rm = TRUE),
    democracy_c  = mean(m3_cc$democracy_c,   na.rm = TRUE),
    log_cum_comp = mean(m3_cc$log_cum_comp,  na.rm = TRUE),
    log_cum_resp = mean(m3_cc$log_cum_resp,  na.rm = TRUE),
    decade       = factor(levels(dyad_panel_h3$decade)[1],
                          levels = levels(dyad_panel_h3$decade))
)

grid_ally   <- data.frame(atopally = 1, log_trade_c = trade_seq, base_row,
                           stringsAsFactors = FALSE)
grid_noally <- data.frame(atopally = 0, log_trade_c = trade_seq, base_row,
                           stringsAsFactors = FALSE)

# Design matrices (strip LHS so 'dispute' is not required)
fterms <- delete.response(terms(m_h3_3_glm))
X1 <- model.matrix(fterms, data = grid_ally,   xlev = m_h3_3_glm$xlevels)
X0 <- model.matrix(fterms, data = grid_noally, xlev = m_h3_3_glm$xlevels)

# Linear predictors, probabilities, and per-line delta-method CIs
eta1      <- drop(X1 %*% coef(m_h3_3_glm))
eta0      <- drop(X0 %*% coef(m_h3_3_glm))
se_eta1   <- sqrt(rowSums((X1 %*% vcov_h3_3) * X1))
se_eta0   <- sqrt(rowSums((X0 %*% vcov_h3_3) * X0))

pred_plot_h3 <- bind_rows(
    data.frame(
        log_trade_c = trade_seq,
        prob  = plogis(eta1),
        lower = plogis(eta1 - 1.96 * se_eta1),
        upper = plogis(eta1 + 1.96 * se_eta1),
        ally  = "Ally"
    ),
    data.frame(
        log_trade_c = trade_seq,
        prob  = plogis(eta0),
        lower = plogis(eta0 - 1.96 * se_eta0),
        upper = plogis(eta0 + 1.96 * se_eta0),
        ally  = "Non-Ally"
    )
) %>% mutate(ally = factor(ally, levels = c("Non-Ally", "Ally")))

p_h3_margins <- ggplot(pred_plot_h3,
    aes(x = log_trade_c, y = prob, color = ally, fill = ally)) +
    geom_ribbon(aes(ymin = lower, ymax = upper), alpha = 0.15, color = NA) +
    geom_line(linewidth = 0.9) +
    scale_color_manual(
        values = c("Non-Ally" = "#2166AC", "Ally" = "#D73027"), name = NULL) +
    scale_fill_manual(
        values = c("Non-Ally" = "#2166AC", "Ally" = "#D73027"), name = NULL) +
    scale_y_continuous(labels = scales::label_percent(accuracy = 0.001)) +
    labs(
        x = "Log Bilateral Trade (mean-centered)",
        y = "Predicted P(Dispute Initiation)"
    ) +
    theme_minimal(base_size = 11) +
    theme(
        legend.position  = "bottom",
        panel.grid.minor = element_blank()
    )

p_h3_margins

ggsave("Data/Output/h3_margins.pdf", p_h3_margins,
       width = 5, height = 4, device = cairo_pdf)
ggsave("Data/Output/h3_margins.png", p_h3_margins,
       width = 5, height = 4, dpi = 300)
cat("H3 marginal effects plot saved.\n")

# =============================================================================
# 4. H4: POLITICAL FRAMING INTENSITY (OLS)
#
# H4: Controlling for economic stakes, ally disputes exhibit similar or higher
#     political framing intensity compared to non-ally disputes.
#
# DV: severity_score (1–5 continuous, from LLM-RAG pipeline on Request for
#     Consultations). Higher = more politically aggressive / systemic framing.
#
# Prediction: atopally >= 0 (non-negative) — i.e., allies do NOT file softer
#             complaints even when economic stakes are held constant.
#
# Four nested OLS models with cluster-robust SEs (cluster = complainant):
#   H4.1: alliance + disputed-sector trade + decade FE  (minimal economic)
#   H4.2: + full economic controls (trade dep., bilateral trade, GDP/cap)
#   H4.3: + political/relational controls (UN voting, democracy, litigation exp.)
#   H4.4: + dispute type (product vs. policy case)
#
# Sample: C-R dyad-cases with non-missing severity_score, consultation_year <= 2024.
# =============================================================================

h4_data <- case_cr %>%
  dplyr::filter(!is.na(log_disp_trade),
                !is.na(atopally),
                consultation_year <= 2024) %>%
    mutate(disp_trade_share = disputed_trade_ij_t0 / (total_trade_cr + 1),
           log_disp_share = log(disp_trade_share + 0.001)
           )

cat("\nH4 sample:", nrow(h4_data), "C-R pairs\n")
cat("Ally pairs in H4:", sum(h4_data$atopally == 1), "\n")
cat("Severity mean (ally):",
    round(mean(h4_data$severity_score[h4_data$atopally == 1], na.rm = TRUE), 3), "\n")
cat("Severity mean (non-ally):",
    round(mean(h4_data$severity_score[h4_data$atopally == 0], na.rm = TRUE), 3), "\n")

# Nested OLS models: each model adds one conceptual block to the previous.
# M1 ⊂ M2 ⊂ M3 ⊂ M4; variable order within each formula follows M4.

# H4.1 — Core IVs only
lm_h4_1 <- lm(log_disp_trade ~
                  atopally +
                  severity_score +
                  decade,
              data = h4_data)

# H4.2 — + Economic controls (exp_dep_cr, GDP/cap)
lm_h4_2 <- lm(log_disp_trade ~
                  atopally +
                  severity_score +
                  exp_dep_cr +
                  log_gdppc_c +
                  log_gdppc_r +
                  decade,
              data = h4_data)

# H4.3 — + Political/relational controls (democracy, UN voting, litigation experience, third parties)
lm_h4_3 <- lm(log_disp_trade ~
                  atopally +
                  democracy_c +
                  severity_score +
                  exp_dep_cr +
                  log_gdppc_c +
                  log_gdppc_r +
                  ip_distance +
                  log_cum_comp +
                  log_cum_resp +
                  n_third_parties +
                  decade,
              data = h4_data)

# H4.4 — + Dispute type (product vs. policy case)
lm_h4_4 <- lm(log_disp_trade ~
                  atopally +
                  democracy_c +
                  severity_score +
                  exp_dep_cr +
                  log_gdppc_c +
                  log_gdppc_r +
                  ip_distance +
                  log_cum_comp +
                  log_cum_resp +
                  n_third_parties +
                  is_product_case +
                  decade,
              data = h4_data)

# Clustered SEs by complainant
clust_h4_1 <- coeftest(lm_h4_1, vcov = vcovCL(lm_h4_1, cluster = ~ iso3_c))
clust_h4_2 <- coeftest(lm_h4_2, vcov = vcovCL(lm_h4_2, cluster = ~ iso3_c))
clust_h4_3 <- coeftest(lm_h4_3, vcov = vcovCL(lm_h4_3, cluster = ~ iso3_c))
clust_h4_4 <- coeftest(lm_h4_4, vcov = vcovCL(lm_h4_4, cluster = ~ iso3_c))

cat("\n--- H4.1 (clustered SE) ---\n"); print(clust_h4_1)
cat("\n--- H4.2 (clustered SE) ---\n"); print(clust_h4_2)
cat("\n--- H4.3 (clustered SE) ---\n"); print(clust_h4_3)
cat("\n--- H4.4 (clustered SE) ---\n"); print(clust_h4_4)

add_rows_h4 <- tribble(
  ~term,            ~`(1) Core`, ~`(2) +Economic`, ~`(3) +Political`, ~`(4) Full`,
  "Other controls",  "No",       "Yes",            "Yes",             "Yes"
)

cat("\n====== H4: modelsummary (screen preview) ======\n")
modelsummary(
    list("(1) Core"       = lm_h4_1,
         "(2) +Economic"  = lm_h4_2,
         "(3) +Political" = lm_h4_3,
         "(4) Full"       = lm_h4_4),
    vcov     = list(vcovCL(lm_h4_1, cluster = ~ iso3_c),
                    vcovCL(lm_h4_2, cluster = ~ iso3_c),
                    vcovCL(lm_h4_3, cluster = ~ iso3_c),
                    vcovCL(lm_h4_4, cluster = ~ iso3_c)),
    coef_map  = coef_map_h4,
    add_rows  = add_rows_h4,
    stars    = c("*" = 0.05, "**" = 0.01, "***" = 0.001),
    gof_map  = c("nobs", "r.squared", "adj.r.squared"),
    title    = "Alliance and Bilateral Disputed Trade: OLS (H4)"
)

# =============================================================================
# 5. OUTPUT TABLES
# =============================================================================

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

# Post-process a texreg .tex file → xltabular format matching tergm_results.tex:
#   • Strips \begin{table}/\end{table} wrapper (xltabular is a longtable variant)
#   • Converts \begin{tabular}{spec} → \begin{xltabular}{\textwidth}{@{} X c c... @{}}
#   • Two-row header: (1)(2)... numbers row + model-name row
#   • \endfirsthead / \endhead (numbers only) / \endlastfoot structure
#   • Sig footnote hardcoded in \endlastfoot; any custom.note appended below table
post_process_tex <- function(filepath, arraystretch = 0.9, tabcolsep = "2pt",
                             other_controls = NULL) {
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
  toprule_idx   <- grep("^\\\\toprule",  lines)[1]
  first_midrule <- grep("^\\\\midrule",  lines)[1]
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

  # Insert "Other controls: No/Yes/..." row just before the inner \midrule
  # (the midrule that separates coefficient rows from GOF rows in body_rows)
  if (!is.null(other_controls)) {
    inner_mid <- which(body_rows == "\\midrule")
    if (length(inner_mid) > 0) {
      row_txt <- paste0("Other controls & ",
                        paste(other_controls, collapse = " & "), " \\\\")
      idx <- inner_mid[1]
      body_rows <- c(body_rows[seq_len(idx - 1)],
                     row_txt,
                     body_rows[idx:length(body_rows)])
    }
  }

  # ---- 6. Extra note from custom.note = "..." (texreg \tiny wrapper) ----
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

  # ---- Numbers row (appears in both headers; omitted for single-model tables) ----
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
    out <- c(out, sprintf("\\noindent \\normalsize \\textit{Notes:} %s", note_text))

  writeLines(out, filepath)
  invisible(filepath)
}

# --- Coefficient label maps ---

coef_map_h2 <- list(
  "atopally"        = "ATOP Alliance",
  "log_total_trade" = "Bilateral Trade",
  "gdppc_diff"      = "GDP/cap Gap",
  "log_gdppc_c"     = "GDP/cap: Complainant",
  "log_gdppc_r"     = "GDP/cap: Respondent",
  "ip_distance"     = "UN Voting Distance",
  "democracy_min"   = "Joint Democracy (min)",
  "pta_depth"       = "PTA Depth",
  "severity_score"  = "Dispute Severity",
  "log_cum_comp"    = "Cumul. Complaints",
  "log_cum_resp"    = "Cumul. Respondent",
  "n_third_parties" = "N Third Parties"
)

coef_map_h3 <- list(
  "atopally"             = "ATOP Alliance",
  "log_trade_c"          = "Bilateral Trade (centered)",
  "atopally:log_trade_c" = "Alliance × Trade",
  "atopally:democracy_c" = "Alliance × Democracy",
  "log_gdppc_c"          = "GDP/cap: Complainant",
  "log_gdppc_r"          = "GDP/cap: Respondent",
  "ip_distance"          = "UN Voting Distance",
  "democracy_c"          = "Complainant Democracy",
  "log_cum_comp"         = "Cumul. Complaints",
  "log_cum_resp"         = "Cumul. Respondent"
)

coef_map_h4 <- list(
  "atopally"        = "ATOP Alliance",
  "severity_score"  = "Dispute Severity",
  "exp_dep_cr"      = "Export Dependence",
  "log_cum_comp"    = "Cumul. Complaints",
  "log_cum_resp"    = "Cumul. Respondent",
  "is_product_case" = "Product Case"
)

# H3 clustered SE overrides (dyad-year logit, 3 models; GLM uses z-test → Pr(>|z|))
h3_ses <- list(
  clust_h3_1[, "Std. Error"],
  clust_h3_2[, "Std. Error"],
  clust_h3_3[, "Std. Error"]
)
h3_pvs <- list(
  clust_h3_1[, "Pr(>|z|)"],
  clust_h3_2[, "Pr(>|z|)"],
  clust_h3_3[, "Pr(>|z|)"]
)

# Helper: extract Cox robust into texreg object
extract_cox_robust <- function(mod) {
  s      <- summary(mod)
  coefs  <- s$coefficients[, "coef"]
  se_col <- if ("robust se" %in% colnames(s$coefficients)) "robust se" else "se(coef)"
  ses    <- s$coefficients[, se_col]
  pvs    <- s$coefficients[, ncol(s$coefficients)]
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

# ---------------------------------------------------------------------------
# Screen output
# ---------------------------------------------------------------------------

cat("\n====== H2: Ordered Logit (Primary) ======\n")
screenreg(
  list(tr_ol1, tr_ol2, tr_ol3, tr_ol4),
  custom.model.names = c("OL1 Baseline", "OL2 +Capacity",
                         "OL3 +Alignment", "OL4 +Severity"),
  custom.coef.map    = coef_map_h2,
  omit.coef          = "decade",
  digits             = 3,
  caption = "Ordered Logit: Alliance and WTO Dispute Escalation (H2)"
)

cat("\n====== H2: Cox PH (Robustness) ======\n")
screenreg(
  list(extract_cox_robust(cox_h2_1),
       extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3)),
  custom.model.names = c("Cox H2.1", "Cox H2.2", "Cox H2.3"),
  custom.coef.map    = coef_map_h2,
  digits             = 3,
  caption = "Cox PH: Alliance and Time to Panel Escalation (Robustness)"
)

cat("\n====== H3: Dyad-Year Logit — Dispute Initiation ======\n")
screenreg(
  list(m_h3_1_glm, m_h3_2_glm, m_h3_3_glm),
  override.se      = h3_ses,
  override.pvalues = h3_pvs,
  custom.model.names = c("M1 Baseline", "M2 +Interact", "M3 +DemInteract"),
  custom.coef.map  = coef_map_h3,
  omit.coef        = "factor\\(decade\\)",
  digits           = 3,
  caption = "Logit: Alliance and WTO Dispute Initiation (H3)"
)

# ---------------------------------------------------------------------------
# LaTeX: H2 ordered logit (primary)
# ---------------------------------------------------------------------------
dir.create("Data/Output", showWarnings = FALSE, recursive = TRUE)

texreg(
  list(tr_ol1, tr_ol2, tr_ol3, tr_ol4),
  file               = "Data/Output/h2_ordlogit_results.tex",
  custom.model.names = c("Baseline", "+Node Attrs", "+UN Voting", "+Severity"),
  custom.coef.map    = coef_map_h2,
  omit.coef          = "decade",
  digits             = 3,
  caption            = "Alliance and WTO Dispute Escalation: Ordered Logit (H2)",
  caption.above      = TRUE,
  label              = "tab:h2_ordlogit",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h2_ordlogit_results.tex")
cat("H2 ordinal logit LaTeX saved.\n")

# ---------------------------------------------------------------------------
# LaTeX: H2 Cox robustness
# ---------------------------------------------------------------------------
texreg(
  list(extract_cox_robust(cox_h2_1),
       extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3)),
  file               = "Data/Output/h2_cox_results.tex",
  custom.model.names = c("Baseline", "+Node Attrs", "+Full"),
  custom.coef.map    = coef_map_h2,
  digits             = 3,
  caption            = "Alliance and Time to Panel Escalation: Cox PH Robustness (H2)",
  caption.above      = TRUE,
  label              = "tab:h2_cox",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h2_cox_results.tex")
cat("H2 Cox robustness LaTeX saved.\n")

# ---------------------------------------------------------------------------
# LaTeX: H3 Logit (appendix)
# ---------------------------------------------------------------------------
texreg(
  list(m_h3_1_glm, m_h3_2_glm, m_h3_3_glm),
  override.se        = h3_ses,
  override.pvalues   = h3_pvs,
  file               = "Data/Output/h3_logit_results.tex",
  custom.model.names = c("Baseline", "+Interact", "+DemInteract"),
  custom.coef.map    = coef_map_h3,
  omit.coef          = "factor\\(decade\\)",
  digits             = 3,
  caption            = "Alliance and WTO Dispute Initiation: Dyad-Year Logit (H3)",
  caption.above      = TRUE,
  label              = "tab:h3_logit",
  use.packages       = FALSE,
  booktabs           = TRUE,
  dcolumn            = FALSE,
  custom.note        = "Cluster-robust SE by dyad."
)
post_process_tex("Data/Output/h3_logit_results.tex")
cat("H3 logit LaTeX saved.\n")

# ---------------------------------------------------------------------------
# H4 clustered SE overrides
# ---------------------------------------------------------------------------
h4_ses <- list(
  clust_h4_1[, "Std. Error"],
  clust_h4_2[, "Std. Error"],
  clust_h4_3[, "Std. Error"],
  clust_h4_4[, "Std. Error"]
)
h4_pvs <- list(
  clust_h4_1[, "Pr(>|t|)"],
  clust_h4_2[, "Pr(>|t|)"],
  clust_h4_3[, "Pr(>|t|)"],
  clust_h4_4[, "Pr(>|t|)"]
)

cat("\n====== H4: OLS — Bilateral Disputed Trade ======\n")
screenreg(
  list(lm_h4_1, lm_h4_2, lm_h4_3, lm_h4_4),
  override.se        = h4_ses,
  override.pvalues   = h4_pvs,
  custom.model.names = c("H4.1 Core", "H4.2 +Economic",
                         "H4.3 +Political", "H4.4 Full"),
  custom.coef.map    = coef_map_h4,
  omit.coef          = "democracy_c|log_gdppc|ip_distance|n_third_parties|decade",
  digits             = 3,
  caption = "OLS: Alliance and Bilateral Disputed Trade (H4)"
)

# ---------------------------------------------------------------------------
# LaTeX: H4 OLS
# ---------------------------------------------------------------------------
texreg(
  list(lm_h4_1, lm_h4_2, lm_h4_3, lm_h4_4),
  override.se        = h4_ses,
  override.pvalues   = h4_pvs,
  file               = "Data/Output/h4_ols_results.tex",
  custom.model.names = c("Core IVs", "+Economic", "+Political", "Full"),
  custom.coef.map    = coef_map_h4,
  omit.coef          = "democracy_c|log_gdppc|ip_distance|n_third_parties|decade",
  digits             = 3,
  caption            = "Alliance and Bilateral Disputed Trade: OLS (H4)",
  caption.above      = TRUE,
  label              = "tab:h4_ols",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h4_ols_results.tex",
                 other_controls = c("No", "Yes", "Yes", "Yes"))
cat("H4 OLS LaTeX saved.\n")

modelsummary(
    list("(1) Core"       = lm_h4_1,
         "(2) +Economic"  = lm_h4_2,
         "(3) +Political" = lm_h4_3,
         "(4) Full"       = lm_h4_4),
    vcov     = list(vcovCL(lm_h4_1, cluster = ~ iso3_c),
                    vcovCL(lm_h4_2, cluster = ~ iso3_c),
                    vcovCL(lm_h4_3, cluster = ~ iso3_c),
                    vcovCL(lm_h4_4, cluster = ~ iso3_c)),
    coef_map  = coef_map_h4,
    add_rows  = add_rows_h4,
    stars    = c("*" = 0.05, "**" = 0.01, "***" = 0.001),
    gof_map  = c("nobs", "r.squared", "adj.r.squared"),
    title    = "Alliance and Bilateral Disputed Trade: OLS (H4)"
)

# ===========================================================================
# 6. MAIN-IV PAPER / SLIDES TABLES
#    Key IVs only — full-control versions above serve as appendix tables.
# ===========================================================================

# ---- Main IV coef maps ----
coef_map_h2_main <- list(
  "atopally"        = "ATOP Alliance",
  "log_total_trade" = "Bilateral Trade",
  "ip_distance"     = "UN Voting Distance",
  "severity_score"  = "Dispute Severity",
  "n_third_parties" = "N Third Parties"
)

coef_map_h3_main <- list(
  "atopally"             = "ATOP Alliance",
  "log_trade_c"          = "Bilateral Trade (centered)",
  "atopally:log_trade_c" = "Alliance × Trade",
  "atopally:democracy_c" = "Alliance × Democracy",
  "ip_distance"          = "UN Voting Distance",
  "democracy_c"          = "Complainant Democracy"
)

coef_map_h4_main <- list(
  "atopally"        = "ATOP Alliance",
  "severity_score"  = "Dispute Severity",
  "exp_dep_cr"      = "Export Dependence",
  "log_cum_comp"    = "Cumul. Complaints",
  "log_cum_resp"    = "Cumul. Respondent",
  "is_product_case" = "Product Case"
)

# ---- H2 ordlogit: main paper table ----
texreg(
  list(tr_ol1, tr_ol2, tr_ol3, tr_ol4),
  file               = "Data/Output/h2_ordlogit_main.tex",
  custom.model.names = c("Baseline", "+Node Attrs", "+UN Voting", "+Severity"),
  custom.coef.map    = coef_map_h2_main,
  omit.coef          = "decade",
  digits             = 3,
  caption            = "Alliance and WTO Dispute Escalation: Ordered Logit (H2)",
  caption.above      = TRUE,
  label              = "tab:h2_ordlogit",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h2_ordlogit_main.tex")
cat("H2 ordlogit main table saved.\n")

# ---- H2 Cox: main paper table ----
texreg(
  list(extract_cox_robust(cox_h2_1),
       extract_cox_robust(cox_h2_2),
       extract_cox_robust(cox_h2_3)),
  file               = "Data/Output/h2_cox_main.tex",
  custom.model.names = c("Baseline", "+Node Attrs", "+Full"),
  custom.coef.map    = coef_map_h2_main,
  digits             = 3,
  caption            = "Alliance and Time to Panel Escalation: Cox PH (H2 Robustness)",
  caption.above      = TRUE,
  label              = "tab:h2_cox_main",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h2_cox_main.tex")
cat("H2 Cox main table saved.\n")

# ---- H3 logit: main paper table ----
texreg(
  list(m_h3_1_glm, m_h3_2_glm, m_h3_3_glm),
  override.se        = h3_ses,
  override.pvalues   = h3_pvs,
  file               = "Data/Output/h3_logit_main.tex",
  custom.model.names = c("Baseline", "+Interact", "+DemInteract"),
  custom.coef.map    = coef_map_h3_main,
  omit.coef          = "factor\\(decade\\)",
  digits             = 3,
  caption            = "Alliance and WTO Dispute Initiation: Logit (H3)",
  caption.above      = TRUE,
  label              = "tab:h3_logit_main",
  use.packages       = FALSE,
  booktabs           = TRUE,
  dcolumn            = FALSE,
  custom.note        = ""
)
post_process_tex("Data/Output/h3_logit_main.tex")
cat("H3 logit main table saved.\n")

# ---- H4 OLS: main paper table ----
texreg(
  list(lm_h4_1, lm_h4_2, lm_h4_3, lm_h4_4),
  override.se        = h4_ses,
  override.pvalues   = h4_pvs,
  file               = "Data/Output/h4_ols_main.tex",
  custom.model.names = c("Core IVs", "+Economic", "+Political", "Full"),
  custom.coef.map    = coef_map_h4_main,
  omit.coef          = "democracy_c|log_gdppc|ip_distance|n_third_parties|decade",
  digits             = 3,
  caption            = "Alliance and Bilateral Disputed Trade: OLS (H4)",
  caption.above      = TRUE,
  label              = "tab:h4_ols",
  use.packages       = FALSE,
  booktabs           = TRUE,
  custom.note        = ""
)
post_process_tex("Data/Output/h4_ols_main.tex",
                 other_controls = c("No", "Yes", "Yes", "Yes"))
cat("H4 OLS main table saved.\n")

# ---------------------------------------------------------------------------
# HTML: combined H2 + H3 summary
# ---------------------------------------------------------------------------
htmlreg(
  list(tr_ol1, tr_ol2, tr_ol3, tr_ol4,
       m_h3_1_glm, m_h3_2_glm, m_h3_3_glm),
  override.se      = c(list(NULL, NULL, NULL, NULL), h3_ses),
  override.pvalues = c(list(NULL, NULL, NULL, NULL), h3_pvs),
  file               = "Data/Output/h2_h3_results.html",
  custom.model.names = c("H2(1)", "H2(2)", "H2(3)", "H2(4)",
                         "H3(1)", "H3(2)", "H3(3)"),
  custom.coef.map    = c(coef_map_h2,
                         coef_map_h3[!names(coef_map_h3) %in% names(coef_map_h2)]),
  omit.coef          = "factor\\(decade\\)",
  digits             = 3,
  caption            = "Alliance Effects on WTO Dispute Behavior (H2 & H3)"
)
cat("HTML saved to Data/Output/h2_h3_results.html\n")

cat("\n=== Done ===\n")
