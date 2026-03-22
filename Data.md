# Dataset Documentation — WTO Dispute Analysis

**Last Updated:** March 2026
**Maintainer:** Dean Kuo

---

## Table of Contents

1. [Panel Data](#1-panel-data)
   - [1.1 Country-Year Panel: `country_meta_1995_2024.csv`](#11-country-year-panel-country_meta_1995_2024csv)
   - [1.2 WTO Participation Panel: `wto_panel_1995_2024.csv`](#12-wto-participation-panel-wto_panel_1995_2024csv)
   - [1.3 WTO Membership List: `wto_mem_list.csv`](#13-wto-membership-list-wto_mem_listcsv)
2. [Dyadic Data](#2-dyadic-data)
   - [2.1 WTO Dispute Dyads: `wto_dyadic_v2.csv`](#21-wto-dispute-dyads-wto_dyadic_v2csv)
   - [2.2 Bilateral Trade (WTO-filtered): `bilateral_trade_wto.csv`](#22-bilateral-trade-wto-filtered-bilateral_trade_wtocsv)
   - [2.3 Bilateral Trade by Section (WTO-filtered): `bilateral_trade_section_wto.csv`](#23-bilateral-trade-by-section-wto-filtered-bilateral_trade_section_wtocsv)
   - [2.4 DESTA Trade Agreement Panel: `desta_panel_1995_2025.csv`](#24-desta-trade-agreement-panel-desta_panel_1995_2025csv)
3. [WTO Case Data](#3-wto-case-data)
   - [3.1 Case Dataset: `wto_cases_v2.csv`](#31-case-dataset-wto_cases_v2csv)
   - [3.2 RAG Pipeline Outputs (`Data/Output/`)](#32-rag-pipeline-outputs-dataoutput)
   - [3.3 WTO Dispute Analysis Results](#33-wto-dispute-analysis-results)
4. [Systematic Missing Data](#4-systematic-missing-data)
   - [4.1 Panel Dataset](#41-panel-dataset-country_meta_1995_2024csv)
   - [4.2 Bilateral Trade Dataset](#42-bilateral-trade-dataset-bilateral_trade_wtocsv)
   - [4.3 Bilateral Trade Section Dataset](#43-bilateral-trade-section-dataset-bilateral_trade_section_wtocsv)
   - [4.4 ERGM Datasets](#44-ergm-datasets)
5. [Data Processing & Construction Notes](#5-data-processing--construction-notes)
   - [5.1 Unit Standardization](#51-unit-standardization)
   - [5.2 WGI Interpolation](#52-wgi-interpolation)
   - [5.3 WTO Participation Variables](#53-wto-participation-variables)
   - [5.4 V-Dem Election Variables](#54-v-dem-election-variables)
   - [5.5 Bilateral Trade Pipeline](#55-bilateral-trade-pipeline)
   - [5.6 EU Representation in Trade Data](#56-eu-representation-in-trade-data)
   - [5.7 EU Disaggregation Rules for ERGM Datasets](#57-eu-disaggregation-rules-for-ergm-datasets)
6. [Reference Files](#6-reference-files)
7. [ERGM Analysis Datasets](#7-ergm-analysis-datasets)
   - [7.1 `wto_cases_enriched.csv`](#71-wto_cases_enrichedcsv)
   - [7.2 `wto_dyadic_enriched.csv`](#72-wto_dyadic_enrichedcsv)
   - [7.3 `ergm_dyad_year_eun.csv`](#73-ergm_dyad_year_euncsv)
   - [7.4 `ergm_dyad_year_eu_disagg.csv`](#74-ergm_dyad_year_eu_disaggcsv)

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

**Source:** WTO official membership records and `wto_cases_v2.csv` dispute data (644 cases DS1–DS644, 1995–2024).

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

> **ERGM datasets:** All `nvotes*`, `q*` posterior uncertainty columns are **excluded** from ERGM node attribute merges. Only the point estimates `idealpointfp`, `idealpointall`, `idealpointlegacy` are retained (suffixed `_1`/`_2`). Taiwan/HK/Macao/EU have NaN for all ideal point columns.

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

> **ERGM datasets:** `v2eltype_0`, `v2eltype_1`, `v2eltype_6`, `v2eltype_7`, `is_leg_elec`, `is_pres_elec` are **excluded** from ERGM node attribute merges. Only `v2x_polyarchy`, `v2x_libdem`, `v2x_regime`, and `election_binary` are retained.

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

> **ERGM datasets:** `gdp` (total) is **excluded** from ERGM node attribute merges. Use `gdppc` and `log_gdppc` instead. All other WDI columns above are retained.

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

> **ERGM datasets:** Only `cinc` is retained from NMC. `milex`, `milper`, `pec`, `tpop`, `upop` are **excluded**. `cinc` is NaN for all years 2017–2024 (NMC v6.0 ends 2016).

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

### 2.1 WTO Dispute Dyads: `wto_dyadic_v2.csv`

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Case-level directed dyad |
| Rows | 8,373 |
| Columns | 36 |
| Unique cases | 644 |

Each row represents a directed country-pair relationship within a specific WTO dispute case. Country names harmonized: European Communities → European Union; Turkey → Türkiye.

| Variable | Definition |
|----------|-----------|
| `case` | WTO case number (DS1–DS644, string format "DS{N}") |
| `country1` | First country in the dyad |
| `country2` | Second country in the dyad |
| `relationship` | `complainant-respondent` (684), `complainant-third_party` (3,946), or `third_party-respondent` (3,743) |
| `iso3_1`, `iso3_2` | ISO3 codes for each country |
| `ccode1`, `ccode2` | COW codes for each country |
| Remaining 28 columns | Full case metadata inherited from `wto_cases_v2.csv` (title, short_title, summary, all procedural dates, `dispute_stage`, `product`) |

**EU handling note**: 395 cases have EUN-only; 37 cases list both EUN and individual member states (e.g., DS316 lists USA vs EUN, FRA, DEU, ESP, GBR separately); 30 early cases list individual EU member states without EUN (e.g., DS37: USA vs PRT). See Section 5.7 for EU disaggregation rules.

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

### 3.1 Case Dataset: `wto_cases_v2.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 644 (DS1–DS644) |
| Columns | 29 |
| Script | `scripts/scrape_wto_cases.py` (scraped March 2026) |

Country names harmonized: European Communities → European Union (230 cases); Turkey → Türkiye (119 cases).

| Variable | Definition |
|----------|-----------|
| `case` | Case number (string "DS{N}") |
| `title` | Full case title ("Respondent — Product" format) |
| `short_title` | Short case name |
| `complainant` | Complainant country/entity name |
| `respondent` | Respondent country/entity name |
| `third_parties` | Semicolon-separated list of third-party countries |
| `product` | Product/subject extracted from title |
| `dispute_stage` | 6 categories: Consultation, Mutually Agreed Solution, Panel, Appellate Body, Implementation, Retaliation |
| `current_status` | Free-text current status description |
| `summary` | Case summary text |
| `agreements_cited_consultations` | WTO agreements cited at consultation stage |
| `agreements_cited_panel` | WTO agreements cited at panel stage |
| `consultations_requested` | Date consultations requested |
| `panel_requested` | Date panel requested |
| `mutually_agreed_solution_notified` | Date of mutually agreed solution |
| `panel_established` | Date panel established |
| `panel_composed` | Date panel composed |
| `panel_report_circulated` | Date panel report circulated |
| `appellate_body_report_circulated` | Date appellate body report circulated |
| `Art 21.5 Panel requested` | Date Art 21.5 panel requested |
| `Art 21.5 DSU Panel report circulated` | Date Art 21.5 panel report circulated |
| `Art 21.5 DSU Appellate Body report circulated` | Date Art 21.5 AB report circulated |
| `Art 22.6 DSU Arbitration decision circulated` | Date Art 22.6 decision |
| `Art 25 DSU Arbitration award circulated` | Date Art 25 award |
| `Art 21.5 DSU Panel lapsed` | Date Art 21.5 panel lapsed |
| `panel_lapsed` | Date panel lapsed |
| `arbitration_agreement` | Arbitration agreement details |
| `recourse_to_arbitration` | Recourse to arbitration details |
| `article_25_arbitrator_composed` | Date Art 25 arbitrator composed |

**Dispute Stage Distribution:**

| Stage | Cases |
|-------|-------|
| Consultation | ~239 |
| Panel | ~178 |
| Appellate Body | ~115 |
| Mutually Agreed Solution | ~69 |
| Implementation | ~29 |
| Retaliation | ~14 |

> Note: DS627–DS644 (18 cases) have metadata but no PDF documents. Severity scoring and HS classification cover only DS1–DS626.

---

---

### 3.2 RAG Pipeline Outputs (`Data/Output/`)

All files cover DS1–DS626 (626 cases with PDF documents). Cases DS627–DS644 have no RAG outputs.

#### `industry_extraction.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 626 |
| Columns | 11 |

| Variable | Definition |
|----------|-----------|
| `case_id` | Integer case number |
| `case_title` | Case title |
| `title_product` | Product extracted from title |
| `product_descriptions` | RAG-extracted product descriptions |
| `explicit_hs_codes` | Explicitly cited HS codes in documents |
| `is_systemic` | Whether dispute concerns a systemic policy measure |
| `is_services` | Whether dispute concerns services (GATS) |
| `confidence` | Extraction confidence |
| `notes` | Additional notes |
| `retrieved_context` | Retrieved document context (truncated) |
| `n_parents_retrieved` | Number of parent chunks retrieved |

#### `case_hs_sections.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 626 |
| Columns | 12 |

| Variable | Definition |
|----------|-----------|
| `case_id` | Integer case number |
| `case_title` | Case title |
| `product` | Product from `wto_cases_v2.csv` (ground truth) |
| `title_hs_sections` | HS sections from product/title (pipe-separated integers 1–21) |
| `title_case_type` | Case type from title: `product` or `policy` |
| `hs_sections` | HS sections from RAG + LLM classification (pipe-separated integers 1–21) |
| `case_type` | LLM-assigned case type: `product` or `policy` |
| `product_descriptions` | Product descriptions (product cases only) |
| `policy` | Policy description (policy cases only) |
| `extraction_method` | `explicit_hs`, `llm_classification`, or `title_fallback` |
| `confidence` | Classification confidence |
| `reasoning` | LLM reasoning |

#### `case_section_expanded.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 3,003 |
| Columns | 5 |
| Primary key | `(case_id, hs_section)` |

One row per case-section pair. Policy cases with horizontal measures span all 21 sections (`is_horizontal_policy = True`).

| Variable | Definition |
|----------|-----------|
| `case_id` | Integer case number |
| `hs_section` | HS section number (integer 1–21) |
| `case_type` | `product` or `policy` |
| `extraction_method` | Method used for this classification |
| `confidence` | Confidence level |

#### `severity_scores_raw.csv`

| Attribute | Value |
|-----------|-------|
| Rows | 626 |
| Columns | 10 |

Raw (un-normalized) severity scores. Normalized version deferred until third-party scoring is complete.

| Variable | Definition | Range |
|----------|-----------|-------|
| `case_id` | Integer case number | 1–626 |
| `complainant` | Complainant country name | — |
| `rhetorical_aggressiveness` | 1=procedural/hedged → 5=hostile/geopolitical | 1–5 |
| `systemic_reach` | 1=product-specific → 5=regime-challenging | 1–5 |
| `escalation_ultimatum` | 1=routine → 5=retaliatory/rebalancing | 1–5 |
| `domestic_victimhood` | 1=no domestic pain → 5=existential threat | 1–5 |
| `severity_score` | Mean of 4 dimensions (composite) | 1–5 |
| `reasoning` | LLM reasoning for scores | — |
| `evidence` | Supporting evidence text | — |
| `n_parents_retrieved` | Parent chunks used for scoring | Integer |

> Scoring anchors: DS3 = 1 (procedural/hedged), DS267 = 3 (assertive/data-heavy), DS574 = 5 (geopolitical/aggressive)

---

### 3.3 WTO Dispute Analysis Results

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

#### Document Processing Statistics (March 2026 — Final)

| Metric | Value |
|--------|-------|
| Total PDFs processed | 9,417 (63 pre-split PDFs manually combined) |
| Successfully classified | 9,414 (99.97%) |
| Manual review required | 3 files (non-English cross-references: `293-19.pdf`) |
| Document types | 42 types |
| Date coverage | ~90% (multilingual extraction + multi-part inheritance) |
| Third-party joinings detected | 1,036 entries |

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

> **EUN DESTA note:** All 3,754 EUN rows in this file have `label=0`. This is a data artifact — DESTA records EU trade agreements through individual member states (e.g., EU-Korea FTA appears as DEU→KOR). The ERGM pipeline fixes this post-hoc; `bilateral_trade_wto.csv` itself is not modified.

---

### 4.3 Bilateral Trade Section Dataset (`bilateral_trade_section_wto.csv`)

No missing values in any column.

---

### 4.4 ERGM Datasets

Systematic missing data in `ergm_dyad_year_eun.csv` and `ergm_dyad_year_eu_disagg.csv`:

| Variable Group | Affected Rows / % | Reason |
|----------------|-------------------|--------|
| **Trade lags** `*_t1/t2/t3` | 1995 rows: 100% NaN; 1996: t-2/t-3 imputed; 1997: t-3 imputed | No pre-1995 BACI data; backward imputation applied (see Section 5.5) |
| **UN ideal points** `idealpointfp_*`, `idealpointall_*`, `idealpointlegacy_*` | Taiwan (TAW), HK (HKG), Macao (MAC), EU (EUN): all years NaN | Not UN members |
| **V-Dem** `v2x_polyarchy_*`, `v2x_libdem_*`, `v2x_regime_*` | EU, HK, MAC, micro-states: all years NaN | Outside V-Dem coverage |
| **CINC** `cinc_*` | All countries 2017–2024: NaN | NMC v6.0 ends 2016 |
| **WGI** `voice_*`, `stability_*`, etc. | EUN before aggregation; North Korea; very small states | Not covered by WGI |
| **WDI** `gdppc_*`, `log_gdppc_*`, `pop_*` | ~4.4% NaN | Non-reporting states (North Korea, Syria, Somalia); EUN filled by member-state aggregation |
| **Severity** `severity_max`, `severity_avg`, `dyadic_severity_*` | DS627–DS644 (18 cases): NaN | No PDF documents; RAG pipeline covers DS1–DS626 only |
| **TP-R severity** (`dyadic_severity` = 0.5) | All `third_party-respondent` rows | Placeholder pending third-party scoring completion |
| **Disputed sector trade** `disputed_trade_*` | Rows without disputes: NaN (by design) | Only populated for has_dispute=1 rows |

> **ERGM behavior:** Most ERGM implementations (R `ergm`, `btergm`) drop nodes/edges with missing covariates. For cross-sectional ERGM at a single year, restrict to that year's rows and assess missing data before modeling.

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

- `complainant`, `respondent`, `third_party` are binary indicators constructed from `wto_cases_v2.csv` (644 cases DS1–DS644): 1 if the country participated in at least one dispute of that type in that year, 0 otherwise.
- `cum_complainant`, `cum_respondent`, `cum_third_party` are cumulative counts from 1995 through year t (inclusive).
- The EU is treated as a single litigation actor (`EUN`). Individual EU member states may also appear separately in early cases (see Section 5.7).
- **ERGM note:** For the ERGM datasets, annual activity counts (`n_complainant_t`, `n_respondent_t`, `n_tp_t`) are computed directly from `wto_dyadic_v2.csv` and merged alongside the cumulative `cum_*` variables. The annual counts capture how many distinct cases a country was involved in that specific year.

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

**EUN DESTA data gap:** DESTA records EU trade agreements through individual member state pairs (e.g., the EU-Korea FTA appears as DEU→KOR "EC Korea"). As a result, all EUN rows in `bilateral_trade_wto.csv` have `label=0`. The ERGM pipeline (`build_ergm_data.py`) fixes this by propagating `label=1` to EUN rows whenever any EU member state has a trade agreement with the partner country in that year. The fix is applied in `ergm_dyad_year_eun.csv` and `ergm_dyad_year_eu_disagg.csv` only; `bilateral_trade_wto.csv` itself is unchanged.

**EUN ATOP data:** EUN has `atopally=0` for all rows. This is correct — the European Union as a collective entity is not an ATOP signatory. Individual EU member states (e.g., DEU, FRA) have their own ATOP entries (primarily NATO membership).

**EUN node attributes:** EUN has NaN for all economic (WDI), political (V-Dem, UN Voting, WGI), and military (NMC) variables in `country_meta_1995_2024.csv`. Only WTO participation variables (`wto_member`, `cum_*`) are populated. The ERGM pipeline aggregates EUN attributes from individual EU member states: sum for `pop`; GDP-weighted average for all other numeric variables.

---

### 5.7 EU Disaggregation Rules for ERGM Datasets

Three categories of EU involvement in `wto_dyadic_v2.csv` require different handling in `ergm_dyad_year_eu_disagg.csv`:

| Category | Count | Example | Rule |
|----------|-------|---------|------|
| **EUN-only** — only EUN is listed as party | 395 cases | DS2 (USA vs EUN) | Expand EUN → all individual EU member states in that year from `eu_membership_1995_2024.csv`. Dispute flags propagated to each member's bilateral_trade_wto row. |
| **Mixed** — both EUN and individual EU members listed | 37 cases | DS316 (Airbus: USA vs EUN, FRA, DEU, ESP, GBR) | Drop EUN rows; keep individual member rows. They are already present and correctly populated. |
| **Individual-EU-only** — individual EU members listed, no EUN | 30 cases | DS37 (USA vs PRT) | Keep as-is. These reflect early WTO practice before EU was consistently a single actor. |

> **Interpretation note:** EU disaggregation is a robustness check. The primary analysis should use `ergm_dyad_year_eun.csv` (EUN as unitary actor), which reflects how WTO disputes are actually filed.

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

## 7. ERGM Analysis Datasets

Constructed by `scripts/build_ergm_data.py` and `DataConstruction.ipynb`. See README for full methodology.

### 7.1 `wto_cases_enriched.csv`

| Attribute | Value |
|-----------|-------|
| Unit | Case |
| Rows | 644 |
| Primary key | `case_id` (integer) |

`wto_cases_v2` joined with `severity_scores_raw` and `case_hs_sections`. Adds `consultation_year`, `is_horizontal_policy`, and severity/HS columns. Cases DS627–DS644 have NaN for severity and HS columns.

### 7.2 `wto_dyadic_enriched.csv`

| Attribute | Value |
|-----------|-------|
| Unit | Case-directed dyad |
| Rows | 8,373 |
| Primary key | `(case, iso3_1, iso3_2, relationship)` |

`wto_dyadic_v2` joined with case attributes. Key added columns:

| Variable | Definition |
|----------|-----------|
| `consultation_year` | Year extracted from `consultations_requested` |
| `dyadic_severity` | Severity by role: CR→case score; TP-R→0.5; C-TP→0 |
| `is_horizontal_policy` | True for policy cases spanning all 21 HS sections |
| `disputed_trade_ij_t{0..3}` | Trade from country1→country2 in disputed HS sections at t, t-1, t-2, t-3 |
| `disputed_trade_ji_t{0..3}` | Trade from country2→country1 in disputed HS sections |
| `disputed_dep_ij_t{0..3}` | Partner sector dependence for country1 exports to country2 in disputed sections |

### 7.3 `ergm_dyad_year_eun.csv`

| Attribute | Value |
|-----------|-------|
| Unit | Directed dyad-year (exporter → importer) |
| Rows | ~545,333 |
| Universe | `bilateral_trade_wto` (all WTO-member pairs, 1995–2024) |

Key variable groups:

| Group | Variables |
|-------|-----------|
| **Outcome** | `has_dispute`, `dispute_count`, `case_id_max`, `case_id_avg` |
| **Severity** | `severity_max`, `severity_avg`, `dyadic_severity_max`, `dyadic_severity_avg` |
| **HS sections** | `section_1` … `section_21` (dummies from most severe case) |
| **Trade (contemporaneous)** | `total_trade_ij`, `export_dependence`, `atopally`, `label`, `depth_index` (from `bilateral_trade_wto`) |
| **Trade lags** | `total_trade_ij_t{1..3}`, `export_dependence_t{1..3}`, `atopally_t{1..3}`, `label_t{1..3}` |
| **Disputed sector trade** | `disputed_trade_ij_t{0..3}`, `disputed_trade_ji_t{0..3}` |
| **Node attrs (exporter)** | 44 cols from `country_meta`, suffixed `_1`: `gdppc_1`, `pop_1`, `v2x_polyarchy_1`, `idealpointall_1`, `cum_complainant_1`, `n_complainant_t_1`, etc. |
| **Node attrs (importer)** | Same 44 cols suffixed `_2` |
| **TP covariates** | `tp_with_j_complainant_i` (has i acted as TP supporting j's complaints), `tp_count_i_supporting_j` |

> **Backward imputation (trade only):** 1995 → all NaN; 1996 → t-2=t-3=t-1; 1997 → t-3=t-2. Node attributes use contemporaneous year t.

> **Taiwan:** NaN for `idealpointfp_*`, `idealpointall_*`, `idealpointlegacy_*` (not a UN member).

> **EUN DESTA fix:** EUN rows inherit trade agreement data from member states. EUN ATOP = 0 by design (EU is not an ATOP signatory).

### 7.4 `ergm_dyad_year_eu_disagg.csv`

EU-disaggregated robustness version. EUN dispute rows replaced by individual EU member state rows:
- **395 EUN-only cases**: expanded to individual EU member state rows present in `bilateral_trade_wto`
- **37 mixed cases** (EUN + individual members both listed): EUN rows dropped, individual member rows kept
- **30 individual-EU-member-only cases**: unchanged

---

*End of documentation.*
