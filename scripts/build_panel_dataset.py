#!/usr/bin/env python3
"""
Build WTO panel dataset 1995-2024.

Country × Year panel combining:
  - wto_cases.csv       : dispute participation  (names already in short form)
  - WTO_mem_list.xlsx   : WTO membership accession dates
  - IdealPoint.dta      : country universe + iso3c codes
  - GA_Voting.csv       : UN country names

Country names follow the SHORT / common forms used in wto_cases.csv.
REPLACE_DICT maps WTO-official long names → short names; it is applied to
WTO_mem_list and IdealPoint before building the country universe.
"""

import ast
import re
import numpy as np
import pandas as pd

BASE  = "Data"
YEARS = list(range(1995, 2025))   # 1995–2024 inclusive


def norm(name):
    """Collapse curly apostrophes to straight; strip whitespace."""
    if not isinstance(name, str):
        return name
    return name.replace("\u2019", "'").replace("\u2018", "'").strip()


# ──────────────────────────────────────────────────────────────────────────────
# 1.  SHORT-NAME MAPPING TABLES
# ──────────────────────────────────────────────────────────────────────────────

# Long / canonical  →  short name  (user-supplied replace_dict)
REPLACE_DICT = {
    "United States":                     "U.S.",
    "European Communities":              "EU",
    "European Union":                    "EU",
    "Venezuela, Bolivarian Republic of": "Venezuela",
    "Korea, Republic of":                "South Korea",
    "Hong Kong, China":                  "Hong Kong",
    "Dominican Republic":                "Dominican",
    "Moldova, Republic of":              "Moldova",
    "Viet Nam":                          "Vietnam",
    "Russian Federation":                "Russia",
    "Bahrain, Kingdom of":               "Bahrain",
    "Saudi Arabia, Kingdom of":          "Saudi Arabia",
    "Kyrgyz Republic":                   "Kyrgyzstan",
    "United Arab Emirates":              "UAE",
    "Chinese Taipei":                    "Taiwan",
    "Bolivia, Plurinational State of":   "Bolivia",
}

# Within wto_cases.csv the only inconsistency is Turkey/Türkiye (renamed 2022)
CASES_NORMALIZE = {
    "Turkey": "Türkiye",
}

# IdealPoint country name  →  WTO-canonical name  (then REPLACE_DICT is applied)
# Only entries that actually differ from the target short name are listed.
IDEALPOINT_TO_WTO = {
    # name changes / abbreviation differences
    "Turkey":                    "Türkiye",         # directly to Türkiye (not in REPLACE_DICT)
    "Czechia":                   "Czech Republic",
    "Slovakia":                  "Slovak Republic",
    "Kuwait":                    "Kuwait, the State of",
    # ampersand → "and"
    "Antigua & Barbuda":         "Antigua and Barbuda",
    "St. Kitts & Nevis":         "Saint Kitts and Nevis",
    "St. Lucia":                 "Saint Lucia",
    "St. Vincent & Grenadines":  "Saint Vincent and the Grenadines",
    "Trinidad & Tobago":         "Trinidad and Tobago",
    # other remaps
    "Congo - Brazzaville":       "Congo",
    "Congo - Kinshasa":          "Democratic Republic of the Congo",
    "Myanmar (Burma)":           "Myanmar",
    "Brunei":                    "Brunei Darussalam",
    "Cape Verde":                "Cabo Verde",
    "Laos":                      "Lao People's Democratic Republic",
    # encoding artefacts in the .dta file
    "CÃ´te dâ\x80\x99Ivoire":    "Côte d'Ivoire",
    "SÃ£o TomÃ© & PrÃ\xadncipe": "Sao Tome and Principe",
}


def idealpoint_to_short(raw):
    """Map an IdealPoint country name to the short name used in the panel."""
    wto = norm(IDEALPOINT_TO_WTO.get(raw, raw))   # step 1: IdealPoint → WTO canonical
    return REPLACE_DICT.get(wto, wto)              # step 2: canonical → short


def wto_official_to_short(raw):
    """Map a WTO_mem_list (official) name to the short name used in the panel."""
    n = norm(raw)
    return REPLACE_DICT.get(n, n)


# ──────────────────────────────────────────────────────────────────────────────
# 2.  EU & EUROZONE MEMBERSHIP  (keys are short names)
# ──────────────────────────────────────────────────────────────────────────────

EU_ACCESSION = {
    # Founding Six (Treaty of Rome entered into force 1958)
    "Belgium": 1958, "France": 1958, "Germany": 1958,
    "Italy":   1958, "Luxembourg": 1958, "Netherlands": 1958,
    # 1st enlargement
    "Denmark": 1973, "Ireland": 1973, "United Kingdom": 1973,
    # 2nd
    "Greece": 1981,
    # 3rd
    "Portugal": 1986, "Spain": 1986,
    # 4th
    "Austria": 1995, "Finland": 1995, "Sweden": 1995,
    # 5th (Big Bang)
    "Cyprus": 2004, "Czech Republic": 2004, "Estonia": 2004,
    "Hungary": 2004, "Latvia": 2004, "Lithuania": 2004,
    "Malta": 2004, "Poland": 2004, "Slovak Republic": 2004, "Slovenia": 2004,
    # 6th
    "Bulgaria": 2007, "Romania": 2007,
    # 7th
    "Croatia": 2013,
}

BREXIT_YEAR = 2020   # UK flips eu_member 1 → 0 from this year

EURO_ACCESSION = {
    "Austria": 1999, "Belgium": 1999, "Finland": 1999, "France": 1999,
    "Germany": 1999, "Ireland": 1999, "Italy": 1999, "Luxembourg": 1999,
    "Netherlands": 1999, "Portugal": 1999, "Spain": 1999,
    "Greece": 2001, "Slovenia": 2007,
    "Cyprus": 2008, "Malta": 2008,
    "Slovak Republic": 2009, "Estonia": 2011,
    "Latvia": 2014, "Lithuania": 2015, "Croatia": 2023,
}


# ──────────────────────────────────────────────────────────────────────────────
# 3.  HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def parse_list_col(val):
    if pd.isna(val):
        return []
    try:
        result = ast.literal_eval(val)
        return [x for x in result if x]
    except Exception:
        return [val] if val else []


def extract_year(date_str):
    if pd.isna(date_str):
        return None
    m = re.search(r"\b(1[9]\d{2}|20\d{2})\b", str(date_str))
    return int(m.group(1)) if m else None


# ──────────────────────────────────────────────────────────────────────────────
# 4.  LOAD & HARMONISE SOURCES
# ──────────────────────────────────────────────────────────────────────────────

# ── wto_cases ──
cases_df = pd.read_csv(f"{BASE}/wto_cases_v2.csv")
cases_df["year"] = cases_df["consultations_requested"].apply(extract_year)

def normalise_cases_name(raw):
    """Normalise a wto_cases country name to the panel's short-name standard."""
    n = norm(raw)                       # 1. fix curly apostrophes / whitespace
    n = CASES_NORMALIZE.get(n, n)      # 2. Turkey → Türkiye, etc.
    n = REPLACE_DICT.get(n, n)         # 3. long WTO names → short names
    return n

case_records = []
for _, row in cases_df.iterrows():
    yr = row["year"]
    if yr is None or yr < 1995 or yr > 2024:
        continue
    for raw in parse_list_col(row["complainant"]):
        case_records.append((yr, normalise_cases_name(raw), "complainant"))
    for raw in parse_list_col(row["respondent"]):
        case_records.append((yr, normalise_cases_name(raw), "respondent"))
    for raw in parse_list_col(row["third_parties"]):
        case_records.append((yr, normalise_cases_name(raw), "third_party"))

roles_df = pd.DataFrame(case_records, columns=["year", "country", "role"])
roles_df = roles_df[roles_df["country"] != ""]

# ── WTO membership ──
wto_mem = pd.read_excel(f"{BASE}/WTO_mem_list.xlsx")
wto_mem.columns = ["wto_name", "membership_date"]
wto_mem["wto_name"]       = wto_mem["wto_name"].apply(norm)
wto_mem["short_name"]     = wto_mem["wto_name"].apply(wto_official_to_short)
wto_mem["accession_year"] = wto_mem["membership_date"].apply(extract_year)

# ── IdealPoint ──
ideal_df = pd.read_stata(f"{BASE}/IdealPoint.dta")
ideal_df = ideal_df[ideal_df["year"].between(1995, 2024)].copy()
ideal_df["short_name"] = ideal_df["countryname"].apply(idealpoint_to_short)

# iso3c:  short_name → iso3c
iso3c_map = (
    ideal_df[ideal_df["iso3c"].notna() & (ideal_df["iso3c"] != "")]
    .drop_duplicates("short_name")[["short_name", "iso3c"]]
    .set_index("short_name")["iso3c"]
    .to_dict()
)
iso3c_map["Taiwan"] = "TAW"   # follow COW dataset (ccode 713)
iso3c_map["EU"]     = "EUN"   # EU-level entity

# ccode:  short_name → COW numeric code  (bridge key for merging with COW datasets)
# IdealPoint carries the COW ccode; we build short_name → ccode from it.
iso3c_to_ccode = (
    ideal_df[ideal_df["iso3c"].notna() & (ideal_df["iso3c"] != "")
             & ideal_df["ccode"].notna()]
    .drop_duplicates("iso3c")[["iso3c", "ccode"]]
    .set_index("iso3c")["ccode"]
    .astype(int)
    .to_dict()
)
iso3c_to_ccode["TAW"] = 713    # Taiwan: COW ccode 713, stateabb TAW

# stateabb: COW 3-letter abbreviation
# Filter to states active in 1995-2024; keep most-recent entry per ccode.
cow_df = pd.read_csv(f"{BASE}/statelist2024.csv")
cow_active = (
    cow_df[(cow_df["styear"] <= 2024) & (cow_df["endyear"] >= 1995)]
    .sort_values("styear", ascending=False)
    .drop_duplicates("ccode")[["ccode", "stateabb"]]
    .set_index("ccode")
)
ccode_to_stateabb = cow_active["stateabb"].to_dict()

# ── GA Voting (UN country names) ──
ga_df = pd.read_csv(f"{BASE}/GA_Voting.csv", low_memory=False,
                    usecols=["ms_code", "ms_name"])
un_name_map = (
    ga_df.dropna(subset=["ms_code", "ms_name"])
    .drop_duplicates("ms_code")
    .assign(un_name=lambda d: d["ms_name"].str.title())
    .set_index("ms_code")["un_name"]
    .to_dict()
)

# ──────────────────────────────────────────────────────────────────────────────
# 5.  COUNTRY UNIVERSE  (union of all three sources, using short names)
# ──────────────────────────────────────────────────────────────────────────────

from_wto  = set(wto_mem["short_name"].dropna())
from_case = set(roles_df["country"].dropna())
from_ip   = set(ideal_df["short_name"].dropna()) - {"", "Yugoslavia"}

all_countries = (from_wto | from_case | from_ip)
all_countries.discard("")

# ──────────────────────────────────────────────────────────────────────────────
# 6.  PANEL SKELETON  (country × year)
# ──────────────────────────────────────────────────────────────────────────────

panel = pd.DataFrame(
    [{"country": c, "year": y} for c in sorted(all_countries) for y in YEARS]
)

wto_lookup = wto_mem.set_index("short_name")["accession_year"].to_dict()
panel["wto_accession_year"] = panel["country"].map(wto_lookup)

# ──────────────────────────────────────────────────────────────────────────────
# 7.  wto_member  (0 / 1)
# ──────────────────────────────────────────────────────────────────────────────

panel["wto_member"] = np.where(
    panel["wto_accession_year"].notna() & (panel["year"] >= panel["wto_accession_year"]),
    1, 0
)

# ──────────────────────────────────────────────────────────────────────────────
# 8.  complainant / respondent / third_party / wto_participant
# ──────────────────────────────────────────────────────────────────────────────

for role in ("complainant", "respondent", "third_party"):
    subset = (roles_df[roles_df["role"] == role]
              .drop_duplicates(["year", "country"])
              .assign(**{role: 1}))
    panel = panel.merge(subset[["country", "year", role]],
                        on=["country", "year"], how="left")
    panel[role] = panel[role].fillna(0).astype(int)

# wto_participant = CUMULATIVE union of the three roles
panel = panel.sort_values(["country", "year"])
_yr = (panel["complainant"] | panel["respondent"] | panel["third_party"]).astype(int)
panel["wto_participant"] = _yr.groupby(panel["country"]).cummax().astype(int)

# Cumulative case counts per role — actual number of cases filed each year,
# not binary "was active this year". roles_df has one row per (case, country, role).
for _role, _cum in [("complainant", "cum_complainant"),
                    ("respondent",  "cum_respondent"),
                    ("third_party", "cum_third_party")]:
    _n_col = f"_n_{_role}"
    _yr_counts = (roles_df[roles_df["role"] == _role]
                  .groupby(["year", "country"]).size()
                  .reset_index(name=_n_col))
    panel = panel.merge(_yr_counts, on=["country", "year"], how="left")
    panel[_n_col] = panel[_n_col].fillna(0).astype(int)
    panel[_cum] = panel.groupby("country")[_n_col].cumsum().astype(int)
    panel = panel.drop(columns=[_n_col])

# ──────────────────────────────────────────────────────────────────────────────
# 9.  eu_member / euro_join_year / euro_member
# ──────────────────────────────────────────────────────────────────────────────

def compute_eu_member(row):
    acc = EU_ACCESSION.get(row["country"])
    if acc is None or row["year"] < acc:
        return 0
    if row["country"] == "United Kingdom" and row["year"] >= BREXIT_YEAR:
        return 0
    return 1

panel["eu_member"]     = panel.apply(compute_eu_member, axis=1)
panel["euro_join_year"] = panel["country"].map(EURO_ACCESSION)
panel["euro_member"]   = np.where(
    panel["euro_join_year"].notna() & (panel["year"] >= panel["euro_join_year"]),
    1, 0
)

# ──────────────────────────────────────────────────────────────────────────────
# 10. iso3c  &  un_country_name
# ──────────────────────────────────────────────────────────────────────────────

panel["iso3c"]           = panel["country"].map(iso3c_map)
panel["ccode"]           = panel["iso3c"].map(iso3c_to_ccode)
panel["stateabb"]        = panel["ccode"].map(ccode_to_stateabb)
panel["un_country_name"] = panel["iso3c"].map(un_name_map)

# ──────────────────────────────────────────────────────────────────────────────
# 11. FINAL COLUMN ORDER & EXPORT
# ──────────────────────────────────────────────────────────────────────────────

col_order = [
    "country", "iso3c", "ccode", "stateabb", "un_country_name", "year",
    "wto_member", "wto_accession_year",
    "complainant", "respondent", "third_party", "wto_participant",
    "cum_complainant", "cum_respondent", "cum_third_party",
    "eu_member", "euro_join_year", "euro_member",
]
panel = panel[col_order].sort_values(["country", "year"]).reset_index(drop=True)

out_path = f"{BASE}/wto_panel_1995_2024.csv"
panel.to_csv(out_path, index=False)

# ──────────────────────────────────────────────────────────────────────────────
# 12. DIAGNOSTICS
# ──────────────────────────────────────────────────────────────────────────────

print(f"Saved : {out_path}")
print(f"Shape : {panel.shape}")
print(f"Countries: {panel['country'].nunique()}   Years: {panel['year'].min()}–{panel['year'].max()}")

print("\n--- Variable counts (rows == 1) ---")
for col in ["wto_member","complainant","respondent","third_party",
            "wto_participant","eu_member","euro_member"]:
    print(f"  {col:20s} {(panel[col]==1).sum():6,d}")

print("\n--- First year wto_participant = 1 (key countries) ---")
for c in ["South Korea", "U.S.", "EU", "Taiwan", "Venezuela", "Russia", "China",
          "India", "Japan", "Brazil"]:
    sub = panel[(panel["country"] == c) & (panel["wto_participant"] == 1)]
    print(f"  {c:30s}  {sub['year'].min() if len(sub) else 'NEVER'}")

print("\n--- South Korea 1995–1997 (DS3 sanity check) ---")
kor = panel[(panel["country"] == "South Korea") & (panel["year"] <= 1997)]
print(kor[["country","year","complainant","respondent","third_party","wto_participant"]].to_string(index=False))

print("\n--- Long-form names that should NOT appear in country column ---")
bad = ["Korea, Republic of","United States","Russian Federation","Viet Nam",
       "Chinese Taipei","European Union","Bolivia, Plurinational State of",
       "Hong Kong, China","Moldova, Republic of","Kyrgyz Republic"]
for ln in bad:
    found = ln in panel["country"].values
    print(f"  {'FOUND' if found else 'OK   '}  '{ln}'")

print("\n--- Countries with wto_participant == 0 in 2024 (never participated) ---")
never = panel[panel["year"] == 2024].set_index("country")["wto_participant"]
print(sorted(never[never == 0].index.tolist()))

print("\n--- COW merge coverage (year=2000 slice) ---")
s = panel[panel["year"] == 2000]
print(f"  stateabb matched : {s['stateabb'].notna().sum()} / {len(s)} countries")
print(f"  ccode matched    : {s['ccode'].notna().sum()} / {len(s)} countries")

print("\n--- Countries missing stateabb (year=2000) ---")
miss = s[s["stateabb"].isna()][["country","iso3c","ccode"]]
print(miss.to_string(index=False))

print("\n--- Cumulative counts sanity check (South Korea) ---")
kor = panel[panel["country"] == "South Korea"]
print(kor[["year","complainant","respondent","third_party",
           "cum_complainant","cum_respondent","cum_third_party"]].tail(10).to_string(index=False))

print("\n--- Countries missing iso3c ---")
print(sorted(panel[panel["iso3c"].isna()]["country"].unique()))
