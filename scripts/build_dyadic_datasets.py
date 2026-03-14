"""
Dyadic Dataset Aggregation Pipeline

Merges bilateral trade data with ATOP alliances, DESTA trade agreements,
and WTO membership to produce analysis-ready directed dyad-year datasets.

Fixes applied vs. notebook version:
1. DESTA ISO numeric codes (e.g., USA=840) properly mapped via country_converter
   (notebook used BACI codes which differ for USA, FRA, IND, NOR, CHE, TWN)
2. DESTA undirected panel correctly merged to directed trade data
   (both exporter=iso3_1 and exporter=iso3_2 directions matched)
3. ATOP forward-filled from 2018 to 2024
4. WTO membership time-varying filter

Outputs:
  - Data/bilateral_trade_wto.csv          (WTO-filtered aggregate)
  - Data/bilateral_trade_section_wto.csv  (WTO-filtered section-level)
  - Data/desta_panel_1995_2025.csv        (rebuilt with correct ISO3 mapping)

Inputs:
  - Data/bilateral_trade_aggregate.csv    (from build_baci_trade.py)
  - Data/bilateral_trade_by_section.csv   (from build_baci_trade.py)
  - Data/ATOP_5.1/atop5_1ddyr.csv
  - Data/desta_panel_1995_2025.csv
  - Data/wto_mem_list.csv
"""

import os
import numpy as np
import pandas as pd
import country_converter as coco

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")

ATOP_COLS = ["atopally", "defense", "offense", "neutral", "nonagg", "consul"]
DESTA_COLS = [
    "label", "number", "base_treaty", "name", "entry_type", "typememb",
    "depth_index", "depth_rasch", "flexrigid", "flexescape", "enforce", "enforce01",
]


# -- Step 1: Fix DESTA Panel ISO3 Mapping ------------------------------------

def rebuild_desta_panel() -> pd.DataFrame:
    """
    Rebuild DESTA panel with correct ISO3 codes.

    The original notebook merged DESTA's ISO 3166-1 numeric codes (iso1/iso2)
    with baci_to_iso3_mapping.csv using baci_code as key. BACI codes differ
    from ISO numeric for several major countries (USA: 840 vs 842, FRA: 250
    vs 251, IND: 356 vs 699, etc.), causing NaN for those countries.

    Fix: use country_converter with src='ISOnumeric' to map correctly.
    """
    desta = pd.read_csv(os.path.join(DATA_DIR, "desta_panel_1995_2025.csv"))
    panel = pd.read_csv(os.path.join(DATA_DIR, "country_meta_1995_2024.csv"))

    # Build ISO numeric -> ISO3 mapping
    cc = coco.CountryConverter()
    all_codes = set(desta["baci_code1"].dropna().unique()) | set(
        desta["baci_code2"].dropna().unique()
    )

    iso_num_to_iso3 = {}
    for code in all_codes:
        result = cc.convert(int(code), src="ISOnumeric", to="ISO3")
        if result != "not found":
            iso_num_to_iso3[code] = result

    # Manual overrides for our panel conventions
    iso_num_to_iso3[158] = "TAW"  # Taiwan (our panel uses TAW, not TWN)

    # Rebuild iso3_1/iso3_2
    desta["iso3_1"] = desta["baci_code1"].map(iso_num_to_iso3)
    desta["iso3_2"] = desta["baci_code2"].map(iso_num_to_iso3)

    # Rebuild ccode1/ccode2 from panel
    iso3_to_ccode = (
        panel[["iso3c", "ccode"]].drop_duplicates().set_index("iso3c")["ccode"].to_dict()
    )
    desta["ccode1"] = desta["iso3_1"].map(iso3_to_ccode)
    desta["ccode2"] = desta["iso3_2"].map(iso3_to_ccode)

    # Report
    na1 = desta["iso3_1"].isna().sum()
    na2 = desta["iso3_2"].isna().sum()
    print(f"  DESTA panel: {len(desta):,} rows")
    print(f"  ISO3 NaN after fix: iso3_1={na1}, iso3_2={na2}")
    if na1 > 0:
        print(f"    Still unmapped country1: {desta[desta['iso3_1'].isna()]['country1'].unique()}")

    # Save fixed version
    desta_path = os.path.join(DATA_DIR, "desta_panel_1995_2025.csv")
    desta.to_csv(desta_path, index=False)
    print(f"  Saved: {desta_path}")

    return desta


# -- Step 2: Merge ATOP ------------------------------------------------------

def merge_atop(trade: pd.DataFrame) -> pd.DataFrame:
    """
    Merge ATOP 5.1 directed-dyad-year alliance data.
    stateA -> exporter_ccode, stateB -> importer_ccode.
    Forward-fills 2019-2024 from 2018 (ATOP's last year).
    """
    atop = pd.read_csv(os.path.join(DATA_DIR, "ATOP_5.1", "atop5_1ddyr.csv"))
    atop = atop[["stateA", "stateB", "year"] + ATOP_COLS].copy()

    # Forward-fill 2019-2024
    atop_last = atop[atop["year"] == 2018].copy()
    fill_chunks = []
    for y in range(2019, 2025):
        chunk = atop_last.copy()
        chunk["year"] = y
        fill_chunks.append(chunk)
    atop = pd.concat([atop, *fill_chunks], ignore_index=True)
    atop = atop[atop["year"] >= 1995]

    # Merge on ccode
    trade = trade.merge(
        atop,
        left_on=["exporter_ccode", "importer_ccode", "year"],
        right_on=["stateA", "stateB", "year"],
        how="left",
    ).drop(columns=["stateA", "stateB"])

    # ATOP only contains allied dyads — fill 0 for unmatched with valid ccodes
    has_both = trade["exporter_ccode"].notna() & trade["importer_ccode"].notna()
    no_match = trade["atopally"].isna()
    for col in ATOP_COLS:
        trade.loc[has_both & no_match, col] = 0

    n_ally = (trade["atopally"] == 1).sum()
    n_not = (trade["atopally"] == 0).sum()
    n_na = trade["atopally"].isna().sum()
    print(f"  ATOP: allied={n_ally:,}, not allied={n_not:,}, missing ccode={n_na:,}")

    return trade


# -- Step 3: Merge DESTA -----------------------------------------------------

def merge_desta(trade: pd.DataFrame, desta: pd.DataFrame) -> pd.DataFrame:
    """
    Merge DESTA trade agreement panel (undirected) to directed trade data.

    DESTA is undirected (country1 < country2 alphabetically), but trade data
    is directed (exporter -> importer). We merge both directions:
    - Try exporter=iso3_1, importer=iso3_2 first
    - Then fill remaining with exporter=iso3_2, importer=iso3_1

    This ensures CHN->AUS gets the same DESTA data as AUS->CHN.
    """
    desta_merge = desta[["iso3_1", "iso3_2", "year"] + DESTA_COLS].copy()

    # Direction 1: exporter=iso3_1, importer=iso3_2
    merged = trade.merge(
        desta_merge,
        left_on=["exporter", "importer", "year"],
        right_on=["iso3_1", "iso3_2", "year"],
        how="left",
    ).drop(columns=["iso3_1", "iso3_2"])

    # Direction 2: fill NaN from reverse direction
    unmatched = merged["label"].isna()
    desta_reverse = desta_merge.rename(columns={"iso3_1": "iso3_2", "iso3_2": "iso3_1"})
    reverse_match = trade.loc[unmatched].merge(
        desta_reverse,
        left_on=["exporter", "importer", "year"],
        right_on=["iso3_1", "iso3_2", "year"],
        how="left",
    ).drop(columns=["iso3_1", "iso3_2"])

    # Fill in the DESTA columns from reverse match
    for col in DESTA_COLS:
        merged.loc[unmatched, col] = reverse_match[col].values

    # Dyads with valid ISO3 but no DESTA match -> label=0 (no trade agreement)
    has_both_iso3 = trade["exporter"].notna() & trade["importer"].notna()
    still_na = merged["label"].isna()
    merged.loc[has_both_iso3 & still_na, "label"] = 0

    n_has = (merged["label"] == 1).sum()
    n_not = (merged["label"] == 0).sum()
    n_na = merged["label"].isna().sum()
    print(f"  DESTA: has agreement={n_has:,}, no agreement={n_not:,}, unmapped={n_na:,}")

    return merged


# -- Step 4: WTO Membership Filter -------------------------------------------

def filter_wto_members(
    trade: pd.DataFrame, exporter_col: str = "exporter", importer_col: str = "importer"
) -> pd.DataFrame:
    """
    Filter to keep only rows where both exporter and importer are WTO members
    in the given year (time-varying membership).
    """
    wto_mem = pd.read_csv(os.path.join(DATA_DIR, "wto_mem_list.csv"))
    join_map = wto_mem.set_index("iso3c")["year"].to_dict()

    exp_join = trade[exporter_col].map(join_map).fillna(9999)
    imp_join = trade[importer_col].map(join_map).fillna(9999)
    mask = (trade["year"] >= exp_join) & (trade["year"] >= imp_join)

    filtered = trade[mask].copy()
    print(f"  WTO filter: {len(trade):,} -> {len(filtered):,} ({len(trade) - len(filtered):,} excluded)")

    return filtered


# -- Main ---------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Dyadic Dataset Aggregation Pipeline")
    print("=" * 60)

    # Step 1: Fix DESTA panel
    print("\n[1/5] Rebuilding DESTA panel with correct ISO3 mapping...")
    desta = rebuild_desta_panel()

    # Step 2: Load base trade data
    print("\n[2/5] Loading bilateral trade data...")
    trade_agg = pd.read_csv(os.path.join(DATA_DIR, "bilateral_trade_aggregate.csv"))
    trade_sec = pd.read_csv(os.path.join(DATA_DIR, "bilateral_trade_by_section.csv"))
    print(f"  Aggregate: {len(trade_agg):,} rows")
    print(f"  Section:   {len(trade_sec):,} rows")

    # Step 3: Merge ATOP into aggregate
    print("\n[3/5] Merging ATOP alliances...")
    trade_agg = merge_atop(trade_agg)

    # Step 4: Merge DESTA into aggregate
    print("\n[4/5] Merging DESTA trade agreements...")
    trade_agg = merge_desta(trade_agg, desta)

    # Step 5: WTO membership filter
    print("\n[5/5] Filtering by WTO membership...")
    trade_wto = filter_wto_members(trade_agg)
    trade_sec_wto = filter_wto_members(trade_sec)

    # Save outputs
    print("\nSaving outputs...")

    agg_path = os.path.join(DATA_DIR, "bilateral_trade_wto.csv")
    trade_wto.to_csv(agg_path, index=False)
    print(f"  Saved: {agg_path} ({len(trade_wto):,} rows, {len(trade_wto.columns)} cols)")

    sec_path = os.path.join(DATA_DIR, "bilateral_trade_section_wto.csv")
    trade_sec_wto.to_csv(sec_path, index=False)
    print(f"  Saved: {sec_path} ({len(trade_sec_wto):,} rows)")

    # Verification
    print("\n--- Verification ---")
    for code in ["USA", "FRA", "IND", "CHN", "DEU"]:
        rows = trade_wto[trade_wto["exporter"] == code]
        desta_match = (rows["label"] == 1).sum()
        atop_match = (rows["atopally"] == 1).sum()
        print(f"  {code}: {len(rows):,} rows, DESTA={desta_match:,}, ATOP allied={atop_match:,}")

    # Spot-check: USA->CHN and CHN->USA should have same DESTA
    for e, i in [("USA", "CHN"), ("CHN", "USA")]:
        row = trade_wto[(trade_wto["exporter"] == e) & (trade_wto["importer"] == i) & (trade_wto["year"] == 2015)]
        if len(row):
            r = row.iloc[0]
            print(f"  {e}->{i} 2015: label={r['label']}, depth_rasch={r.get('depth_rasch', 'N/A')}")

    print("\nDone!")


if __name__ == "__main__":
    main()
