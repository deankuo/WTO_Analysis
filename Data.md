# Dataset Documentation — WTO Dispute Analysis

**Last Updated:** March 2026
**Maintainer:** Dean Kuo

---

## Table of Contents

1. [Panel Dataset: `country_meta_1995_2024.csv`](#1-panel-dataset-country_meta_1995_2024csv)
   - [Panel Structure](#panel-structure)
   - [A. Identifiers](#a-identifiers)
   - [B. WTO Membership & Participation](#b-wto-membership--participation)
   - [C. EU / Eurozone Membership](#c-eu--eurozone-membership)
   - [D. UN Voting Ideal Points](#d-un-voting-ideal-points)
   - [E. V-Dem Democracy Indicators](#e-v-dem-democracy-indicators)
   - [F. World Development Indicators (WDI) — Economic](#f-world-development-indicators-wdi--economic)
   - [G. Worldwide Governance Indicators (WGI)](#g-worldwide-governance-indicators-wgi)
   - [H. Geographic & Classification Variables](#h-geographic--classification-variables)
   - [I. Derived Variables](#i-derived-variables)
   - [J. COW National Material Capabilities (NMC)](#j-cow-national-material-capabilities-nmc)
2. [Systematic Missing Data](#2-systematic-missing-data)
3. [Data Processing & Construction Notes](#3-data-processing--construction-notes)
4. [WTO Dispute Analysis Results](#4-wto-dispute-analysis-results)
5. [Dyads Dataset (Forthcoming)](#5-dyads-dataset-forthcoming)
6. [Bilateral Trade Datasets](#6-bilateral-trade-datasets)
7. [BACI Code Mapping](#7-baci-code-mapping)
8. [EU Membership Panel](#8-eu-membership-panel)

---

## 1. Panel Dataset: `country_meta_1995_2024.csv`

### Panel Structure

| Attribute | Value |
|-----------|-------|
| Unit of analysis | Country-year |
| Rows | 5,880 |
| Countries / Polities | 196 |
| Year range | 1995–2024 (30 years) |
| Primary key | `(country, year)` |

The dataset integrates six major data sources into a balanced country-year panel covering all WTO-relevant polities (WTO members, observers, and non-members that appear in WTO dispute records), plus the EU as a collective actor.

---

### A. Identifiers

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

### B. WTO Membership & Participation

**Source:** WTO official membership records (<https://www.wto.org/english/thewto_e/whatis_e/tif_e/org6_e.htm>) and `wto_cases.csv` dispute data (626 cases, 1995–2024).

| Variable | Definition | Unit / Range | Notes |
|----------|-----------|--------------|-------|
| `wto_member` | Whether the country is a WTO member in that year | Binary (0/1) | Grows from 112 (1995) to 166 (2024) |
| `wto_accession_year` | Year of WTO accession | Integer; 1995–2024 | `NaN` for non-members (900 obs) |
| `complainant` | Country initiated at least one WTO dispute in that year | Binary (0/1) | Derived from dispute case records |
| `respondent` | Country was respondent in at least one dispute in that year | Binary (0/1) | Derived from dispute case records |
| `third_party` | Country joined as third party in at least one dispute in that year | Binary (0/1) | Derived from dispute case records |
| `wto_participant` | Any WTO dispute activity (complainant OR respondent OR third party) | Binary (0/1) | `= complainant OR respondent OR third_party` |
| `cum_complainant` | Cumulative number of disputes initiated (1995–that year) | Integer; 0–25 | US and EU both reach 25 by 2024 |
| `cum_respondent` | Cumulative number of disputes faced as respondent | Integer; 0–29 | US reaches 29, EU reaches 29 |
| `cum_third_party` | Cumulative number of third-party appearances | Integer; 0–30 | US reaches 30 |

---

### C. EU / Eurozone Membership

**Source:** European Union official membership records; European Central Bank Eurozone records.

| Variable | Definition | Unit / Range | Notes |
|----------|-----------|--------------|-------|
| `eu_member` | Whether the country was an EU member in that year | Binary (0/1) | 28 distinct countries ever member |
| `euro_join_year` | Year the country adopted the Euro | Integer; 1999–2023 | `NaN` for non-Euro countries (89.8% missing) |
| `euro_member` | Whether the country used the Euro in that year | Binary (0/1) | Derived from `euro_join_year` |

> **Note:** The EU itself (`EU` row) is also coded as an actor since it litigates as a single entity in WTO disputes.

---

### D. UN Voting Ideal Points

**Source:** Bailey, Michael A., Anton Strezhnev, and Erik Voeten. 2017. "Estimating Dynamic State Preferences from United Nations Voting Data." *Journal of Conflict Resolution* 61(2): 430–456.
**Data version:** July 28, 2025 (Erik Voeten, Georgetown University).
**Raw data provider:** Fjelstul, Joshua, Simon Hug, and Christopher Kilby. 2025. "Decision-making in the United Nations General Assembly: A comprehensive database of resolution-related decisions." *The Review of International Organizations* 1–18. (<https://unvotes.unige.ch/>)

The ideal points are estimated using a Bayesian Item Response Theory (IRT) model fit to UNGA voting records. Higher values indicate alignment with the US; lower values indicate alignment with Russia/China (per the scaling convention). The model produces a posterior distribution; quantiles are provided to capture estimation uncertainty.

#### D.1 Ideal Point Estimates

| Variable | Definition | Unit / Range | Notes |
|----------|-----------|--------------|-------|
| `idealpointfp` | Ideal point based on **final-passage votes only** | Continuous; approx. –2.1 to +3.0 | Preferred for most analyses; excludes paragraph/amendment votes |
| `idealpointall` | Ideal point based on **all votes** (including paragraph and amendment votes) | Continuous; approx. –2.4 to +3.1 | More comprehensive; may reflect overrepresentation of specific issue areas (e.g., Gaza) |
| `idealpointlegacy` | Ideal point from the legacy session-based estimation (year = session + 1945, all votes) | Continuous; approx. –2.2 to +3.2 | Correlates with `idealpointall` at *r* = 0.988; provided for backward compatibility |

#### D.2 Vote Counts

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `nvotesfp` | Number of final-passage votes the FP ideal point is based on | Integer; 1–109 |
| `nvotesall` | Number of all votes the ALL ideal point is based on | Integer; 1–232 |
| `nvotesLegacy` | Number of votes for the legacy session-based estimation | Integer; 1–96 |

#### D.3 Posterior Quantiles (Final-Passage Model)

These quantiles from the MCMC posterior distribution allow propagating uncertainty about ideal point estimates into statistical models.

| Variable | Definition |
|----------|-----------|
| `qofp` | Posterior mean (equivalent to `idealpointfp`) |
| `q5fp` | 5th percentile of posterior |
| `q10fp` | 10th percentile of posterior |
| `q50fp` | Posterior median |
| `q90fp` | 90th percentile of posterior |
| `q95fp` | 95th percentile of posterior |
| `q100fp` | Maximum of posterior draws |

#### D.4 Posterior Quantiles (All-Votes Model)

| Variable | Definition |
|----------|-----------|
| `qoall` | Posterior mean (equivalent to `idealpointall`) |
| `q5all` | 5th percentile of posterior |
| `q10all` | 10th percentile of posterior |
| `q50all` | Posterior median |
| `q90all` | 90th percentile of posterior |
| `q95all` | 95th percentile of posterior |
| `q100all` | Maximum of posterior draws |

> **Range note:** All quantile variables share the approximate range of their parent ideal point variable (–2.4 to +3.7 at the extremes).

---

### E. V-Dem Democracy Indicators

**Source:** Coppedge, Michael, John Gerring, Carl Henrik Knutsen, Staffan I. Lindberg, Jan Teorell, et al. 2025. "V-Dem Codebook v15." Varieties of Democracy (V-Dem) Project, University of Gothenburg.

V-Dem is a large-scale expert-coded dataset measuring democratic institutions and practices. Variables prefixed `v2x_` are high-level aggregated indices (0–1 scale); variables prefixed `v2el` capture election-specific characteristics.

#### E.1 Democracy Indices

| Variable | Definition | Unit / Range | V-Dem Reference |
|----------|-----------|--------------|-----------------|
| `v2x_polyarchy` | **Electoral Democracy Index** — the extent to which ideal electoral democracy is achieved. Aggregates freedom of expression, association, clean elections, elected officials, and suffrage. | Continuous; 0 (least) – 1 (most) | v15 Codebook, p. 37 |
| `v2x_libdem` | **Liberal Democracy Index** — electoral democracy combined with protections of individual and minority rights against state and majority. | Continuous; 0 (least) – 1 (most) | v15 Codebook, p. 38 |

#### E.2 Regime Classification

| Variable | Definition | Values | V-Dem Reference |
|----------|-----------|--------|-----------------|
| `v2x_regime` | **Regime type** ordinal classification | 0 = Closed Autocracy; 1 = Electoral Autocracy; 2 = Electoral Democracy; 3 = Liberal Democracy | v15 Codebook, p. 291 |

#### E.3 Election Variables

These variables capture whether a particular type of election was held in a given year. **Note:** `NaN` means no election of any type occurred that year (74.7% of obs), not missing data — these are only populated in election years.

| Variable | Definition | Values |
|----------|-----------|--------|
| `v2eltype_0` | **Legislative election** held | 1 = yes, 0 = no, `NaN` = no election year |
| `v2eltype_1` | **Presidential election** held | 1 = yes, 0 = no, `NaN` = no election year |
| `v2eltype_6` | **Constituent assembly election** held | 1 = yes, 0 = no, `NaN` = no election year |
| `v2eltype_7` | **Other executive election** held | 1 = yes, 0 = no, `NaN` = no election year |
| `is_leg_elec` | Any legislative election in that year | Binary (0/1); `NaN` if no COW match |
| `is_pres_elec` | Any presidential election in that year | Binary (0/1); `NaN` if no COW match |
| `election_binary` | Any election (legislative or presidential) in that year | Binary (0/1); `NaN` if no COW match |

---

### F. World Development Indicators (WDI) — Economic

**Source:** World Bank, World Development Indicators (WDI). Accessed 2025.
(<https://databank.worldbank.org/source/world-development-indicators>)

Taiwan economic data manually supplemented from:
- **GDP / GDP per capita / growth:** Directorate-General of Budget, Accounting and Statistics, Executive Yuan (DGBAS), Taiwan.
- **FDI inflows:** UNCTAD Global Investment Data.

**Unit standardization:** All monetary values originally in USD were divided by 1,000,000 → **Million USD**. All WDI percentage values (e.g., `5.2` meaning 5.2%) were divided by 100 → **Ratio (0–1)**.

| Variable | WDI Code | Definition | Unit | Range |
|----------|----------|-----------|------|-------|
| `gdp` | `NY.GDP.MKTP.KD` | Real GDP (constant 2015 USD) | Million USD | 23.6 – 22,568,000 |
| `gdppc` | `NY.GDP.PCAP.KD` | Real GDP per capita (constant 2015 USD) | USD | 211 – 247,170 |
| `pop` | `SP.POP.TOTL` | Total population | Count | 9,280 – 1,450,900,000 |
| `gdp_growth_rate` | `NY.GDP.MKTP.KD.ZG` | Annual GDP growth rate | Ratio (0–1) | –0.503 – 1.500 |
| `trade` | `NE.TRD.GNFS.ZS` | Total trade (exports + imports) as % of GDP | Ratio (0–1) | 0.00021 – 4.373 |
| `fdi` | `BX.KLT.DINV.WD.GD.ZS` | Net FDI inflows as % of GDP | Ratio (0–1) | –1,303 – 1,283 |
| `fdi_inflow_usd` | `BX.KLT.DINV.CD.WD` | Net FDI inflows (absolute) | Million USD | –343,400 – 733,830 |
| `exp_share` | `NE.EXP.GNFS.ZS` | Exports of goods and services as % of GDP | Ratio (0–1) | 0.000054 – 2.290 |
| `imp_share` | `NE.IMP.GNFS.ZS` | Imports of goods and services as % of GDP | Ratio (0–1) | 0.000156 – 2.083 |
| `unemployment_rate` | `SL.UEM.TOTL.NE.ZS` | Unemployment rate (national estimate) | Ratio (0–1) | 0.00039 – 0.388 |

> **Note on FDI:** The `fdi` ratio can exceed ±100% and even ±1000% for very small economies with large FDI flows (e.g., Luxembourg, Ireland); this is mathematically correct but an outlier concern for modeling.

---

### G. Worldwide Governance Indicators (WGI)

**Source:** Kaufmann, Daniel, Aart Kraay, and Massimo Mastruzzi. 2010. "The Worldwide Governance Indicators: Methodology and Analytical Issues." *World Bank Policy Research Working Paper* No. 5430.
(<https://info.worldbank.org/governance/wgi/>)

Taiwan WGI data supplemented from the World Bank WGI Interactive Data Access tool (labeled "Taiwan, China").

All six WGI indicators are measured on a standard normal distribution scale (–2.5 to +2.5), where higher values indicate better governance.

| Variable | WGI Code | Definition | Unit / Range |
|----------|----------|-----------|--------------|
| `voice` | `VA.EST` | **Voice and Accountability** — extent to which citizens can participate in selecting government; freedom of expression, association, and press. | Score; –2.31 to +1.80 |
| `stability` | `PV.EST` | **Political Stability and Absence of Violence/Terrorism** — likelihood of political instability or politically motivated violence. | Score; –3.18 to +1.76 |
| `efficiency` | `GE.EST` | **Government Effectiveness** — quality of public services, civil service, and policy formulation. | Score; –2.44 to +2.47 |
| `reg_quality` | `RQ.EST` | **Regulatory Quality** — ability to formulate sound policies that promote private sector development. | Score; –2.53 to +2.31 |
| `law` | `RL.EST` | **Rule of Law** — confidence in and adherence to rules, contract enforcement, property rights, courts. | Score; –2.33 to +2.12 |
| `corruption` | `CC.EST` | **Control of Corruption** — extent to which public power is exercised for private gain. | Score; –1.97 to +2.46 |

#### WGI Interpolation

WGI was not published annually in early years:
- **1995:** Filled with 1996 values (backward fill).
- **1997, 1999, 2001:** Linearly interpolated from adjacent survey years (e.g., 1997 = average of 1996 and 1998).

---

### H. Geographic & Classification Variables

**Source:** World Bank WDI Extra fields; user-defined for non-WDI entities (Taiwan, EU, etc.).

| Variable | Definition | Values / Unit |
|----------|-----------|---------------|
| `region` | World Bank geographic region | `East Asia & Pacific`, `Europe & Central Asia`, `Latin America & Caribbean`, `Middle East & North Africa`, `North America`, `South Asia`, `Sub-Saharan Africa`; `NaN` for EU (120 obs) |
| `longitude` | Geographic centroid longitude | Decimal degrees; –175.2 to +179.1 |
| `latitude` | Geographic centroid latitude | Decimal degrees; –41.3 to +121.0 |
| `income` | World Bank income group classification | `Low income`, `Lower middle income`, `Upper middle income`, `High income`, `Not classified`; `NaN` for EU (120 obs) |

---

### I. Derived Variables

Constructed within the project; not sourced externally.

| Variable | Definition | Formula | Range |
|----------|-----------|---------|-------|
| `log_gdppc` | Natural log of real GDP per capita | `ln(gdppc)` | 5.35 – 12.42 |
| `log_pop` | Natural log of total population | `ln(pop)` | 9.14 – 21.10 |

---

### J. COW National Material Capabilities (NMC)

**Source:** Singer, J. David, Stuart Bremer, and John Stuckey. 1972. "Capability Distribution, Uncertainty, and Major Power War, 1820–1965." In *Peace, War and Numbers*, ed. Bruce Russett. Beverly Hills: Sage Publications.
**Dataset version:** NMC 6.0 (1816–2016). Hosted by J. Michael Greig and Andrew J. Enterline, University of North Texas. Updated June 28, 2021.
**Codebook:** `COW/NMC_Documentation_v6_0_final_v2.pdf`

> **Critical coverage note:** NMC v6.0 covers **1816–2016 only**. All observations for **2017–2024 are `NaN`** for all NMC variables (1,568 missing observations across all 196 countries × 8 years).

| Variable | Definition | Unit | Range | NMC Notes |
|----------|-----------|------|-------|-----------|
| `cinc` | **Composite Index of National Capability (CINC)** — unweighted average of six capability shares (milex, milper, irst, pec, tpop, upop) in a given year. Each component share sums to 1.0 across all states. | Proportion; 0–1 | 2.44×10⁻⁷ – 0.231 | Codebook p. 4: "CINC is the average of a state's share of the system total for each of the six capability components." |
| `milex` | Military expenditures | Thousands USD (post-1914); thousands GBP (pre-1914) | –9 to 693,600,000 | Missing coded –9 in raw data; converted to `NaN` here |
| `milper` | Military personnel | Thousands of persons | –9 to 2,930 | Missing coded –9; from ACDA (1961–1999) |
| `pec` | Primary energy consumption | Thousands of coal-ton equivalents | –9 to 5,900,300 | Missing coded –9 |
| `tpop` | Total population | Thousands of persons | 9 to 1,403,500 | Parallel to WDI `pop` but in different units |
| `upop` | Urban population (cities >100k; >300k after 2002) | Thousands of persons | 0 to 612,930 | Threshold changed in 2002 |

> **Note on sentinel values:** The COW raw data uses **–9** to denote missing values for `milex`, `milper`, `pec`, `tpop`, and `upop`. These have been retained as-is in this dataset; analysts should recode to `NaN` before modeling.

---

## 2. Systematic Missing Data

This section documents which countries or polities are **systematically absent** from each data source, and the reason why.

### 2.1 UN Voting Ideal Points

**Countries entirely missing (`idealpointfp` = `NaN` for all 30 years):**

| Polity | Reason |
|--------|--------|
| **Taiwan** | Not a UN member (expelled 1971, replaced by PRC). No UNGA voting record. |
| **Hong Kong** | Not a sovereign state; votes subsumed under China (PRC). |
| **Macao, China** | Same as Hong Kong; not a sovereign state. |
| **EU** | Not a UN member state. EU speaks in UNGA but does not vote as a single member. |

**Countries partially missing** (missing for some years due to non-membership or irregular participation):
Afghanistan, Bosnia & Herzegovina, Burundi, Cambodia, Dominican Republic, Gambia, Guinea-Bissau, Iraq, Kiribati, Kyrgyzstan, Liberia, Mauritania, Montenegro, Nauru, Niger, Palau, Sao Tome and Principe, Seychelles, Somalia, South Sudan, Switzerland (observer until 2002), Tajikistan, Timor-Leste, Tonga, Tuvalu, Uzbekistan, Vanuatu, Venezuela (gaps in some years).

### 2.2 V-Dem Democracy Indices

**Countries entirely missing (`v2x_polyarchy` = `NaN` for all 30 years):**

| Polity | Reason |
|--------|--------|
| **EU** | Supranational entity; V-Dem covers sovereign states only. |
| **Hong Kong** | Special Administrative Region (SAR); covered as part of China. |
| **Macao, China** | SAR; covered as part of China. |
| **Andorra, Monaco, San Marino, Liechtenstein** | Micro-states; excluded from V-Dem v15 universe. |
| **Antigua and Barbuda, Bahamas, Barbados (partial), Belize, Dominica, Grenada, Saint Kitts and Nevis, Saint Lucia, Saint Vincent and the Grenadines** | Small Caribbean island states; below COW system membership threshold or not coded. |
| **Brunei Darussalam** | Not in V-Dem state universe for this period. |
| **Kiribati, Marshall Islands, Micronesia (Fed. States), Nauru, Palau, Samoa, Tonga, Tuvalu** | Small Pacific island states; below V-Dem coverage threshold. |
| **South Sudan** | Newly independent (2011); limited early coverage. |
| **Montenegro** | Independent from 2006; limited historical coverage before COW entry. |

### 2.3 COW National Material Capabilities (NMC)

**Temporal gap — 2017–2024 (all countries):**
NMC v6.0 data ends in 2016. All 196 countries have `NaN` for all NMC variables from 2017 onward (1,568 missing observations).

**Countries with additional historical gaps (1995–2016):**

| Polity | Reason |
|--------|--------|
| **EU** | Not a sovereign state in the COW system. |
| **Hong Kong, Macao, China** | Not sovereign states; subsumed under China. |
| **Andorra, Monaco, San Marino, Liechtenstein** | Micro-states below COW system membership threshold. |
| **South Sudan** | Not independent until 2011; limited early coverage. |
| **Montenegro** | Not independent until 2006. |
| Various small island states | Below COW minimum population/sovereignty threshold. |

### 2.4 World Development Indicators (WDI)

**Countries with substantial WDI gaps:**

| Polity | Reason |
|--------|--------|
| **North Korea** | No WDI reporting; international sanctions, data isolation. |
| **Syria** | Post-2011 conflict severely disrupted data reporting. |
| **Somalia** | Prolonged state fragility; limited statistical capacity. |
| **South Sudan** | Newly independent (2011); early years lack data. |
| **Lebanon** | Severe economic crisis (2019–) disrupted data. |
| **EU** | WDI covers member states, not the EU as a supranational entity. |
| **Liechtenstein, Monaco, San Marino** | Small states not covered by WDI. |
| **Hong Kong, Macao, China** | Covered under separate WDI codes (`HKG`, `MAC`) but mapped here with gaps. |
| **Taiwan** | Not a WDI member; data supplemented from DGBAS. |

**`unemployment_rate`** has elevated missingness (42.8%) due to many developing countries not reporting national unemployment estimates to the ILO.

**`trade`, `exp_share`, `imp_share`** missing for 18.1% of observations, concentrated in small island states and conflict-affected countries.

### 2.5 WGI Governance Indicators

Missing ~5–9% of observations. Systematic gaps include:
- **North Korea**: Not covered.
- **Very small island states** (Kiribati, Nauru, Tuvalu, Palau, etc.): Partial coverage.
- **EU**: Not applicable.
- **Early years (1995–1997)**: Filled via interpolation (see Section 3).

---

## 3. Data Processing & Construction Notes

### 3.1 Unit Standardization

| Transformation | Details |
|----------------|---------|
| GDP / FDI monetary values | Divided by 1,000,000 → Million USD |
| WDI percentage variables | Divided by 100 → Ratio (0–1); applies to `trade`, `fdi`, `exp_share`, `imp_share`, `unemployment_rate`, `gdp_growth_rate` |
| COW NMC sentinel values | Raw –9 values retained; should be recoded to `NaN` before use |

### 3.2 WGI Interpolation for Missing Years

WGI surveys were not conducted annually before 2002:
- **1995**: Backfilled using 1996 data.
- **1997**: Linear interpolation of 1996 and 1998.
- **1999**: Linear interpolation of 1998 and 2000.
- **2001**: Linear interpolation of 2000 and 2002.

### 3.3 WTO Participation Variables

- `complainant`, `respondent`, `third_party` are constructed from `wto_cases.csv` (626 cases).
- The EU is treated as a single litigation actor. Individual EU member states may also appear separately in some cases.
- Cumulative counts (`cum_*`) are inclusive of the current year.

### 3.4 V-Dem Election Variables

- `v2eltype_*` variables are `NaN` in non-election years (not missing data).
- `is_leg_elec`, `is_pres_elec`, `election_binary` are derived aggregates that are `NaN` only when V-Dem coverage is entirely absent for that country.

---

## 4. WTO Dispute Analysis Results

The following summarizes outputs from the WTO dispute processing pipeline (9,480 PDFs, 626 cases, 1995–2024).

### 4.1 Case Dataset (`wto_cases.csv`)

- **Cases:** 626 (DS1–DS626)
- **Columns:** 24 (case number, complainant, respondent, third parties, title, summary, agreements cited, key procedural dates, dispute stage)

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

**Top 10 Complainants (cumulative through 2024):**

| Country | Cases Filed |
|---------|------------|
| U.S. | 120 |
| EU | 110 |
| Canada | 38 |
| Brazil | 33 |
| Japan | 27 |
| China | 25 |
| India | 22 |
| Argentina | 22 |
| Mexico | 21 |
| South Korea | 20 |

**Top 10 Respondents (cumulative through 2024):**

| Country | Cases Faced |
|---------|------------|
| U.S. | 159 |
| EU | 89 |
| China | 49 |
| India | 32 |
| Canada | 23 |
| Argentina | 22 |
| South Korea | 19 |
| Australia | 17 |
| Brazil | 17 |
| Japan | 16 |

### 4.2 Document Processing Statistics

| Metric | Value |
|--------|-------|
| Total PDFs processed | 9,480 |
| Successfully classified | 9,398 (99.1%) |
| Manual review required | 82 files |
| — Scanned (OCR) | 78 |
| — Non-English | 3 |
| — Other errors | 1 |
| Document types (consolidated) | 35 |
| Date coverage | ~90% |

### 4.3 Network Analysis Results (`wto_analysis_results_1995-2024.json`)

Annual cumulative network metrics (conflict-weighted dispute graph where nodes = countries, edges = dispute relationships):

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

**Key metrics:**
- `conflict_density`: Share of possible adversarial edges that exist
- `support_ratio`: Proportion of edges that are cooperative (third-party support) vs. adversarial
- `modularity`: Community structure strength (Louvain algorithm on signed network)
- `community_count`: Number of detected communities per year

Network structure data available in:
- `wto_analysis_results_1995-2024.json` — per-year: `basic_stats`, `network_metrics`, `community_roles`, `centrality`
- `wto_network_analysis_1995-2024.json` — per-year: `basic_stats`, `network_metrics`, `year_summary`

### 4.4 Harmonized Case Dataset (`wto_cases_harmonized.csv`)

Harmonized version of case data with standardized country names for network analysis. Used as the primary input for building the country-year panel.

---

## 5. Dyads Dataset (Forthcoming)

> **Status:** Under construction. Structure documented below as a placeholder.

The dyads dataset will be a **directed country-pair-year** panel capturing bilateral trade, formal alliances, trade agreement depth, political alignment, and dispute history between all WTO-relevant country pairs.

### 5.1 Planned File

**Filename:** `dyads_1995_2024.csv`
**Unit of analysis:** Directed dyad-year `(country_A → country_B, year)`
**Estimated rows:** ~600,000 (196 × 195 directed pairs × 30 years, filtered to WTO-relevant dyads)

### 5.2 Planned Variable Groups

| Group | Planned Variables | Source |
|-------|------------------|--------|
| **Identifiers** | `iso3c_A`, `iso3c_B`, `year`, `ccode_A`, `ccode_B`, `dyad_id` | — |
| **WTO Dispute History** | `dispute_AB`, `dispute_BA`, `third_party_AB`, `cum_disputes_AB` | `wto_cases.csv` |
| **Bilateral Trade** | `export_value_AB`, `import_value_AB`, `bilateral_trade_total`, `log_trade` | CEPII BACI |
| **Trade Agreement** | `pta_dummy`, `pta_depth_rasch`, `pta_depth_type`, `desta_number` | World Bank DTA / DESTA |
| **Military Alliance** | `atop_ally`, `atop_defense`, `atop_offense`, `atop_nonagg`, `atop_consul` | ATOP v5.1 |
| **UN Voting Alignment** | `ideal_distance_fp`, `s_score` | Voeten 2025 |
| **Bilateral GDP** | `log_gdp_product`, `log_gdp_ratio` | WDI (from node panel) |
| **Contiguity / Geography** | `contiguous`, `log_distance` | COW / CEPII GeoDist |

---

### 5.3 Source 1 — CEPII BACI (Bilateral Trade Flows)

**Source:** Gaulier, Guillaume, and Soledad Zignago. 2010. "BACI: International Trade Database at the Product-Level. The 1994–2007 Version." *CEPII Working Paper* No. 2010-23. Centre d'Études Prospectives et d'Informations Internationales (CEPII).
**Dataset:** BACI HS02, HS07, or HS17 edition (depending on year coverage needed).
**Access:** <http://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37>

BACI (Base pour l'Analyse du Commerce International) reconciles importer and exporter reports from the UN Comtrade database using a cost, insurance, and freight (CIF) / free on board (FOB) harmonization procedure. It is the standard source for bilateral trade flows in gravity models.

#### Raw BACI Structure (one row = exporter × importer × HS6-product × year)

| Raw Variable | Definition | Unit |
|---|---|---|
| `t` | Year | Integer |
| `i` | Exporter country code (BACI/ISO numeric) | Integer |
| `j` | Importer country code | Integer |
| `k` | HS 6-digit product code | String |
| `v` | Trade value | Thousands USD |
| `q` | Quantity | Metric tons |

#### Planned Aggregation to Dyad-Year Level

Raw HS6-product flows will be collapsed to the **country-pair-year** level:

| Constructed Variable | Definition | Formula |
|---|---|---|
| `export_value_AB` | Total exports from A to B in year *t* | Sum of `v` across all HS6 codes |
| `import_value_AB` | Total imports A receives from B in year *t* | Same as `export_value_BA` |
| `bilateral_trade_total` | Total bilateral trade (A→B + B→A) | `export_value_AB + import_value_AB` |
| `log_trade` | Log bilateral trade | `ln(bilateral_trade_total + 1)` |

#### Systematic Coverage Gaps

| Polity | Reason |
|--------|--------|
| **Taiwan** | Reported under code `490` (Taipei, Chinese) in Comtrade; requires remapping |
| **Hong Kong, Macao** | Reported separately as re-export hubs; trade flows may double-count entrepôt trade |
| **North Korea** | Extremely limited reporting; data unreliable or absent |
| **Small island states** | Partial or absent Comtrade reporting |

---

### 5.4 Source 2 — ATOP v5.1 (Formal Military Alliances)

**Source:** Leeds, Brett Ashley, Jeffrey M. Ritter, Sara McLaughlin Mitchell, and Andrew G. Long. 2002. "Alliance Treaty Obligations and Provisions, 1815–1944." *International Interactions* 28: 237–260.
**Codebook:** Leeds, Brett Ashley. 2022. *Alliance Treaty Obligations and Provisions (ATOP) Codebook v5.1.* Rice University. (<http://www.atopdata.org>)
**Coverage:** 1815–2018 (765 alliances). All post-2018 dyad-years will be `NaN` for ATOP variables.

#### Files in `Data/ATOP 5.1/`

| File | Description | Rows |
|------|-------------|------|
| `atop5_1dy.csv` | **Dyad-year** (undirected; one row per unique state pair per year) | 136,648 |
| `atop5_1ddyr.csv` | **Directed** dyad-year | — |
| `atop5_1a.csv` | Alliance-level (one row per alliance) | 765 |
| `atop5_1sy.csv` | State-year (one row per state per year) | — |
| `atop5_1m.csv` | Member-level data | — |

#### Key Variables in `atop5_1dy.csv`

| Variable | Definition | Values |
|----------|-----------|--------|
| `dyad` | COW dyad identifier (`mem1 × 1000 + mem2`) | Integer |
| `mem1`, `mem2` | COW numeric country codes for the two states | Integer |
| `year` | Calendar year | Integer; 1815–2018 |
| `atopally` | Any alliance relationship between the dyad | Binary (0/1) |
| `defense` | Mutual defense pact obligation | Binary (0/1) |
| `offense` | Offensive military obligation | Binary (0/1) |
| `neutral` | Neutrality pledge | Binary (0/1) |
| `nonagg` | Non-aggression pact | Binary (0/1) |
| `consul` | Consultation/coordination obligation | Binary (0/1) |
| `bilatno` | Number of bilateral alliances in the dyad | Integer |
| `multino` | Number of multilateral alliances in the dyad | Integer |
| `number` | Total number of alliances | Integer |
| `asymm` | Any asymmetric obligation in alliance | Binary (0/1) |
| `atopid1`–`atopid9` | ATOP IDs of alliances covering this dyad | Integer (up to 9) |

> **Merge note:** ATOP uses COW numeric codes (`mem1`, `mem2`). Join to the node panel via `ccode_A` / `ccode_B`. Dyads involving polities without COW codes (EU, HK, Taiwan, etc.) will have no ATOP match.

#### Systematic Coverage Gaps

| Polity | Reason |
|--------|--------|
| **Post-2018 years** | ATOP v5.1 ends in 2018; 2019–2024 will be `NaN` |
| **EU** | Not a COW state; EU-level defense commitments not in ATOP (NATO captures most EU members) |
| **Taiwan** | Not in COW system; no ATOP entries |
| **Hong Kong, Macao** | Not sovereign states; no ATOP entries |
| **Micro-states** | Below COW minimum threshold |

---

### 5.5 Source 3 — DESTA / World Bank Deep Trade Agreements (PTA Depth)

#### 5.5.1 DESTA

**Source:** Dür, Andreas, Leonardo Baccini, and Manfred Elsig. 2014. "The Design of International Trade Agreements: Introducing a New Dataset." *The Review of International Organizations* 9(3): 353–375.
**Dataset version:** DESTA v2 (Design of Trade Agreements). Available at <https://www.designoftradeagreements.org/>
**File available:** `Data/desta_dyadic.csv` (781 agreements)

DESTA codes the **provisions and depth** of 781 preferential trade agreements signed 1948–2023. Each row is one agreement. The primary depth measure is `mar_typedepth`, a 5-category ordinal scale.

| Variable | Definition | Values |
|----------|-----------|--------|
| `number` | Unique DESTA agreement identifier | Integer |
| `name` | Agreement name | String |
| `year` | Signing year | Integer; 1948–2023 |
| `entryforceyear` | Year agreement entered into force | Float |
| `wto_listed` | Whether notified to the WTO | Binary (0/1) |
| `mar_typedepth` | **PTA type / depth** (ordinal) | 1 = Partial scope; 2 = FTA; 3 = Customs union; 4 = Common market; 5 = Economic union |
| `mar_goods_nt` | National treatment for goods | Binary (0/1) |
| `mar_goods_mfn` | MFN clause for goods | Binary (0/1) |
| `ser_general` | General services liberalization provision | Binary (0/1) |
| `typememb` | Membership type | Categorical |
| `regioncon` | Regional scope | Categorical |

> **Construction note:** `desta_dyadic.csv` is currently agreement-level (781 rows). To construct dyad-year indicators, the dataset must be expanded to list all member-pair combinations for each agreement, then merged to the country-pair-year panel on `(iso3c_A, iso3c_B, year ≥ entryforceyear)`.

#### 5.5.2 World Bank Deep Trade Agreements (DTA)

**Source:** Mattoo, Aaditya, Nadia Rocha, and Michele Ruta, eds. 2020. *The Evolution of Deep Trade Agreements.* Washington, DC: World Bank. (<https://datatopics.worldbank.org/dta/>)

The World Bank DTA database codes 18 policy areas across 280+ PTAs. It extends DESTA with a continuous **Rasch-scaled depth index** (`depth_rasch`) derived from item response theory, comparable across agreements.

| Planned Variable | Definition | Source |
|-----------------|-----------|--------|
| `pta_dummy` | Any PTA in force between dyad in year *t* | DESTA / WB DTA |
| `pta_depth_type` | Ordinal PTA depth (DESTA `mar_typedepth`, 1–5) | DESTA |
| `pta_depth_rasch` | Continuous Rasch-scaled depth index | World Bank DTA |
| `desta_number` | DESTA agreement ID (for traceback) | DESTA |

#### Systematic Coverage Gaps

| Polity | Reason |
|--------|--------|
| **Taiwan** | Some Taiwan PTAs are listed (e.g., ECFA with China), but not systematically coded in DESTA |
| **Hong Kong** | HK–China CEPA covered but HK rarely appears as independent signatory |
| **Pre-1995 agreements** | Agreements in force before WTO establishment included only if still active |
| **Post-2023 agreements** | DESTA v2 ends in 2023 |

---

## 6. Bilateral Trade Datasets

**Source:** BACI HS92 (CEPII), processed by `scripts/build_baci_trade.py`.
**Coverage:** 1995--2024 (30 years).

These datasets use **dual EU representation**: individual EU member states appear with their own trade flows (including intra-EU trade), and a separate `EUN` aggregate node represents the EU acting as a single external trade entity (intra-EU trade excluded). This design reflects the WTO context where the EU litigates as a single actor while member states also have bilateral trade relationships.

> **Note on indices:** Individual members' `total_exports_i` includes intra-EU trade; EUN's `total_exports_i` excludes it. Dependence indices are therefore computed on different bases -- choose the appropriate rows for your analysis.

### 6.1 Dyad-Year Aggregate: `bilateral_trade_aggregate.csv`

**Unit of analysis:** Directed dyad-year (exporter -> importer, year).
**Rows:** ~882,000. **Years:** 1995--2024 (30 years). **Unique exporters:** ~230. **Unique importers:** ~231.

| Variable | Definition | Unit |
|----------|-----------|------|
| `year` | Calendar year | Integer; 1995--2024 |
| `exporter` | Exporter ISO alpha-3 code | String (e.g., `USA`, `FRA`, `EUN`) |
| `exporter_ccode` | Exporter COW numeric code | Integer; `NaN` if not in panel |
| `exporter_name` | Exporter country name | String |
| `importer` | Importer ISO alpha-3 code | String |
| `importer_ccode` | Importer COW numeric code | Integer; `NaN` if not in panel |
| `importer_name` | Importer country name | String |
| `total_trade_ij` | Total exports from i to j | Thousands USD |
| `imports_i_from_j` | Total imports i receives from j (= exports j to i) | Thousands USD |
| `n_products_ij` | Number of distinct HS6 products traded | Integer |
| `n_sections_ij` | Number of distinct HS sections traded | Integer; 1--21 |
| `export_dependence` | `total_trade_ij / total_exports_i` | Ratio (0--1) |
| `import_dependence` | `imports_i_from_j / total_imports_i` | Ratio (0--1) |
| `bilateral_trade_gdp_share` | `total_trade_ij / (gdp_i * 1000)` | Ratio |
| `total_exports_i` | Total exports of exporter i (all destinations) | Thousands USD |
| `total_imports_i` | Total imports of exporter i (from all origins) | Thousands USD |

> **Dependence indices:** `export_dependence` measures how dependent i is on j as an export destination. `import_dependence` measures how dependent i is on j as an import source. Together they capture the asymmetric interdependence structure of a bilateral trade relationship.

> **GDP note:** `bilateral_trade_gdp_share` is `NaN` for `EUN` rows (no aggregate EU GDP in panel) and for countries absent from the panel dataset.

### 6.2 Dyad-Year-Section: `bilateral_trade_by_section.csv`

**Unit of analysis:** Directed dyad-year-section (exporter -> importer, HS section, year).
**Rows:** ~8.9M. **Sections:** 21 HS sections.

| Variable | Definition | Unit |
|----------|-----------|------|
| `year` | Calendar year | Integer; 1995--2024 |
| `exporter` | Exporter ISO alpha-3 code | String |
| `exporter_ccode` | Exporter COW numeric code | Integer; `NaN` if not in panel |
| `importer` | Importer ISO alpha-3 code | String |
| `importer_ccode` | Importer COW numeric code | Integer; `NaN` if not in panel |
| `section_num` | HS section number | Integer; 1--21 |
| `section_en` | HS section English name | String |
| `trade_value_ij_s` | Exports from i to j in section s | Thousands USD |
| `imports_i_from_j_s` | Imports i receives from j in section s (= exports j to i in s) | Thousands USD |
| `n_products_ij_s` | Number of distinct HS6 products in section s | Integer |
| `bilateral_sector_concentration` | `trade_value_ij_s / total_exports_i` | Ratio |
| `sector_export_concentration` | `total_exports_i_s / total_exports_i` | Ratio |
| `export_dependence` | `trade_value_ij_s / total_exports_i_s` | Ratio |
| `import_dependence` | `imports_i_from_j_s / total_imports_i_s` | Ratio |
| `bilateral_sector_gdp_share` | `trade_value_ij_s / (gdp_i * 1000)` | Ratio |
| `total_exports_i` | Total exports of exporter i (all destinations, all sections) | Thousands USD |
| `total_exports_i_s` | Total exports of exporter i in section s (all destinations) | Thousands USD |
| `total_imports_i` | Total imports of exporter i (from all origins, all sections) | Thousands USD |
| `total_imports_i_s` | Total imports of exporter i in section s (from all origins) | Thousands USD |

> **Section-level dependence:** `export_dependence` = within sector s, what share of i's sector exports goes to j. `import_dependence` = within sector s, what share of i's sector imports comes from j. Values of 0 for `import_dependence` indicate no reverse flow in that sector.

### 6.3 EU Representation Details

| Entity type | Rows include | `total_exports_i` basis | Intra-EU trade | GDP merge |
|-------------|-------------|------------------------|----------------|-----------|
| Individual EU member (e.g., `FRA`) | All bilateral flows including intra-EU | All exports including to other EU members | Included (e.g., FRA->DEU) | Merges on member's own GDP |
| EU aggregate (`EUN`) | Only EU external flows | EU external exports only | Excluded | `NaN` (no aggregate EU GDP) |

**Belgium-Luxembourg:** BACI reports Belgium-Luxembourg as a single unit (code 58) until 1998. In the individual pass, code 58 is mapped to Belgium (56). Luxembourg appears individually from 1999 onward.

### 6.4 Entities in Trade Data but Not in Panel

The following ISO3 codes appear in the trade data but have no match in `country_meta_1995_2024.csv`:

| Code | Entity | Reason |
|------|--------|--------|
| `ANT` | Netherlands Antilles | Dissolved 2010; not in panel |
| `EFT` | EFTA aggregate | Aggregate, not a country |
| `PUS` | US Pacific Islands | Aggregate, not in panel |
| `SUN` | USSR | Historical; dissolved 1991 |

---

## 7. BACI Code Mapping

**File:** `baci_to_iso3_mapping.csv`

Reference mapping from BACI numeric country codes to ISO alpha-3 codes used in all trade datasets.

| Variable | Definition |
|----------|-----------|
| `baci_code` | BACI numeric country code |
| `iso3` | ISO alpha-3 country code |
| `ccode` | COW numeric code; `NaN` if not in panel |
| `country_name` | Country name from BACI metadata |

**Special mappings:**

| BACI Code | ISO3 | Entity | Notes |
|-----------|------|--------|-------|
| 58 | `BEL` | Belgium-Luxembourg | Pre-1999 combined unit -> Belgium |
| 251 | `FRA` | France | Non-standard BACI code |
| 344 | `HKG` | Hong Kong | Separate WTO member |
| 446 | `MAC` | Macao | Separate WTO member |
| 490 | `TAW` | Taiwan | "Other Asia, nes" proxy |
| 999 | `EUN` | European Union | Constructed aggregate |

---

## 8. EU Membership Panel

**File:** `eu_membership_1995_2024.csv`
**Rows:** 840 (28 EU members x 30 years)

Time-varying EU membership panel for all 28 countries that were ever EU members during 1995--2024.

| Variable | Definition | Unit / Range |
|----------|-----------|--------------|
| `country` | Country name | String |
| `iso3c` | ISO alpha-3 code | String |
| `ccode` | COW numeric code | Integer |
| `baci_code` | BACI numeric code | Integer |
| `year` | Calendar year | Integer; 1995--2024 |
| `eu_member` | Whether the country was an EU member in that year | Binary (0/1) |
| `accession_year` | Year of EU accession | Integer |
| `exit_year` | Year of EU exit | Integer; `NaN` if still member |

**Membership transitions:**

| Event | Year | Countries |
|-------|------|-----------|
| EU-15 (founding WTO members) | 1995 | AUT, BEL, DNK, FIN, FRA, DEU, GRC, IRL, ITA, LUX, NLD, PRT, ESP, SWE, GBR |
| Eastern enlargement | 2004 | CYP, CZE, EST, HUN, LVA, LTU, MLT, POL, SVK, SVN |
| Southeastern enlargement | 2007 | BGR, ROU |
| Croatian accession | 2013 | HRV |
| Brexit | After 2020 | GBR exits (`eu_member` = 0 from 2021) |

---

*End of documentation.*
