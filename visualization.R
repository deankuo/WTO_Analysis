# This script is for visualization for the paper "More Trade, More Dispute? Measuring Alliance Effect of WTO Conflict
library(tidyverse)
library(ggplot2)
library(stringr)
library(patchwork)
library(haven)

df <- read.csv("./Data/wto_cases_v2.csv")
target_country <- "United States"
df <- df %>%
    mutate(is_us_tp = str_detect(third_parties, fixed(target_country, ignore_case = TRUE))) %>%
    replace_na(list(is_us_tp = FALSE))


# Top 7 Respondents when U.S. is Complainant
data1 <- df %>%
    filter(complainant == target_country) %>%
    count(respondent) %>%
    slice_max(n, n = 7, with_ties = FALSE)

# Top 7 Complainants when U.S. is Respondent
data2 <- df %>%
    filter(respondent == target_country) %>%
    count(complainant) %>%
    slice_max(n, n = 7, with_ties = FALSE)

# Top 7 Respondents when U.S. is Third Party
data3 <- df %>%
    filter(is_us_tp) %>%
    count(respondent) %>%
    slice_max(n, n = 7, with_ties = FALSE)

# Top 7 Complainants when U.S. is Third Party
data4 <- df %>%
    filter(is_us_tp) %>%
    count(complainant) %>%
    slice_max(n, n = 7, with_ties = FALSE)

plot_bar <- function(data, x_var, y_var, title, fill_color) {
    data[[x_var]] <- factor(data[[x_var]], levels = rev(data[[x_var]]))
    ggplot(data, aes(x = .data[[y_var]], y = .data[[x_var]])) +
        geom_col(fill = fill_color, width = 0.8) +
        labs(title = title, x = "Number of Cases", y = NULL) +
        theme_minimal() +
        theme(
            plot.title = element_text(hjust = 0.5, size = 14),
            panel.grid.minor = element_blank(),
            axis.text.y = element_text(size = 12)
        )
}

# Plot
p1 <- plot_bar(data1, "respondent", "n", "Top 7 Respondents when U.S. is Complainant", "#4682B4")
p2 <- plot_bar(data2, "complainant", "n", "Top 7 Complainants when U.S. is Respondent", "#CD5C5C")
p3 <- plot_bar(data3, "respondent", "n", "Top 7 Respondents when U.S. is Third Party", "#3CB371")
p4 <- plot_bar(data4, "complainant", "n", "Top 7 Complainants when U.S. is Third Party", "#DAA520")

(p1 | p2) / (p3 | p4) + 
    plot_annotation(
        title = "WTO Dispute Analysis for United States",
        theme = theme(plot.title = element_text(size = 18, face = "bold", hjust = 0.5))
    )

# ===========================================================================
# Document Distribution
doc_df <- jsonlite::fromJSON("./Data/WTO/rename_manifest_full.json")
plot_data <- df %>%
    mutate(type = case_when(
        type == "Request_To_Join_Consultations" ~ "Join Consultation",
        TRUE ~ as.character(type)
    )) %>%
    count(type) %>%
    arrange(desc(n))
    # slice_head(n = 10) # print all categories

# turn into factor
plot_data$type <- factor(plot_data$type, levels = plot_data$type)

# Plot
ggplot(plot_data, aes(x = type, y = n)) +
    geom_col(fill = "#4A6990", width = 0.7, color = "black", size = 0.2) +
    geom_text(aes(label = n), vjust = -0.5, size = 3.5, fontface = "bold") +
    labs(
        title = "Distribution of WTO Dispute Settlement Case Types",
        x = "Legal Stage / Procedure Type",
        y = "Frequency (Count)",
    ) +
    theme_classic(base_size = 12) +
    theme(
        plot.title = element_text(face = "bold", size = 16, margin = margin(b = 10)),
        plot.subtitle = element_text(size = 11, color = "grey40", margin = margin(b = 15)),
        axis.text.x = element_text(angle = 45, hjust = 1, color = "black"),
        axis.title = element_text(face = "bold"),
        panel.grid.major.y = element_line(color = "grey90", size = 0.5),
        plot.margin = margin(1, 1, 1, 1, "cm")
    ) +
    scale_y_continuous(expand = expansion(mult = c(0, 0.1)))

# Save
ggsave("Case_Type_Distribution.png", width = 10, height = 7)


