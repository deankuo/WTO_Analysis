# Dataset Documentation — WTO Dispute Analysis

**Last Updated:** \today
**Maintainer:** Dean Kuo

---

## Table of Contents

1. [Panel Data](#1-panel-data)
   - [1.1 Country-Year Panel: `country_meta_1995_2024.csv`](#11-country-year-panel-country_meta_1995_2024csv)
   - [1.2 WTO Participation Panel: `wto_panel_1995_2024.csv`](#12-wto-participation-panel-wto_panel_1995_2024csv)
   - [1.3 WTO Membership List: `wto_mem_list.csv`](#13-wto-membership-list-wto_mem_listcsv)
2. [Dyadic Data](#2-dyadic-data)
   - [2.1 WTO Dispute Dyads: `wto_dyadic.csv`](#21-wto-dispute-dyads-wto_dyadiccsv)
   - [2.2 Bilateral Trade (WTO-filtered): `bilateral_trade_wto.csv`](#22-bilateral-trade-wto-filtered-bilateral_trade_wtocsv)
   - [2.3 Bilateral Trade by Section (WTO-filtered): `bilateral_trade_section_wto.csv`](#23-bilateral-trade-by-section-wto-filtered-bilateral_trade_section_wtocsv)
   - [2.4 DESTA Trade Agreement Panel: `desta_panel_1995_2025.csv`](#24-desta-trade-agreement-panel-desta_panel_1995_2025csv)
3. [WTO Case Data](#3-wto-case-data)
   - [3.1 Case Dataset: `wto_cases.csv`](#31-case-dataset-wto_casescsv)
   - [3.2 WTO Dispute Analysis Results](#32-wto-dispute-analysis-results)
4. [Systematic Missing Data](#4-systematic-missing-data)
   - [4.1 Panel Dataset](#41-panel-dataset-country_meta_1995_2024csv)
   - [4.2 Bilateral Trade Dataset](#42-bilateral-trade-dataset-bilateral_trade_wtocsv)
   - [4.3 Bilateral Trade Section Dataset](#43-bilateral-trade-section-dataset-bilateral_trade_section_wtocsv)
5. [Data Processing & Construction Notes](#5-data-processing--construction-notes)
6. [Reference Files](#6-reference-files)

---

## 1. Panel Data

### 1.1 Country-Year Panel: `country_meta_1995_2024.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Country-year |
| Rows | 5,880 |
| Countries / Polities | 196 |
| Year range | 1995–2024 (30 years) |
| Columns | 77 |
| Primary key | `(country, year)` |

The dataset integrates seven major data sources into a balanced country-year panel covering all WTO-relevant polities (WTO members, observers, and non-members that appear in WTO dispute records), plus the EU as a collective actor.

---

#### A. Identifiers

| Variable | Definition | Unit / Range | Source |
|----------|-----------|--------------|--------|
| `country` | Country / polity name | String | User-defined |
| `iso3c` | ISO 3166-1 alpha-3 country code | 3-letter string (e.g., `USA`, `TAW`) | WDI / User-defined |
| `ccode` | Correlates of War numeric country code | Integer; –1 if no COW match | COW State System |
| `stateabb` | COW state abbreviation (3-letter) | String (e.g., `USA`, `CHN`) | COW State System |
| `un_country_name` | Official UN country name | String | UN / WDI |
| `year` | Calendar year | Integer; 1995–2024 | — |
| `COWcode` | COW numeric code (for V-Dem/NMC join) | Integer | COW / V-Dem |

> **Note on `ccode`:** Uses –1 as a sentinel for polities without a COW code (e.g., EU, Hong Kong, Macao, small island states).

---

#### B. WTO Membership & Participation

**Source:** WTO official membership records and `wto_cases.csv` dispute data (626 cases, 1995–2024).

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `wto_member` | Whether the country is a WTO member in that year | Binary (0/1) |
| `wto_accession_year` | Year of WTO accession | Integer; 1995–2024; `NaN` for non-members (15.3%) |
| `complainant` | Country initiated at least one WTO dispute in that year | Binary (0/1) |
| `respondent` | Country was respondent in at least one dispute in that year | Binary (0/1) |
| `third_party` | Country joined as third party in at least one dispute in that year | Binary (0/1) |
| `wto_participant` | Any WTO dispute activity (complainant OR respondent OR third party) | Binary (0/1) |
| `cum_complainant` | Cumulative number of disputes initiated (1995–that year) | Integer; 0–25 |
| `cum_respondent` | Cumulative number of disputes faced as respondent | Integer; 0–29 |
| `cum_third_party` | Cumulative number of third-party appearances | Integer; 0–30 |

---

#### C. EU / Eurozone Membership

**Source:** European Union official membership records; European Central Bank Eurozone records.

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `eu_member` | Whether the country was an EU member in that year | Binary (0/1) |
| `euro_join_year` | Year the country adopted the Euro | Integer; 1999–2023; `NaN` for non-Euro countries (89.8%) |
| `euro_member` | Whether the country used the Euro in that year | Binary (0/1) |

---

#### D. UN Voting Ideal Points

**Source:** Bailey, Michael A., Anton Strezhnev, and Erik Voeten. 2017. "Estimating Dynamic State Preferences from United Nations Voting Data." *Journal of Conflict Resolution* 61(2): 430–456.
**Data version:** July 28, 2025 (Erik Voeten, Georgetown University).

The ideal points are estimated using a Bayesian Item Response Theory (IRT) model fit to UNGA voting records. Higher values indicate alignment with the US; lower values indicate alignment with Russia/China.

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `idealpointfp` | Ideal point based on final-passage votes only | Continuous; approx. –2.1 to +3.0 |
| `idealpointall` | Ideal point based on all votes | Continuous; approx. –2.4 to +3.1 |
| `idealpointlegacy` | Ideal point from legacy session-based estimation | Continuous; approx. –2.2 to +3.2 |
| `nvotesfp` | Number of final-passage votes | Integer; 1–109 |
| `nvotesall` | Number of all votes | Integer; 1–232 |
| `nvotesLegacy` | Number of votes for legacy estimation | Integer; 1–96 |
| `qofp` | Posterior mean (FP) | Continuous |
| `q5fp`, `q10fp`, `q50fp`, `q90fp`, `q95fp`, `q100fp` | Posterior quantiles (FP) | Continuous |
| `qoall` | Posterior mean (all votes) | Continuous |
| `q5all`, `q10all`, `q50all`, `q90all`, `q95all`, `q100all` | Posterior quantiles (all votes) | Continuous |

---

#### E. V-Dem Democracy Indicators

**Source:** Coppedge, Michael, et al. 2025. "V-Dem Codebook v15." Varieties of Democracy (V-Dem) Project, University of Gothenburg.

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `v2x_polyarchy` | Electoral Democracy Index | Continuous; 0–1 |
| `v2x_libdem` | Liberal Democracy Index | Continuous; 0–1 |
| `v2x_regime` | Regime type classification | 0=Closed Autocracy; 1=Electoral Autocracy; 2=Electoral Democracy; 3=Liberal Democracy |
| `v2eltype_0` | Legislative election held (first round) | 0/1; `NaN` in non-election years (74.7%) |
| `v2eltype_1` | Legislative election held (second round) | 0/1; `NaN` in non-election years |
| `v2eltype_6` | Presidential election held (first round) | 0/1; `NaN` in non-election years |
| `v2eltype_7` | Presidential election held (second round) | 0/1; `NaN` in non-election years |
| `is_leg_elec` | Any legislative election in that year | Binary (0/1); derived |
| `is_pres_elec` | Any presidential election in that year | Binary (0/1); derived |
| `election_binary` | Any election (legislative or presidential) | Binary (0/1); derived |

> **Note:** `v2eltype_*` are `NaN` in non-election years — this is by design, not missing data.

---

#### F. World Development Indicators (WDI)

**Source:** World Bank, World Development Indicators (WDI). Accessed 2025.

**Unit standardization:** Monetary values in **Million USD**. Percentage values divided by 100 to **Ratio (0–1)**.

| Variable | WDI Code | Definition | Unit |
|----------|----------|-----------|------|
| `gdp` | `NY.GDP.MKTP.KD` | Real GDP (constant 2015 USD) | Million USD |
| `gdppc` | `NY.GDP.PCAP.KD` | Real GDP per capita (constant 2015 USD) | USD |
| `pop` | `SP.POP.TOTL` | Total population | Count |
| `gdp_growth_rate` | `NY.GDP.MKTP.KD.ZG` | Annual GDP growth rate | Ratio |
| `trade` | `NE.TRD.GNFS.ZS` | Total trade (exports + imports) as % of GDP | Ratio |
| `fdi` | `BX.KLT.DINV.WD.GD.ZS` | Net FDI inflows as % of GDP | Ratio |
| `fdi_inflow_usd` | `BX.KLT.DINV.CD.WD` | Net FDI inflows (absolute) | Million USD |
| `exp_share` | `NE.EXP.GNFS.ZS` | Exports of goods and services as % of GDP | Ratio |
| `imp_share` | `NE.IMP.GNFS.ZS` | Imports of goods and services as % of GDP | Ratio |
| `unemployment_rate` | `SL.UEM.TOTL.NE.ZS` | Unemployment rate (national estimate) | Ratio |

---

#### G. Worldwide Governance Indicators (WGI)

**Source:** Kaufmann, Daniel, Aart Kraay, and Massimo Mastruzzi. 2010. "The Worldwide Governance Indicators: Methodology and Analytical Issues." *World Bank Policy Research Working Paper* No. 5430.

All six WGI indicators are on a standard normal scale (–2.5 to +2.5), higher = better governance.

| Variable | WGI Code | Definition |
|----------|----------|-----------|
| `voice` | `VA.EST` | Voice and Accountability |
| `stability` | `PV.EST` | Political Stability and Absence of Violence/Terrorism |
| `efficiency` | `GE.EST` | Government Effectiveness |
| `reg_quality` | `RQ.EST` | Regulatory Quality |
| `law` | `RL.EST` | Rule of Law |
| `corruption` | `CC.EST` | Control of Corruption |

WGI interpolation: 1995 backfilled from 1996; 1997, 1999, 2001 linearly interpolated from adjacent survey years.

---

#### H. Geographic & Classification Variables

**Source:** World Bank WDI.

| Variable | Definition | Values |
|----------|-----------|--------|
| `region` | World Bank geographic region | 7 regions; `NaN` for EU |
| `longitude` | Geographic centroid longitude | Decimal degrees |
| `latitude` | Geographic centroid latitude | Decimal degrees |
| `income` | World Bank income group | `Low income`, `Lower middle income`, `Upper middle income`, `High income` |

---

#### I. Derived Variables

| Variable | Definition | Formula |
|----------|-----------|---------|
| `log_gdppc` | Natural log of real GDP per capita | `ln(gdppc)` |
| `log_pop` | Natural log of total population | `ln(pop)` |

---

#### J. COW National Material Capabilities (NMC)

**Source:** Singer, Bremer, and Stuckey. 1972. **Dataset version:** NMC 6.0 (1816–2016).

> **Coverage note:** NMC v6.0 covers **1816–2016 only**. All observations for **2017–2024 are `NaN`** (1,568 missing observations).

| Variable | Definition | Unit |
|----------|-----------|------|
| `cinc` | Composite Index of National Capability | Proportion; 0–1 |
| `milex` | Military expenditures | Thousands USD |
| `milper` | Military personnel | Thousands of persons |
| `pec` | Primary energy consumption | Thousands of coal-ton equivalents |
| `tpop` | Total population | Thousands of persons |
| `upop` | Urban population (cities >100k) | Thousands of persons |

> **Sentinel values:** COW uses **–9** to denote missing values. These are retained as-is; recode to `NaN` before modeling.

---

### 1.2 WTO Participation Panel: `wto_panel_1995_2024.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Country-year |
| Rows | 5,880 |
| Columns | 18 |

The WTO-specific subset of `country_meta_1995_2024.csv`. Contains only identifiers (`country`, `iso3c`, `ccode`, `stateabb`, `un_country_name`, `year`), WTO participation variables (`wto_member`, `wto_accession_year`, `complainant`, `respondent`, `third_party`, `wto_participant`, `cum_complainant`, `cum_respondent`, `cum_third_party`), and EU/Eurozone membership (`eu_member`, `euro_join_year`, `euro_member`).

---

### 1.3 WTO Membership List: `wto_mem_list.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 166 |
| Columns | 5 |

| Variable | Definition |
|----------|-----------|
| `member` | Member name (WTO official) |
| `membership_date` | Full accession date |
| `iso3c` | ISO3 code |
| `ccode` | COW numeric code |
| `year` | Accession year (integer) |

---

## 2. Dyadic Data

### 2.1 WTO Dispute Dyads: `wto_dyadic.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Case-level directed dyad |
| Rows | 8,145 |
| Columns | 31 |
| Unique cases | 626 |

Each row represents a directed country-pair relationship within a specific WTO dispute case.

| Variable | Definition |
|----------|-----------|
| `case` | WTO case number (DS1–DS626) |
| `country1` | First country in the dyad |
| `country2` | Second country in the dyad |
| `relationship` | `complainant-respondent` (669), `complainant-third_party` (3,811), or `third_party-respondent` (3,665) |
| `iso3_1`, `iso3_2` | ISO3 codes for each country |
| `ccode1`, `ccode2` | COW codes for each country |
| Remaining 23 columns | Full case metadata inherited from `wto_cases.csv` (title, summary, agreements cited, all procedural dates, `dispute_stage`) |

---

### 2.2 Bilateral Trade (WTO-filtered): `bilateral_trade_wto.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Directed dyad-year (exporter → importer) |
| Rows | 545,333 |
| Columns | 31 |
| Years | 1995–2024 |
| Scripts | `build_baci_trade.py` (base trade) + `build_dyadic_datasets.py` (merge & filter) |

Directed dyad-year bilateral trade data filtered to pairs where **both exporter and importer are WTO members** in the given year (time-varying membership filter). Merges base BACI trade data (882,643 rows) with ATOP alliance data and DESTA trade agreement data, then applies WTO membership filtering (removes 337,310 non-WTO-member dyad-year observations).

Uses **dual EU representation**: individual EU member states retain their own trade flows (including intra-EU trade) while a separate `EUN` aggregate captures the EU as a single external trade actor (intra-EU trade excluded).

#### Trade Variables (from BACI HS92)

| Variable | Definition | Unit |
|----------|-----------|------|
| `year` | Calendar year | Integer; 1995–2024 |
| `exporter` | Exporter ISO3 code | String |
| `exporter_ccode` | Exporter COW numeric code | Integer |
| `exporter_name` | Exporter country name | String |
| `importer` | Importer ISO3 code | String |
| `importer_ccode` | Importer COW numeric code | Integer |
| `importer_name` | Importer country name | String |
| `total_trade_ij` | Total exports from i to j | Thousands USD |
| `n_products_ij` | Number of distinct HS6 products traded | Integer |
| `n_sections_ij` | Number of distinct HS sections traded | Integer; 1–21 |
| `export_dependence` | `total_trade_ij / total_exports_i` — Partner dependence | Ratio (0–1) |
| `trade_dependence` | `(exports_ij + imports_ij) / gdp_i` — Bilateral trade relative to GDP | Ratio; unbounded |
| `total_exports_i` | Total exports of exporter i (all destinations) | Thousands USD |

> **Import data omitted by design:** Import-side columns are not stored because they are redundant — the import flow from j to i equals the export flow in the reverse row (j, i). Reconstruct if needed by joining on the reverse direction.

> **`trade_dependence`:** Can exceed 1 for small open economies (e.g., ship-registration economies). `NaN` for entities without GDP in the panel (2.4%).

#### ATOP Alliance Variables

**Source:** Leeds et al. 2002. ATOP v5.1 (1815–2018). Forward-filled 2019–2024 from 2018.

| Variable | Definition | Values |
|----------|-----------|--------|
| `atopally` | Any alliance between exporter and importer | 0/1 |
| `defense` | Exporter has defensive obligation toward importer | 0/1 |
| `offense` | Exporter has offensive obligation toward importer | 0/1 |
| `neutral` | Neutrality obligation | 0/1 |
| `nonagg` | Non-aggression pact | 0/1 |
| `consul` | Consultation obligation | 0/1 |

> **ATOP uses COW ccodes.** After WTO membership filtering, all rows have valid ccodes on both sides, so no ATOP `NaN` values remain. Allied: 130,206 (23.9%). Not allied: 415,127 (76.1%).

#### DESTA Trade Agreement Variables

**Source:** Dur, Baccini, and Elsig. 2014. DESTA v2.

| Variable | Definition | Values |
|----------|-----------|--------|
| `label` | Any trade agreement in force between dyad | 0/1 |
| `number` | DESTA agreement identifier | Integer; `NaN` if no agreement |
| `base_treaty` | Base treaty number | Integer |
| `name` | Agreement name | String |
| `entry_type` | Type of entry into the agreement | Categorical |
| `typememb` | Membership type (1=bilateral, 2=plurilateral, etc.) | Integer; 1–7 |
| `depth_index` | Additive depth index (7 provisions) | Integer; 0–7 |
| `depth_rasch` | Rasch-scaled depth measure (latent trait) | Continuous |
| `flexrigid` | Flexibility/rigidity provisions | Continuous |
| `flexescape` | Escape clause provisions | Continuous |
| `enforce` | Dispute settlement mechanism strength (raw) | Continuous |
| `enforce01` | Standardized DSM strength index | Continuous; 0–6 |

> **DESTA is undirected.** The pipeline merges both directions to ensure CHN→AUS gets the same values as AUS→CHN. Has agreement: 205,130 (37.6%). No agreement: 340,203 (62.4%).

---

### 2.3 Bilateral Trade by Section (WTO-filtered): `bilateral_trade_section_wto.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Directed dyad-year-section |
| Rows | 6,374,486 |
| Columns | 14 |
| Sections | 21 HS sections |
| Scripts | `build_baci_trade.py` (base) + `build_dyadic_datasets.py` (WTO filter) |

Section-level breakdown of bilateral trade, WTO-filtered. No ATOP/DESTA columns at this level.

| Variable | Definition | Unit |
|----------|-----------|------|
| `year` | Calendar year | Integer; 1995–2024 |
| `exporter` | Exporter ISO3 code | String |
| `exporter_ccode` | Exporter COW numeric code | Integer |
| `importer` | Importer ISO3 code | String |
| `importer_ccode` | Importer COW numeric code | Integer |
| `section_num` | HS section number | Integer; 1–21 |
| `section_en` | HS section English name | String |
| `trade_value_ij_s` | Exports from i to j in section s | Thousands USD |
| `n_products_ij_s` | Number of distinct HS6 products in section s | Integer |
| `bilateral_sector_concentration` | `trade_value_ij_s / total_exports_i` — How important is section s for i→j trade | Ratio (0–1) |
| `sector_export_concentration` | `total_exports_i_s / total_exports_i` — How important is section s for country i | Ratio (0–1) |
| `partner_sector_dependence` | `trade_value_ij_s / total_exports_i_s` — How much does i rely on j for section s | Ratio (0–1) |
| `total_exports_i` | Total exports of exporter i (all destinations, all sections) | Thousands USD |
| `total_exports_i_s` | Total exports of exporter i in section s (all destinations) | Thousands USD |

> **No missing values** in this dataset.

---

### 2.4 DESTA Trade Agreement Panel: `desta_panel_1995_2025.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Undirected dyad-year (country1 < country2 alphabetically) |
| Rows | 235,011 |
| Columns | 21 |
| Years | 1995–2025 |
| Unique dyads | 7,581 |
| Script | `build_dyadic_datasets.py` |

| Variable | Definition |
|----------|-----------|
| `country1`, `country2` | Country names (alphabetically sorted) |
| `year` | Calendar year |
| `label` | Trade agreement in force (0/1). Has agreement: 167,521; No agreement: 67,490 |
| `iso3_1`, `iso3_2` | ISO3 codes (mapped from ISO 3166-1 numeric via `country_converter`) |
| `baci_code1`, `baci_code2` | ISO 3166-1 numeric codes (from original DESTA data) |
| `ccode1`, `ccode2` | COW numeric codes |
| `number`, `base_treaty`, `name` | DESTA agreement identifiers |
| `entry_type`, `typememb` | Agreement membership type |
| `depth_index`, `depth_rasch` | Depth measures |
| `flexrigid`, `flexescape` | Flexibility provisions |
| `enforce`, `enforce01` | Dispute settlement strength |

> **ISO mapping note:** DESTA uses ISO 3166-1 numeric codes (e.g., USA=840, France=250) which differ from BACI codes (USA=842, France=251). The pipeline maps these using `country_converter` with `src='ISOnumeric'`. Taiwan (ISO=158) is mapped to `TAW` to match the panel dataset. Unmapped iso3_1: 651 rows (mostly dissolved states).

---

## 3. WTO Case Data

### 3.1 Case Dataset: `wto_cases.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 626 (DS1–DS626) |
| Columns | 24 |

| Variable | Definition |
|----------|-----------|
| `case` | Case number |
| `Complainant` | List of complainant countries |
| `Respondent` | List of respondent countries |
| `third_parties` | List of third-party countries |
| `title` | Case title |
| `summary` | Case summary |
| `agreements_cited` | WTO agreements cited |
| `consultations_requested` | Date consultations requested |
| `panel_requested` | Date panel requested |
| `mutually_agreed_solution_notified` | Date of mutually agreed solution |
| `panel_established` | Date panel established |
| `panel_composed` | Date panel composed |
| `panel_report_circulated` | Date panel report circulated |
| `appellate_body_report_circulated` | Date appellate body report circulated |
| `Art 21.3(c) DSU Arbitration report circulated` | Date of Art 21.3(c) report |
| `Art 21.5 DSU Panel lapsed` | Date Art 21.5 panel lapsed |
| `Art 21.5 DSU Panel report circulated` | Date of Art 21.5 panel report |
| `Art 21.5 DSU Appellate Body report circulated` | Date of Art 21.5 AB report |
| `Art 22.6 DSU Arbitration decision circulated` | Date of Art 22.6 decision |
| `Art 25 DSU Arbitration award circulated` | Date of Art 25 award |
| `Second Recourse to Art 21.5 DSU Panel report circulated` | Date of second recourse panel report |
| `Second Recourse to Art 21.5 DSU Appellate Body report circulated` | Date of second recourse AB report |
| `panel_lapsed` | Date panel lapsed |
| `dispute_stage` | Final stage reached (Consultation, Panel, Appellate Body, etc.) |

**Dispute Stage Distribution:**

| Stage | Cases |
|-------|-------|
| Consultation | 237 (37.8%) |
| Panel | 175 (27.9%) |
| Appellate Body | 115 (18.4%) |
| Mutually Agreed Solution | 69 (11.0%) |
| Implementation & Compliance | 23 (3.7%) |
| Retaliation & Arbitration | 4 (0.6%) |
| Unknown | 3 (0.5%) |

---

### 3.2 WTO Dispute Analysis Results

#### Network Analysis Results (`wto_analysis_results_1995-2024.json`)

Annual cumulative network metrics (conflict-weighted dispute graph):

| Year | Nodes | Edges | Conflict Density | Modularity | Communities |
|------|-------|-------|-----------------|------------|-------------|
| 1995 | 26 | 100 | 0.086 | 0.196 | 3 |
| 2000 | 36 | 267 | 0.065 | 0.019 | 3 |
| 2005 | 26 | 100 | 0.037 | 0.182 | 4 |
| 2010 | 33 | 217 | 0.036 | 0.031 | 2 |
| 2015 | 32 | 227 | 0.026 | –0.052 | 3 |
| 2018 | 50 | 1,117 | 0.032 | 0.086 | 4 |
| 2020 | 23 | 87 | 0.020 | 0.173 | 2 |
| 2024 | 20 | 39 | 0.026 | 0.200 | 1 |

#### Document Processing Statistics

| Metric | Value |
|--------|-------|
| Total PDFs processed | 9,480 |
| Successfully classified | 9,398 (99.1%) |
| Manual review required | 82 files (78 scanned, 3 non-English, 1 error) |
| Document types (consolidated) | 35 |
| Date coverage | ~90% |

---

## 4. Systematic Missing Data

### 4.1 Panel Dataset (`country_meta_1995_2024.csv`)

**Overall missing data by variable group:**

| Variable Group | Missing % | Reason |
|----------------|-----------|--------|
| `wto_accession_year` | 15.3% | Non-WTO members |
| `euro_join_year` | 89.8% | Non-Euro countries |
| `idealpointfp` | 4.1% | Non-UN members/observers |
| `idealpointall` / `idealpointlegacy` | 7.4% | Same + broader vote gaps |
| `COWcode` / V-Dem indices | 12.6% | Entities outside COW/V-Dem |
| `v2eltype_*` | 74.7% | `NaN` in non-election years (by design) |
| `gdp`, `gdppc` | 4.4% | Non-reporting states |
| `trade`, `exp_share`, `imp_share` | 18.1% | Small/conflict states |
| `unemployment_rate` | 42.8% | Many developing countries don't report |
| `cinc` / NMC variables | 28.7% | NMC v6.0 ends 2016 (all countries `NaN` 2017–2024) |
| WGI (`voice`, `stability`, etc.) | 5.6–8.6% | Small/non-covered states |

**Countries systematically missing from each source:**

| Source | Missing Polities | Reason |
|--------|-----------------|--------|
| **UN Voting** (all years) | Taiwan, Hong Kong, Macao, EU | Not UN members |
| **UN Voting** (partial) | Afghanistan, Bosnia, Burundi, Cambodia, etc. (30+ countries) | Non-membership or irregular participation in some years |
| **V-Dem** (all years) | EU, Hong Kong, Macao, Andorra, Monaco, San Marino, Liechtenstein, Brunei, 8 Pacific island states, 9 Caribbean island states, South Sudan, Montenegro | Supranational entities, micro-states, SARs |
| **COW NMC** (2017–2024) | All 196 countries | NMC v6.0 coverage ends 2016 |
| **COW NMC** (1995–2016) | EU, Hong Kong, Macao, Andorra, Monaco, San Marino, Liechtenstein | Not sovereign COW states |
| **WDI** | North Korea, Syria (post-2011), Somalia, South Sudan (pre-2011), EU, Taiwan (supplemented) | Sanctions, conflict, non-reporting |
| **WGI** | North Korea, very small island states, EU | Not covered |

---

### 4.2 Bilateral Trade Dataset (`bilateral_trade_wto.csv`)

| Variable | Missing % | Reason |
|----------|-----------|--------|
| `trade_dependence` | 2.4% | Entities without GDP in panel (e.g., EUN, territories) |
| `number`, `base_treaty`, `name`, `entry_type`, `typememb` | 56.5% | Dyads with no DESTA trade agreement (label=0) |
| `depth_index`, `depth_rasch`, `flexrigid`, `flexescape`, `enforce`, `enforce01` | 62.4% | No agreement (label=0) or agreement exists but no depth coding |

> All other variables (trade, ATOP) have 0% missing after WTO membership filtering.

---

### 4.3 Bilateral Trade Section Dataset (`bilateral_trade_section_wto.csv`)

No missing values in any column.

---

## 5. Data Processing & Construction Notes

### 5.1 Unit Standardization

| Transformation | Details |
|----------------|---------|
| GDP / FDI monetary values | Divided by 1,000,000 → Million USD |
| WDI percentage variables | Divided by 100 → Ratio (0–1) |
| COW NMC sentinel values | Raw –9 values retained; recode to `NaN` before use |
| BACI trade values | Thousands of current USD (original BACI units) |

### 5.2 WGI Interpolation

WGI surveys were not conducted annually before 2002:
- **1995**: Backfilled using 1996 data.
- **1997**: Linear interpolation of 1996 and 1998.
- **1999**: Linear interpolation of 1998 and 2000.
- **2001**: Linear interpolation of 2000 and 2002.

### 5.3 WTO Participation Variables

- `complainant`, `respondent`, `third_party` are constructed from `wto_cases.csv` (626 cases).
- The EU is treated as a single litigation actor. Individual EU member states may also appear separately.
- Cumulative counts (`cum_*`) are inclusive of the current year.

### 5.4 V-Dem Election Variables

- `v2eltype_*` variables are `NaN` in non-election years (not missing data).
- `is_leg_elec`, `is_pres_elec`, `election_binary` are derived aggregates.

### 5.5 Bilateral Trade Pipeline

```
BACI HS92 raw data → build_baci_trade.py → bilateral_trade_aggregate.csv (882,643 rows)
                                          → bilateral_trade_by_section.csv (8.9M rows)
                                              ↓
                      build_dyadic_datasets.py:
                        + ATOP 5.1 alliances (forward-filled 2019–2024)
                        + DESTA trade agreements (both merge directions)
                        + WTO membership filter (time-varying)
                                              ↓
                      bilateral_trade_wto.csv (545,333 rows)
                      bilateral_trade_section_wto.csv (6,374,486 rows)
```

**WTO membership filter:** Removes rows where either exporter or importer was not yet a WTO member in the given year. Reduces aggregate from 882,643 to 545,333 rows (–38.2%) and section-level from 8,880,578 to 6,374,486 rows (–28.2%).

**DESTA merge fix:** DESTA is undirected (country1 < country2 alphabetically). The pipeline merges both directions (exporter=iso3_1/importer=iso3_2 AND exporter=iso3_2/importer=iso3_1) to ensure symmetric coverage.

**DESTA ISO code fix:** DESTA uses ISO 3166-1 numeric codes which differ from BACI codes for 15 countries (e.g., USA: ISO=840, BACI=842; France: ISO=250, BACI=251). Fixed using `country_converter` with `src='ISOnumeric'`.

### 5.6 EU Representation in Trade Data

| Entity type | Rows include | `total_exports_i` basis | Intra-EU trade |
|-------------|-------------|------------------------|----------------|
| Individual EU member (e.g., `FRA`) | All bilateral flows including intra-EU | All exports including to other EU members | Included |
| EU aggregate (`EUN`) | Only EU external flows | EU external exports only | Excluded |

Belgium-Luxembourg: BACI reports as a single unit (code 58) until 1998, mapped to Belgium.

---

## 6. Reference Files

### 6.1 BACI Code Mapping: `baci_to_iso3_mapping.csv`

| Variable | Definition |
|----------|-----------|
| `baci_code` | BACI numeric country code |
| `iso3` | ISO alpha-3 country code |
| `ccode` | COW numeric code |
| `country_name` | Country name from BACI metadata |

### 6.2 EU Membership Panel: `eu_membership_1995_2024.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 840 (28 EU members x 30 years) |
| Columns | 8 |

| Variable | Definition |
|----------|-----------|
| `country` | Country name |
| `iso3c` | ISO alpha-3 code |
| `ccode` | COW numeric code |
| `baci_code` | BACI numeric code |
| `year` | Calendar year |
| `eu_member` | Whether the country was an EU member in that year (0/1) |
| `accession_year` | Year of EU accession |
| `exit_year` | Year of EU exit; `NaN` if still member |

### 6.3 Harmonized Case Dataset: `wto_cases_harmonized.csv`

Harmonized version of case data with standardized country names for network analysis.

---

*End of documentation.*
