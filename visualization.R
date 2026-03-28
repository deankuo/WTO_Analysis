###############################################################################
# WTO Dispute Analysis — Visualization
# Paper: "More Trade, More Dispute? Measuring Alliance Effect of WTO Conflict"
###############################################################################

suppressPackageStartupMessages({
  library(tidyverse)
  library(patchwork)
  library(scales)
  library(jsonlite)
})

dir.create("./Graph", showWarnings = FALSE)

# ---------------------------------------------------------------------------
# Common theme
# ---------------------------------------------------------------------------
theme_wto <- function(base_size = 14) {
  theme_minimal(base_size = base_size) %+replace%
    theme(
      plot.title         = element_text(face = "bold", size = base_size + 2,
                                        hjust = 0.5, margin = margin(b = 8)),
      axis.title         = element_text(face = "bold", size = base_size),
      axis.title.x       = element_text(margin = margin(t = 8)),
      axis.title.y       = element_text(margin = margin(r = 8)),
      axis.text          = element_text(color = "grey20"),
      panel.grid.minor   = element_blank(),
      panel.grid.major.x = element_blank(),
      panel.grid.major.y = element_line(color = "grey90", linewidth = 0.4),
      plot.background    = element_rect(fill = "white", color = NA),
      panel.background   = element_rect(fill = "white", color = NA),
      plot.margin        = margin(12, 14, 12, 12)
    )
}

CLR_BLUE   <- "#2C4770"
CLR_RED    <- "#B03A2E"
CLR_GREEN  <- "#1A7A4A"
CLR_AMBER  <- "#B7770D"
CLR_TEAL   <- "#148F77"

# =============================================================================
# 1. DATA LOADING
# =============================================================================

df <- read.csv("./Data/wto_cases_v2.csv", stringsAsFactors = FALSE) %>%
  mutate(
    # Harmonise country names
    across(c(complainant, respondent, third_parties),
           ~ str_replace_all(.x, "European Communities", "European Union")),
    across(c(complainant, respondent, third_parties),
           ~ str_replace_all(.x, "Korea, Republic of",   "South Korea")),
    # Parse consultation year
    consult_date = coalesce(
      suppressWarnings(as.Date(consultations_requested, format = "%d-%b-%y")),
      suppressWarnings(as.Date(consultations_requested, format = "%d %B %Y"))
    ),
    consult_year = as.integer(format(consult_date, "%Y"))
  )

# =============================================================================
# 2. US WTO ACTIVITY (4-panel)
# =============================================================================

target_country <- "United States"

df_us <- df %>%
  mutate(is_us_tp = str_detect(replace_na(third_parties, ""),
                               fixed(target_country, ignore_case = TRUE)))

data_us1 <- df_us %>% filter(complainant == target_country) %>%
  count(respondent) %>% slice_max(n, n = 7, with_ties = FALSE)
data_us2 <- df_us %>% filter(respondent == target_country) %>%
  count(complainant) %>% slice_max(n, n = 7, with_ties = FALSE)
data_us3 <- df_us %>% filter(is_us_tp) %>%
  count(respondent) %>% slice_max(n, n = 7, with_ties = FALSE)
data_us4 <- df_us %>% filter(is_us_tp) %>%
  count(complainant) %>% slice_max(n, n = 7, with_ties = FALSE)

make_us_panel <- function(data, x_var, title, fill_color) {
  data[[x_var]] <- factor(data[[x_var]], levels = rev(data[[x_var]]))
  ggplot(data, aes(x = n, y = .data[[x_var]])) +
    geom_col(fill = fill_color, width = 0.7) +
    geom_text(aes(label = n), hjust = -0.25, size = 3.8, color = "grey25") +
    scale_x_continuous(expand = expansion(mult = c(0, 0.2))) +
    labs(title = title, x = "Number of Cases", y = NULL) +
    theme_wto(base_size = 13) +
    theme(
      plot.title  = element_text(size = 12, face = "bold", hjust = 0.5,
                                 margin = margin(b = 4)),
      axis.text.y = element_text(size = 11),
      plot.margin = margin(8, 10, 8, 8)
    )
}

us_p1 <- make_us_panel(data_us1, "respondent",
                       "U.S. as Complainant\n(Top 7 Respondents)",  CLR_BLUE)
us_p2 <- make_us_panel(data_us2, "complainant",
                       "U.S. as Respondent\n(Top 7 Complainants)",  CLR_RED)
us_p3 <- make_us_panel(data_us3, "respondent",
                       "U.S. as Third Party\n(Top 7 Respondents)",  CLR_GREEN)
us_p4 <- make_us_panel(data_us4, "complainant",
                       "U.S. as Third Party\n(Top 7 Complainants)", CLR_AMBER)

us_combined <- (us_p1 | us_p2) / (us_p3 | us_p4) +
  plot_annotation(
    # title = "United States WTO Dispute Activity",
    theme = theme(
      plot.title      = element_text(size = 16, face = "bold", hjust = 0.5,
                                     margin = margin(b = 8)),
      plot.background = element_rect(fill = "white", color = NA)
    )
  ) +
  plot_layout(widths = c(1, 1), heights = c(1, 1))

ggsave("./Graph/us_wto_activity.png", us_combined,
       width = 12, height = 9, dpi = 300, bg = "white")
print(us_combined)

# =============================================================================
# 3. DOCUMENT TYPE DISTRIBUTION
# =============================================================================

doc_label_map <- c(
  "Communication"                          = "Communication",
  "Request_To_Join_Consultations"          = "Request to Join Consultations",
  "Status_Report"                          = "Status Report",
  "Addendum"                               = "Addendum",
  "Report_Of_Panel"                        = "Panel Report",
  "Request_For_Consultations"              = "Request for Consultations",
  "Request_For_Establishment_Of_Panel"     = "Request for Panel Establishment",
  "Note_By_Secretariat"                    = "Secretariat Note",
  "Report_Of_Appellate_Body"              = "Appellate Body Report",
  "Notification_Of_Appeal"                = "Notice of Appeal",
  "Agreement_Art_21_3"                    = "Art. 21.3 Agreement",
  "Working_Procedures"                    = "Working Procedures",
  "Appellate_Body_Report_And_Panel_Report" = "AB & Panel Report",
  "Recourse"                              = "Recourse",
  "Understanding"                         = "Understanding"
)

doc_df <- fromJSON("./Data/WTO/rename_manifest_full.json")

doc_plot_data <- doc_df %>%
  count(type, name = "n") %>%
  arrange(desc(n)) %>%
  slice_head(n = 15) %>%
  mutate(
    label = coalesce(doc_label_map[type], str_replace_all(type, "_", " ")),
    label = factor(label, levels = rev(label))
  )

doc_plot <- ggplot(doc_plot_data, aes(x = n, y = label)) +
  geom_col(fill = CLR_BLUE, width = 0.75) +
  geom_text(aes(label = comma(n)), hjust = -0.2, size = 3.8, color = "grey20") +
  scale_x_continuous(labels = comma, expand = expansion(mult = c(0, 0.15))) +
  labs(
    # title = "WTO DSB Document Types (Top 15)",
    x     = "Number of Documents",
    y     = "Doc Type"
  ) +
  theme_wto(base_size = 14) +
  theme(
    panel.grid.major.x = element_line(color = "grey90", linewidth = 0.4),
    panel.grid.major.y = element_blank(),
    axis.text.y        = element_text(size = 12)
  )

ggsave("./Graph/document_distribution.png", doc_plot,
       width = 10, height = 7, dpi = 300, bg = "white")
print(doc_plot)

# =============================================================================
# 4. DISPUTE STAGE DISTRIBUTION  (horizontal bars — avoids x-label overlap)
# =============================================================================

stage_data <- tribble(
  ~stage,                  ~pct,  ~ord,
  "Consultation",           30.7,    1,
  "Mutually Agreed",        18.5,    2,
  "Panel",                  11.6,    3,
  "Appellate Body",         11.5,    4,
  "Implementation",         23.8,    5,
  "Retaliation",             3.9,    6
) %>%
  mutate(stage = factor(stage, levels = rev(stage[order(ord)])))

stage_plot <- ggplot(stage_data, aes(x = pct, y = stage)) +
  geom_col(fill = CLR_BLUE, width = 0.65) +
  geom_text(aes(label = paste0(pct, "%")),
            hjust = -0.25, size = 4.5, color = CLR_BLUE, fontface = "bold") +
  scale_x_continuous(
    limits = c(0, 36),
    breaks = seq(0, 35, 5),
    expand = expansion(mult = c(0, 0.05)),
    labels = function(x) paste0(x, "%")
  ) +
  labs(
    # title = "WTO Disputes by Procedural Stage",
    x     = "Share of Cases",
    y     = NULL
  ) +
  theme_wto(base_size = 14) +
  theme(
    panel.grid.major.x = element_line(color = "grey90", linewidth = 0.4),
    panel.grid.major.y = element_blank(),
    axis.text.y        = element_text(size = 13)
  )

ggsave("./Graph/dispute_stage_distribution.png", stage_plot,
       width = 8, height = 5, dpi = 300, bg = "white")
print(stage_plot)

# =============================================================================
# 5. ANNUAL WTO DISPUTE TRENDS
# =============================================================================

annual_data <- df %>%
  filter(!is.na(consult_year), consult_year >= 1995, consult_year <= 2026) %>%
  count(consult_year, name = "n_cases")

trend_plot <- ggplot(annual_data, aes(x = consult_year, y = n_cases)) +
  geom_area(fill = CLR_BLUE, alpha = 0.12) +
  geom_line(color = CLR_BLUE, linewidth = 1.1) +
  geom_point(color = CLR_BLUE, size = 2.2, fill = "white",
             shape = 21, stroke = 1.3) +
  scale_x_continuous(breaks = seq(1995, 2024, 5)) +
  scale_y_continuous(breaks = seq(0, 60, 10),
                     expand = expansion(mult = c(0, 0.08))) +
  labs(
    #title = "Annual WTO Dispute Initiatives",
    x     = "Year",
    y     = "Number of Cases"
  ) +
  theme_wto(base_size = 14) +
  theme(panel.grid.major.x = element_line(color = "grey93", linewidth = 0.3))

ggsave("./Graph/annual_dispute_trends.png", trend_plot,
       width = 10, height = 6, dpi = 300, bg = "white")
print(trend_plot)

# =============================================================================
# 6. TOP WTO LITIGANTS
# =============================================================================

top_c <- df %>%
  filter(!is.na(complainant), complainant != "") %>%
  count(complainant, name = "n") %>%
  slice_max(n, n = 12, with_ties = FALSE) %>%
  mutate(country = fct_reorder(complainant, n))

top_r <- df %>%
  filter(!is.na(respondent), respondent != "") %>%
  count(respondent, name = "n") %>%
  slice_max(n, n = 12, with_ties = FALSE) %>%
  mutate(country = fct_reorder(respondent, n))

litig_c <- ggplot(top_c, aes(x = n, y = country)) +
  geom_col(fill = CLR_BLUE, width = 0.7) +
  geom_text(aes(label = n), hjust = -0.2, size = 3.8, color = "grey20") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.2))) +
  labs(title = "Top 12 Complainants", x = "Cases Filed", y = NULL) +
  theme_wto(base_size = 13) +
  theme(plot.title  = element_text(size = 13, hjust = 0.5),
        axis.text.y = element_text(size = 11))

litig_r <- ggplot(top_r, aes(x = n, y = country)) +
  geom_col(fill = CLR_RED, width = 0.7) +
  geom_text(aes(label = n), hjust = -0.2, size = 3.8, color = "grey20") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.2))) +
  labs(title = "Top 12 Respondents", x = "Cases Faced", y = NULL) +
  theme_wto(base_size = 13) +
  theme(plot.title  = element_text(size = 13, hjust = 0.5),
        axis.text.y = element_text(size = 11))

litig_combined <- (litig_c | litig_r) +
  plot_annotation(
    title = "Most Active WTO Litigants, 1995–2024",
    theme = theme(
      plot.title      = element_text(size = 16, face = "bold", hjust = 0.5,
                                     margin = margin(b = 8)),
      plot.background = element_rect(fill = "white", color = NA)
    )
  )

ggsave("./Graph/top_litigants.png", litig_combined,
       width = 13, height = 7, dpi = 300, bg = "white")
print(litig_combined)

# =============================================================================
# 7. ALLIANCE vs NON-ALLIANCE: ECONOMIC STAKES + ESCALATION RATE
# =============================================================================

dyadic_cr  <- tryCatch(
  read.csv("Data/wto_dyadic_enriched.csv", stringsAsFactors = FALSE),
  error = function(e) NULL
)
trade_ally <- tryCatch(
  read.csv("Data/bilateral_trade_wto.csv", stringsAsFactors = FALSE) %>%
    select(exporter, importer, year, atopally),
  error = function(e) NULL
)

if (!is.null(dyadic_cr) && !is.null(trade_ally)) {

  cr_ally <- dyadic_cr %>%
    filter(relationship == "complainant-respondent") %>%
    rename(iso3_c = iso3_1, iso3_r = iso3_2) %>%
    left_join(trade_ally,
              by = c("iso3_c" = "exporter", "iso3_r" = "importer",
                     "consultation_year" = "year")) %>%
    left_join(
      trade_ally %>% rename(atopally_rev = atopally),
      by = c("iso3_c" = "importer", "iso3_r" = "exporter",
             "consultation_year" = "year")
    ) %>%
    mutate(
      atopally       = coalesce(atopally, atopally_rev),
      log_disp_trade = log(replace_na(disputed_trade_ij_t0, 0) + 1),
      ally_label     = case_when(atopally == 1 ~ "Allies",
                                 atopally == 0 ~ "Non-Allies",
                                 TRUE ~ NA_character_)
    ) %>%
    filter(!is.na(ally_label))

  # --- 7a. Economic stakes (H3 motivation) ---
  ally_n <- cr_ally %>% count(ally_label)

  stakes_plot <- ggplot(cr_ally, aes(x = ally_label, y = log_disp_trade,
                                     fill = ally_label)) +
    geom_violin(alpha = 0.3, color = NA, trim = TRUE) +
    geom_boxplot(width = 0.25, outlier.size = 0.8, outlier.alpha = 0.4,
                 color = "grey30") +
    geom_text(data = ally_n,
              aes(x = ally_label, y = -0.5, label = paste0("n = ", n)),
              inherit.aes = FALSE, size = 3.8, color = "grey40") +
    scale_fill_manual(values = c("Allies" = CLR_BLUE, "Non-Allies" = CLR_RED),
                      guide = "none") +
    scale_y_continuous(breaks = seq(0, 25, 5)) +
    labs(
      title = "Disputed Trade by Alliance Status",
      x     = NULL,
      y     = expression(log(Disputed~Trade[t[0]] + 1))
    ) +
    theme_wto(base_size = 14) +
    theme(panel.grid.major.x = element_blank())

  ggsave("./Graph/alliance_economic_stakes.png", stakes_plot,
         width = 7, height = 6, dpi = 300, bg = "white")
  print(stakes_plot)

  # --- 7b. Panel escalation rate (H2 motivation) ---
  esc_data <- cr_ally %>%
    mutate(reached_panel = as.integer(!is.na(panel_established) &
                                        panel_established != "")) %>%
    group_by(ally_label) %>%
    summarise(n = n(), n_panel = sum(reached_panel, na.rm = TRUE),
              pct_panel = mean(reached_panel, na.rm = TRUE) * 100,
              .groups = "drop")

  esc_plot <- ggplot(esc_data,
                     aes(x = ally_label, y = pct_panel, fill = ally_label)) +
    geom_col(width = 0.5, alpha = 0.9) +
    geom_text(aes(label = sprintf("%.1f%%", pct_panel)),
              vjust = -0.5, size = 4.5, fontface = "bold", color = "grey15") +
    geom_text(aes(label = paste0("n = ", n)),
              y = 2, size = 3.5, color = "white", fontface = "bold") +
    scale_fill_manual(values = c("Allies" = CLR_BLUE, "Non-Allies" = CLR_RED),
                      guide = "none") +
    scale_y_continuous(limits = c(0, 80),
                       breaks = seq(0, 70, 10),
                       labels = function(x) paste0(x, "%"),
                       expand = expansion(mult = c(0, 0.1))) +
    labs(
      title = "Panel Escalation Rate by Alliance Status",
      x     = NULL,
      y     = "Cases Reaching Panel (%)"
    ) +
    theme_wto(base_size = 14) +
    theme(panel.grid.major.x = element_blank())

  ggsave("./Graph/alliance_escalation_rate.png", esc_plot,
         width = 6, height = 6, dpi = 300, bg = "white")
  print(esc_plot)

} else {
  message("Skipping alliance plots: required data files not found.")
}

# =============================================================================
# 8. SEVERITY SCORE DISTRIBUTION
# =============================================================================

sev_path <- "Data/Output/severity_scores_raw.csv"

if (file.exists(sev_path)) {

  sev_df <- read.csv(sev_path, stringsAsFactors = FALSE)

  # Join case_type if missing
  if (!"case_type" %in% names(sev_df) &&
      file.exists("Data/wto_dyadic_enriched.csv")) {
    ct <- read.csv("Data/wto_dyadic_enriched.csv", stringsAsFactors = FALSE) %>%
      filter(relationship == "complainant-respondent") %>%
      select(case_id, case_type) %>% distinct()
    sev_df <- left_join(sev_df, ct, by = "case_id")
  }

  dim_labels <- c(
    rhetorical_aggressiveness = "Rhetorical Aggressiveness",
    systemic_reach            = "Systemic Reach",
    escalation_ultimatum      = "Escalation Ultimatum",
    domestic_victimhood       = "Domestic Victimhood"
  )

  sev_long <- sev_df %>%
    select(case_id, any_of(names(dim_labels))) %>%
    pivot_longer(cols = any_of(names(dim_labels)),
                 names_to = "dimension", values_to = "score") %>%
    filter(!is.na(score)) %>%
    mutate(dim_label = factor(dim_labels[dimension], levels = dim_labels))

  sev_plot <- ggplot(sev_long, aes(x = score, fill = dimension)) +
    geom_histogram(binwidth = 0.5, color = "white", linewidth = 0.3,
                   boundary = 0.75) +
    facet_wrap(~ dim_label, nrow = 1) +
    scale_x_continuous(breaks = 1:5, limits = c(0.5, 5.5)) +
    scale_fill_manual(
      values = c(rhetorical_aggressiveness = CLR_BLUE,
                 systemic_reach            = CLR_RED,
                 escalation_ultimatum      = CLR_GREEN,
                 domestic_victimhood       = CLR_AMBER),
      guide  = "none"
    ) +
    labs(
      title = "Distribution of Consultation Severity Dimensions",
      x     = "Score (1–5)",
      y     = "Number of Cases"
    ) +
    theme_wto(base_size = 13) +
    theme(
      strip.text         = element_text(size = 11, face = "bold"),
      panel.grid.major.x = element_blank(),
      panel.spacing      = unit(0.8, "lines")
    )

  # Composite score
  comp_plot <- ggplot(sev_df %>% filter(!is.na(severity_score)),
                      aes(x = severity_score)) +
    geom_histogram(aes(y = after_stat(density)), binwidth = 0.25,
                   fill = CLR_BLUE, alpha = 0.7, color = "white") +
    geom_density(color = CLR_RED, linewidth = 1, adjust = 1.5) +
    geom_vline(xintercept = mean(sev_df$severity_score, na.rm = TRUE),
               linetype = "dashed", color = CLR_AMBER, linewidth = 0.9) +
    scale_x_continuous(breaks = 1:5, limits = c(0.75, 5.25)) +
    labs(
      # title = "Composite Severity Score Distribution",
      x     = "Composite Severity (1–5)",
      y     = "Density"
    ) +
    theme_wto(base_size = 14)

  ggsave("./Graph/severity_dimensions.png",  sev_plot,
         width = 13, height = 5, dpi = 300, bg = "white")
  ggsave("./Graph/severity_composite.png",   comp_plot,
         width = 7,  height = 5, dpi = 300, bg = "white")
  print(sev_plot)
  print(comp_plot)

} else {
  message("Skipping severity plots: 'Data/Output/severity_scores_raw.csv' not found.")
}

# =============================================================================
# 9. HS SECTION DISTRIBUTION
# =============================================================================

hs_path <- "Data/Output/case_section_expanded.csv"

if (file.exists(hs_path)) {

  hs_names <- c(
     "1" = "Animals & Products",   "2" = "Vegetable Products",
     "3" = "Fats & Oils",          "4" = "Food, Bev. & Tobacco",
     "5" = "Mineral Products",     "6" = "Chemicals",
     "7" = "Plastics & Rubber",    "8" = "Leather & Hides",
     "9" = "Wood & Paper",        "10" = "Textiles & Apparel",
    "11" = "Footwear",            "12" = "Stone & Glass",
    "13" = "Precious Metals",     "14" = "Base Metals",
    "15" = "Machinery & Electronics",
    "16" = "Transport Equipment", "17" = "Instruments",
    "18" = "Arms & Ammunition",   "19" = "Misc. Manufactures",
    "20" = "Art & Antiques",      "21" = "Horizontal Policy"
  )

  hs_df <- read.csv(hs_path, stringsAsFactors = FALSE) %>%
    mutate(
      hs_sec   = as.character(hs_section),
      sec_name = coalesce(hs_names[hs_sec], paste0("Section ", hs_sec))
    ) %>%
    count(sec_name, name = "n_cases") %>%
    mutate(sec_name = fct_reorder(sec_name, n_cases))

  hs_plot <- ggplot(hs_df, aes(x = n_cases, y = sec_name)) +
    geom_col(fill = CLR_TEAL, width = 0.75, alpha = 0.9) +
    geom_text(aes(label = n_cases), hjust = -0.2, size = 3.5, color = "grey20") +
    scale_x_continuous(expand = expansion(mult = c(0, 0.18))) +
    labs(
      title = "WTO Disputes by HS Trade Section",
      x     = "Number of Case-Section Observations",
      y     = NULL
    ) +
    theme_wto(base_size = 13) +
    theme(
      panel.grid.major.x = element_line(color = "grey90", linewidth = 0.4),
      panel.grid.major.y = element_blank(),
      axis.text.y        = element_text(size = 11.5)
    )

  ggsave("./Graph/hs_section_distribution.png", hs_plot,
         width = 10, height = 8, dpi = 300, bg = "white")
  print(hs_plot)

} else {
  message("Skipping HS section plot: 'Data/Output/case_section_expanded.csv' not found.")
}

cat("\n=== All plots saved to ./Graph/ ===\n")
