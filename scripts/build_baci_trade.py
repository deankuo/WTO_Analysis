"""
BACI HS92 Bilateral Trade Aggregation & Dependence Index Construction

Processes yearly BACI trade data (1995-2024) into bilateral trade datasets
with dependence indices at dyad-year and dyad-year-section levels.

Dual EU representation: individual EU member states are kept alongside an
aggregate EUN node. Individual members include intra-EU trade in their
totals; EUN excludes it.

Outputs:
  - Data/bilateral_trade_aggregate.csv     (dyad-year level)
  - Data/bilateral_trade_by_section.csv    (dyad-year-section level)
  - Data/baci_to_iso3_mapping.csv          (reference mapping)
  - Data/eu_membership_1995_2024.csv       (EU membership panel)
"""

import os
import warnings
import pandas as pd
import numpy as np
import country_converter as coco

warnings.filterwarnings("ignore", category=FutureWarning)

# -- Paths --------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACI_DIR = os.path.join(BASE_DIR, "Data", "BACI_HS92")
DATA_DIR = os.path.join(BASE_DIR, "Data")
OUTPUT_DIR = DATA_DIR  # output CSVs go to Data/

BACI_CC_FILE = os.path.join(BACI_DIR, "country_codes_V202601.csv")
HS_SECTION_FILE = os.path.join(BACI_DIR, "hs_section_mapping_v2.csv")
PANEL_FILE = os.path.join(DATA_DIR, "country_meta_1995_2024.csv")

YEARS = range(1995, 2025)

# -- EU Membership (time-varying) ---------------------------------------------
EU_MEMBERS_1995 = {40, 56, 208, 246, 251, 276, 300, 372, 380, 442, 528, 620, 724, 752, 826}  # 15 members
EU_2004_ACCESSION = {196, 203, 233, 348, 428, 440, 470, 616, 703, 705}  # 10 members
EU_2007_ACCESSION = {100, 642}   # Bulgaria, Romania
EU_2013_ACCESSION = {191}        # Croatia
UK_BACI_CODE = 826
EU_AGGREGATE_CODE = 999

# Belgium-Luxembourg (58) was reported as a single unit until 1998
# Map it to Belgium (56) which is an EU member anyway
BELGLUX_CODE = 58

# EU membership metadata for panel generation
EU_MEMBER_INFO = [
    # (country, iso3c, ccode, baci_code, accession_year, exit_year_or_None)
    ("Austria",        "AUT",  305,  40,  1995, None),
    ("Belgium",        "BEL",   211,  56,  1995, None),
    ("Denmark",        "DNK",  390, 208,  1995, None),
    ("Finland",        "FIN",  375, 246,  1995, None),
    ("France",         "FRA",  220, 251,  1995, None),
    ("Germany",        "DEU",  255, 276,  1995, None),
    ("Greece",         "GRC",  350, 300,  1995, None),
    ("Ireland",        "IRL",  205, 372,  1995, None),
    ("Italy",          "ITA",  325, 380,  1995, None),
    ("Luxembourg",     "LUX",  212, 442,  1995, None),
    ("Netherlands",    "NLD",  210, 528,  1995, None),
    ("Portugal",       "PRT",  235, 620,  1995, None),
    ("Spain",          "ESP",  230, 724,  1995, None),
    ("Sweden",         "SWE",  380, 752,  1995, None),
    ("United Kingdom", "GBR",  200, 826,  1995, 2020),
    ("Cyprus",         "CYP",  352, 196,  2004, None),
    ("Czech Republic", "CZE",  316, 203,  2004, None),
    ("Estonia",        "EST",  366, 233,  2004, None),
    ("Hungary",        "HUN",  310, 348,  2004, None),
    ("Latvia",         "LVA",  367, 428,  2004, None),
    ("Lithuania",      "LTU",  368, 440,  2004, None),
    ("Malta",          "MLT",  338, 470,  2004, None),
    ("Poland",         "POL",  290, 616,  2004, None),
    ("Slovakia",       "SVK",  317, 703,  2004, None),
    ("Slovenia",       "SVN",  349, 705,  2004, None),
    ("Bulgaria",       "BGR",  355, 100,  2007, None),
    ("Romania",        "ROU",  360, 642,  2007, None),
    ("Croatia",        "HRV",  344, 191,  2013, None),
]


def get_eu_members(year: int) -> set:
    """Return set of BACI numeric codes for EU members in a given year."""
    members = set(EU_MEMBERS_1995)
    if year >= 2004:
        members |= EU_2004_ACCESSION
    if year >= 2007:
        members |= EU_2007_ACCESSION
    if year >= 2013:
        members |= EU_2013_ACCESSION
    # Brexit: UK leaves after 2020
    if year >= 2021:
        members.discard(UK_BACI_CODE)
    return members


# -- Step 1: Build Country Code Mapping ----------------------------------------

def build_code_mapping() -> tuple[dict, dict]:
    """
    Build BACI numeric code -> ISO3 mapping.
    Returns (code_to_iso3, code_to_name) dicts.
    """
    cc_df = pd.read_csv(BACI_CC_FILE)
    converter = coco.CountryConverter()

    # Start with country_converter for all codes
    code_to_iso3 = {}
    code_to_name = {}
    unresolved = []

    for _, row in cc_df.iterrows():
        code = int(row["country_code"])
        name = row["country_name"]
        code_to_name[code] = name

        iso3 = converter.convert(code, src="BACI", to="ISO3")
        if iso3 != "not found":
            code_to_iso3[code] = iso3
        else:
            unresolved.append((code, name, row.get("country_iso3", "")))

    # Manual overrides for country_converter failures
    manual_overrides = {
        58:  "BEL",   # Belgium-Luxembourg (...1998) -> Belgium (EU-aggregated anyway)
        251: "FRA",   # France (BACI non-standard code)
        490: "TAW",   # "Other Asia, nes" -> Taiwan (panel data uses TAW)
        530: "ANT",   # Netherlands Antilles (...2010)
        579: "NOR",   # Norway
        697: "EFT",   # Europe EFTA, nes (aggregate, not in panel)
        699: "IND",   # India
        711: "ZAF",   # Southern African Customs Union (...1999) -> South Africa
        736: "SDN",   # Sudan (...2011)
        757: "CHE",   # Switzerland
        810: "SUN",   # USSR (historical)
        842: "USA",   # USA
        849: "PUS",   # US Misc. Pacific Isds
        891: "SRB",   # Serbia and Montenegro (...2005) -> Serbia
    }
    code_to_iso3.update(manual_overrides)

    # Special cases explicitly required
    code_to_iso3[344] = "HKG"  # Hong Kong
    code_to_iso3[446] = "MAC"  # Macao
    code_to_iso3[EU_AGGREGATE_CODE] = "EUN"  # EU aggregate
    code_to_name[EU_AGGREGATE_CODE] = "European Union"

    # Report
    print("=== Country Code Mapping ===")
    print(f"Total codes in BACI metadata: {len(cc_df)}")
    print(f"Resolved by country_converter: {len(code_to_iso3) - len(manual_overrides) - 3}")
    print(f"Manual overrides applied: {len(manual_overrides) + 3}")

    still_unresolved = [u for u in unresolved if u[0] not in manual_overrides]
    if still_unresolved:
        print(f"Still unresolved: {still_unresolved}")

    return code_to_iso3, code_to_name


# -- Step 2: Process Each Year (Two-Pass) -------------------------------------

def _load_and_prepare(year: int, hs_sections: pd.DataFrame) -> pd.DataFrame | None:
    """Read one year of BACI CSV, zero-pad HS codes, merge section mapping."""
    filepath = os.path.join(BACI_DIR, f"BACI_HS92_Y{year}_V202601.csv")
    if not os.path.exists(filepath):
        print(f"  WARNING: {filepath} not found, skipping year {year}")
        return None

    df = pd.read_csv(filepath)
    df["k"] = df["k"].astype(str).str.zfill(6)
    df["hs2"] = df["k"].str[:2]

    # Merge HS section mapping
    df = df.merge(hs_sections[["hs2", "section_num", "section_en"]], on="hs2", how="left")

    # Drop rows without a valid section (hs2 = "99" etc.)
    n_before = len(df)
    df = df.dropna(subset=["section_num"])
    df["section_num"] = df["section_num"].astype(int)
    if len(df) < n_before:
        print(f"  Year {year}: dropped {n_before - len(df)} rows with unmapped HS chapters")

    return df


def _compute_indices(df: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute dependence indices at dyad-year-section and dyad-year levels."""
    # === Export-side aggregates ===
    # Dyad-year-section level
    dys = df.groupby(["i", "j", "section_num", "section_en"]).agg(
        trade_value_ij_s=("v", "sum"),
        n_products_ij_s=("k", "nunique"),
    ).reset_index()

    # Country-year-section: total exports by exporter x section
    cys_exp = df.groupby(["i", "section_num"]).agg(
        total_exports_i_s=("v", "sum"),
    ).reset_index()

    # Country-year: total exports by exporter
    cy_exp = df.groupby("i").agg(
        total_exports_i=("v", "sum"),
    ).reset_index()

    # === Import-side aggregates ===
    # Country-year-section: total imports by importer x section
    cys_imp = df.groupby(["j", "section_num"]).agg(
        total_imports_i_s=("v", "sum"),
    ).reset_index().rename(columns={"j": "i"})

    # Country-year: total imports by importer
    cy_imp = df.groupby("j").agg(
        total_imports_i=("v", "sum"),
    ).reset_index().rename(columns={"j": "i"})

    # === Merge export-side into dys ===
    dys = dys.merge(cy_exp, on="i", how="left")
    dys = dys.merge(cys_exp, on=["i", "section_num"], how="left")

    dys["bilateral_sector_concentration"] = dys["trade_value_ij_s"] / dys["total_exports_i"]
    dys["sector_export_concentration"] = dys["total_exports_i_s"] / dys["total_exports_i"]
    dys["export_dependence"] = np.where(
        dys["total_exports_i_s"] > 0,
        dys["trade_value_ij_s"] / dys["total_exports_i_s"],
        np.nan,
    )

    # === Import-side: reverse flow (imports_i_from_j_s = trade from j to i in s) ===
    imports_s_lookup = dys[["i", "j", "section_num", "trade_value_ij_s"]].rename(
        columns={"i": "_exp", "j": "_imp", "trade_value_ij_s": "imports_i_from_j_s"}
    )
    dys = dys.merge(
        imports_s_lookup,
        left_on=["j", "i", "section_num"],
        right_on=["_exp", "_imp", "section_num"],
        how="left",
    ).drop(columns=["_exp", "_imp"])
    dys["imports_i_from_j_s"] = dys["imports_i_from_j_s"].fillna(0)

    dys = dys.merge(cys_imp, on=["i", "section_num"], how="left")
    dys = dys.merge(cy_imp, on="i", how="left")

    dys["import_dependence"] = np.where(
        dys["total_imports_i_s"] > 0,
        dys["imports_i_from_j_s"] / dys["total_imports_i_s"],
        np.nan,
    )

    dys["year"] = year

    # === Dyad-year aggregate level ===
    dya = dys.groupby(["i", "j"]).agg(
        total_trade_ij=("trade_value_ij_s", "sum"),
        n_products_ij=("n_products_ij_s", "sum"),
        n_sections_ij=("section_num", "nunique"),
    ).reset_index()

    dya = dya.merge(cy_exp, on="i", how="left")
    dya["export_dependence"] = dya["total_trade_ij"] / dya["total_exports_i"]

    # Import-side aggregate: reverse flow lookup
    imports_agg_lookup = dya[["i", "j", "total_trade_ij"]].rename(
        columns={"i": "_exp", "j": "_imp", "total_trade_ij": "imports_i_from_j"}
    )
    dya = dya.merge(
        imports_agg_lookup,
        left_on=["j", "i"],
        right_on=["_exp", "_imp"],
        how="left",
    ).drop(columns=["_exp", "_imp"])
    dya["imports_i_from_j"] = dya["imports_i_from_j"].fillna(0)

    dya = dya.merge(cy_imp, on="i", how="left")
    dya["import_dependence"] = np.where(
        dya["total_imports_i"] > 0,
        dya["imports_i_from_j"] / dya["total_imports_i"],
        np.nan,
    )

    dya["year"] = year

    return dys, dya


def process_year(year: int, hs_sections: pd.DataFrame,
                 code_to_iso3: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Process one year of BACI data with dual EU representation.

    Pass 1 (Individual): Keep all country codes as-is. Belgium-Luxembourg (58)
    mapped to Belgium (56) for years <= 1998. Intra-EU trade is kept.

    Pass 2 (EU Aggregate): Replace EU member codes with 999, drop intra-EU
    trade. Only EUN rows are extracted from this pass.

    Returns (dyad_year_section_df, dyad_year_agg_df) with both individual
    member rows and EUN aggregate rows.
    """
    df = _load_and_prepare(year, hs_sections)
    if df is None:
        return pd.DataFrame(), pd.DataFrame()

    eu_members = get_eu_members(year)
    # Belgium-Luxembourg (58) -> treat as EU member for years it appears
    if year <= 1998:
        eu_members.add(BELGLUX_CODE)

    # ── Pass 1: Individual country codes ──
    df_indiv = df.copy()

    # Map Belgium-Luxembourg (58) -> Belgium (56) for individual pass
    if year <= 1998:
        df_indiv.loc[df_indiv["i"] == BELGLUX_CODE, "i"] = 56
        df_indiv.loc[df_indiv["j"] == BELGLUX_CODE, "j"] = 56

    # Drop self-trade (shouldn't exist but be safe)
    df_indiv = df_indiv[df_indiv["i"] != df_indiv["j"]].copy()

    dys_indiv, dya_indiv = _compute_indices(df_indiv, year)

    # ── Pass 2: EU Aggregate ──
    df_eu = df.copy()

    df_eu.loc[df_eu["i"].isin(eu_members), "i"] = EU_AGGREGATE_CODE
    df_eu.loc[df_eu["j"].isin(eu_members), "j"] = EU_AGGREGATE_CODE

    # Drop intra-EU trade
    df_eu = df_eu[df_eu["i"] != df_eu["j"]].copy()

    dys_eu, dya_eu = _compute_indices(df_eu, year)

    # ── Combine: all individual rows + only EUN rows from Pass 2 ──
    dys_eun = dys_eu[
        (dys_eu["i"] == EU_AGGREGATE_CODE) | (dys_eu["j"] == EU_AGGREGATE_CODE)
    ]
    dya_eun = dya_eu[
        (dya_eu["i"] == EU_AGGREGATE_CODE) | (dya_eu["j"] == EU_AGGREGATE_CODE)
    ]

    dys_combined = pd.concat([dys_indiv, dys_eun], ignore_index=True)
    dya_combined = pd.concat([dya_indiv, dya_eun], ignore_index=True)

    return dys_combined, dya_combined


# -- Step 3: Combine and Convert Codes ----------------------------------------

def convert_codes(df: pd.DataFrame, code_to_iso3: dict,
                  code_to_name: dict,
                  iso3_to_ccode: dict | None = None) -> pd.DataFrame:
    """Map BACI numeric codes to ISO3, add country names and COW ccode."""
    df["exporter"] = df["i"].map(code_to_iso3)
    df["importer"] = df["j"].map(code_to_iso3)
    df["exporter_name"] = df["i"].map(code_to_name)
    df["importer_name"] = df["j"].map(code_to_name)

    if iso3_to_ccode is not None:
        df["exporter_ccode"] = df["exporter"].map(iso3_to_ccode)
        df["importer_ccode"] = df["importer"].map(iso3_to_ccode)

    # Check for unmapped
    unmapped_exp = df[df["exporter"].isna()]["i"].unique()
    unmapped_imp = df[df["importer"].isna()]["j"].unique()
    unmapped = set(unmapped_exp) | set(unmapped_imp)
    if unmapped:
        print(f"\n  WARNING: Unmapped BACI codes: {sorted(unmapped)}")
        # Drop unmapped rows
        df = df.dropna(subset=["exporter", "importer"])

    return df


# -- Step 4: Merge GDP --------------------------------------------------------

def merge_gdp(dys: pd.DataFrame, dya: pd.DataFrame,
              panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Merge GDP from panel data and compute GDP-based indices.
    GDP is in millions USD; BACI trade values in thousands USD.
    """
    gdp_df = panel[["iso3c", "year", "gdp"]].drop_duplicates()

    # Merge into dyad-year-section
    dys = dys.merge(
        gdp_df, left_on=["exporter", "year"], right_on=["iso3c", "year"], how="left"
    ).drop(columns=["iso3c"])

    # bilateral_sector_gdp_share = trade_value_ij_s (thousands) / gdp (millions)
    # = (trade * 1000) / (gdp * 1_000_000) = trade / (gdp * 1000)
    dys["bilateral_sector_gdp_share"] = np.where(
        dys["gdp"].notna() & (dys["gdp"] > 0),
        dys["trade_value_ij_s"] / (dys["gdp"] * 1000),
        np.nan,
    )
    dys = dys.drop(columns=["gdp"])

    # Merge into dyad-year aggregate
    dya = dya.merge(
        gdp_df, left_on=["exporter", "year"], right_on=["iso3c", "year"], how="left"
    ).drop(columns=["iso3c"])

    dya["bilateral_trade_gdp_share"] = np.where(
        dya["gdp"].notna() & (dya["gdp"] > 0),
        dya["total_trade_ij"] / (dya["gdp"] * 1000),
        np.nan,
    )
    dya = dya.drop(columns=["gdp"])

    return dys, dya


# -- EU Membership Panel ------------------------------------------------------

def build_eu_membership_panel() -> pd.DataFrame:
    """
    Build EU membership panel: 28 members x 30 years = 840 rows.
    Columns: country, iso3c, ccode, baci_code, year, eu_member, accession_year, exit_year
    """
    rows = []
    for country, iso3c, ccode, baci_code, acc_year, exit_year in EU_MEMBER_INFO:
        for year in YEARS:
            if exit_year is not None:
                is_member = 1 if acc_year <= year <= exit_year else 0
            else:
                is_member = 1 if year >= acc_year else 0
            rows.append({
                "country": country,
                "iso3c": iso3c,
                "ccode": ccode,
                "baci_code": baci_code,
                "year": year,
                "eu_member": is_member,
                "accession_year": acc_year,
                "exit_year": exit_year if exit_year is not None else np.nan,
            })
    return pd.DataFrame(rows)


# -- Summary Statistics --------------------------------------------------------

def print_summary(dya: pd.DataFrame, dys: pd.DataFrame):
    """Print verification statistics."""
    print("\n" + "=" * 60)
    print("SUMMARY STATISTICS")
    print("=" * 60)

    print(f"\n--- Dyad-Year Aggregate ---")
    print(f"Years: {dya['year'].min()}-{dya['year'].max()}")
    print(f"Total rows: {len(dya):,}")
    print(f"Unique exporters: {dya['exporter'].nunique()}")
    print(f"Unique importers: {dya['importer'].nunique()}")

    print(f"\n--- Dyad-Year-Section ---")
    print(f"Total rows: {len(dys):,}")

    # Top 15 trading dyads
    print(f"\n--- Top 15 Trading Dyads (total trade across all years, billions USD) ---")
    top_dyads = (
        dya.groupby(["exporter", "exporter_name", "importer", "importer_name"])["total_trade_ij"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
    )
    for (exp, exp_name, imp, imp_name), val in top_dyads.items():
        print(f"  {exp} ({exp_name}) -> {imp} ({imp_name}): ${val / 1e6:.1f}B")

    # Top 10 HS sections
    print(f"\n--- Top 10 HS Sections (total trade, billions USD) ---")
    top_sections = (
        dys.groupby(["section_num", "section_en"])["trade_value_ij_s"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )
    for (snum, sname), val in top_sections.items():
        print(f"  Section {snum:2d} ({sname}): ${val / 1e6:.1f}B")

    # Verify special entities
    print(f"\n--- Special Entity Verification ---")
    for code, label in [("EUN", "EU"), ("TAW", "Taiwan"), ("HKG", "Hong Kong"), ("MAC", "Macao")]:
        n_exp = len(dya[dya["exporter"] == code])
        n_imp = len(dya[dya["importer"] == code])
        print(f"  {code} ({label}): {n_exp:,} exporter rows, {n_imp:,} importer rows")

    # EU dual representation verification
    print(f"\n--- EU Dual Representation Verification ---")
    for code, label in [("FRA", "France"), ("DEU", "Germany"), ("ITA", "Italy"), ("GBR", "UK")]:
        years_exp = sorted(dya[dya["exporter"] == code]["year"].unique())
        if len(years_exp) > 0:
            print(f"  {code} ({label}): exporter {years_exp[0]}-{years_exp[-1]} ({len(years_exp)} years)")
        else:
            print(f"  {code} ({label}): NOT FOUND as exporter")

    eun_years = sorted(dya[dya["exporter"] == "EUN"]["year"].unique())
    if len(eun_years) > 0:
        print(f"  EUN (EU aggregate): exporter {eun_years[0]}-{eun_years[-1]} ({len(eun_years)} years)")

    # Verify no double-counting: USA->JPN should appear exactly once per year
    print(f"\n--- Double-Count Check (USA->JPN) ---")
    usa_jpn = dya[(dya["exporter"] == "USA") & (dya["importer"] == "JPN")]
    counts = usa_jpn.groupby("year").size()
    dupes = counts[counts > 1]
    if len(dupes) == 0:
        print(f"  OK: USA->JPN appears exactly once per year ({len(counts)} years)")
    else:
        print(f"  WARNING: USA->JPN duplicated in years: {list(dupes.index)}")

    # Verify intra-EU trade exists in individual rows
    print(f"\n--- Intra-EU Trade Check ---")
    fra_deu = dya[(dya["exporter"] == "FRA") & (dya["importer"] == "DEU")]
    if len(fra_deu) > 0:
        print(f"  FRA->DEU: {len(fra_deu)} year rows present (intra-EU trade retained)")
    else:
        print(f"  WARNING: FRA->DEU not found (intra-EU trade missing)")

    # Taiwan cross-validation for 2020
    print(f"\n--- Taiwan (TAW) Top 5 Partners in 2020 (export value, billions USD) ---")
    tw_2020 = dya[(dya["exporter"] == "TAW") & (dya["year"] == 2020)]
    if len(tw_2020) > 0:
        top5 = tw_2020.nlargest(5, "total_trade_ij")
        for _, row in top5.iterrows():
            print(f"  TAW -> {row['importer']} ({row['importer_name']}): "
                  f"${row['total_trade_ij'] / 1e6:.1f}B")
        print(f"  Total Taiwan exports 2020: ${tw_2020['total_trade_ij'].sum() / 1e6:.1f}B")
    else:
        print("  No Taiwan export data for 2020!")

    # GDP merge coverage
    n_gdp = dya["bilateral_trade_gdp_share"].notna().sum()
    print(f"\n--- GDP Merge Coverage ---")
    print(f"  Dyad-year aggregate: {n_gdp:,}/{len(dya):,} rows have GDP-based index "
          f"({n_gdp / len(dya) * 100:.1f}%)")
    n_gdp_s = dys["bilateral_sector_gdp_share"].notna().sum()
    print(f"  Dyad-year-section:   {n_gdp_s:,}/{len(dys):,} rows have GDP-based index "
          f"({n_gdp_s / len(dys) * 100:.1f}%)")


# -- Main ---------------------------------------------------------------------

def main():
    print("BACI Bilateral Trade Aggregation (Dual EU Representation)")
    print("=" * 60)

    # Step 1: Build mapping
    code_to_iso3, code_to_name = build_code_mapping()

    # Load HS section mapping
    hs_sections = pd.read_csv(HS_SECTION_FILE, dtype={"hs2": str})

    # Step 2: Process each year (two-pass)
    all_dys = []
    all_dya = []

    for year in YEARS:
        print(f"Processing {year}...", end=" ", flush=True)
        dys, dya = process_year(year, hs_sections, code_to_iso3)
        if len(dys) > 0:
            all_dys.append(dys)
            all_dya.append(dya)
            print(f"dyad-section: {len(dys):,}, dyad-agg: {len(dya):,}")
        else:
            print("SKIPPED")

    # Step 3: Combine and convert codes
    print("\nCombining all years...")
    dys_all = pd.concat(all_dys, ignore_index=True)
    dya_all = pd.concat(all_dya, ignore_index=True)

    print("Converting country codes to ISO3 and merging COW ccodes...")
    panel = pd.read_csv(PANEL_FILE)
    iso3_to_ccode = panel[["iso3c", "ccode"]].drop_duplicates().set_index("iso3c")["ccode"].to_dict()
    dys_all = convert_codes(dys_all, code_to_iso3, code_to_name, iso3_to_ccode)
    dya_all = convert_codes(dya_all, code_to_iso3, code_to_name, iso3_to_ccode)

    # Step 4: Merge GDP
    print("Merging GDP from panel data...")
    dys_all, dya_all = merge_gdp(dys_all, dya_all, panel)

    # Step 5: Save outputs
    print("\nSaving outputs...")

    # Dyad-year aggregate
    dya_cols = [
        "year", "exporter", "exporter_ccode", "exporter_name",
        "importer", "importer_ccode", "importer_name",
        "total_trade_ij", "imports_i_from_j", "n_products_ij", "n_sections_ij",
        "export_dependence", "import_dependence",
        "bilateral_trade_gdp_share", "total_exports_i", "total_imports_i",
    ]
    dya_out = dya_all[dya_cols].sort_values(["year", "exporter", "importer"])
    dya_path = os.path.join(OUTPUT_DIR, "bilateral_trade_aggregate.csv")
    dya_out.to_csv(dya_path, index=False)
    print(f"  Saved: {dya_path} ({len(dya_out):,} rows)")

    # Dyad-year-section
    dys_cols = [
        "year", "exporter", "exporter_ccode", "importer", "importer_ccode",
        "section_num", "section_en",
        "trade_value_ij_s", "imports_i_from_j_s", "n_products_ij_s",
        "bilateral_sector_concentration", "sector_export_concentration",
        "export_dependence", "import_dependence",
        "bilateral_sector_gdp_share",
        "total_exports_i", "total_exports_i_s",
        "total_imports_i", "total_imports_i_s",
    ]
    dys_out = dys_all[dys_cols].sort_values(["year", "exporter", "importer", "section_num"])
    dys_path = os.path.join(OUTPUT_DIR, "bilateral_trade_by_section.csv")
    dys_out.to_csv(dys_path, index=False)
    print(f"  Saved: {dys_path} ({len(dys_out):,} rows)")

    # Mapping reference
    mapping_rows = []
    for code, iso3 in sorted(code_to_iso3.items()):
        name = code_to_name.get(code, "")
        ccode = iso3_to_ccode.get(iso3, np.nan)
        mapping_rows.append({"baci_code": code, "iso3": iso3, "ccode": ccode, "country_name": name})
    mapping_df = pd.DataFrame(mapping_rows)
    mapping_path = os.path.join(OUTPUT_DIR, "baci_to_iso3_mapping.csv")
    mapping_df.to_csv(mapping_path, index=False)
    print(f"  Saved: {mapping_path} ({len(mapping_df)} codes)")

    # EU membership panel
    eu_panel = build_eu_membership_panel()
    eu_path = os.path.join(OUTPUT_DIR, "eu_membership_1995_2024.csv")
    eu_panel.to_csv(eu_path, index=False)
    print(f"  Saved: {eu_path} ({len(eu_panel)} rows)")

    # Step 6: Summary
    print_summary(dya_out, dys_out)

    # Cross-validate ISO3 codes against panel data
    panel_iso3 = set(panel["iso3c"].unique())
    trade_iso3 = set(dya_out["exporter"].unique()) | set(dya_out["importer"].unique())
    not_in_panel = trade_iso3 - panel_iso3
    if not_in_panel:
        print(f"\n--- ISO3 codes in trade data but NOT in panel ---")
        for code in sorted(not_in_panel):
            name = code_to_name.get(
                next((k for k, v in code_to_iso3.items() if v == code), None), ""
            )
            print(f"  {code} ({name})")

    print("\nDone!")


if __name__ == "__main__":
    main()
