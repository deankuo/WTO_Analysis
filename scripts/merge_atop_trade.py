"""
Merge ATOP 5.1 directed-dyad-year alliance data with bilateral trade dataset.

ATOP stateA -> bilateral exporter (ccode), stateB -> importer (ccode).
ATOP coverage ends 2018; years 2019-2024 are forward-filled from 2018 values.

Output: Data/bilateral_trade_atop.csv
"""

import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")

TRADE_FILE = os.path.join(DATA_DIR, "bilateral_trade_aggregate.csv")
ATOP_FILE = os.path.join(DATA_DIR, "ATOP_5.1", "atop5_1ddyr.csv")
OUTPUT_FILE = os.path.join(DATA_DIR, "bilateral_trade_atop.csv")

ATOP_COLS = ["atopally", "defense", "offense", "neutral", "nonagg", "consul"]


def merge_atop_trade() -> pd.DataFrame:
    trade = pd.read_csv(TRADE_FILE)
    atop = pd.read_csv(ATOP_FILE)

    # Keep only needed columns
    atop = atop[["stateA", "stateB", "year"] + ATOP_COLS].copy()

    # ATOP ends 2018 — forward-fill to 2024 using last observed year per dyad
    atop_last = atop[atop["year"] == atop["year"].max()].copy()
    fill_rows = []
    for fill_year in range(2019, 2025):
        chunk = atop_last.copy()
        chunk["year"] = fill_year
        fill_rows.append(chunk)
    atop = pd.concat([atop, *fill_rows], ignore_index=True)

    # Filter to 1995+ (trade data range)
    atop = atop[atop["year"] >= 1995]

    # Merge: stateA=exporter_ccode, stateB=importer_ccode
    merged = trade.merge(
        atop,
        left_on=["exporter_ccode", "importer_ccode", "year"],
        right_on=["stateA", "stateB", "year"],
        how="left",
    ).drop(columns=["stateA", "stateB"])

    # ATOP only contains allied dyads — unmatched rows with valid ccodes = no alliance (0)
    has_both_ccode = merged["exporter_ccode"].notna() & merged["importer_ccode"].notna()
    no_atop_match = merged["atopally"].isna()
    fill_mask = has_both_ccode & no_atop_match
    for col in ATOP_COLS:
        merged.loc[fill_mask, col] = 0

    # Report coverage
    n_total = len(merged)
    n_has_ccode = has_both_ccode.sum()
    n_ally = (merged["atopally"] == 1).sum()
    n_no_ally = (merged["atopally"] == 0).sum()
    n_missing = merged["atopally"].isna().sum()
    print(f"Total trade rows:   {n_total:,}")
    print(f"With both ccodes:   {n_has_ccode:,} ({n_has_ccode / n_total * 100:.1f}%)")
    print(f"  Allied (1):       {n_ally:,} ({n_ally / n_has_ccode * 100:.1f}%)")
    print(f"  Not allied (0):   {n_no_ally:,} ({n_no_ally / n_has_ccode * 100:.1f}%)")
    print(f"Missing ccode (NaN): {n_missing:,}")

    return merged


def main():
    print("Merging ATOP 5.1 with bilateral trade data")
    print("=" * 50)
    merged = merge_atop_trade()
    merged.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved: {OUTPUT_FILE} ({len(merged):,} rows)")


if __name__ == "__main__":
    main()
