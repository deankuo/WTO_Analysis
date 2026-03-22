#!/usr/bin/env python3
"""
Build wto_dyadic_v2.csv from wto_cases_v2.csv.

Expands each case into dyadic rows:
  complainant-respondent   (C-R)
  third_party-respondent   (TP-R)
  complainant-third_party  (C-TP)

ISO3 / COW codes looked up from wto_mem_list.csv (+ baci_to_iso3_mapping.csv fallback).

Usage:
  python scripts/build_dyadic_v2.py
"""

import os
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def p(filename):
    return os.path.join(BASE, "Data", filename)


# ── name harmonization ────────────────────────────────────────────────────────
NAME_HARMONIZATION = {
    "European Communities":                "European Union",
    "Turkey":                              "Türkiye",
    "European Union and its Member States": "European Union",
}


def harmonize_name(name):
    name = name.strip()
    return NAME_HARMONIZATION.get(name, name)


def parse_country_field(val):
    """Split semicolon-separated country string into harmonized list."""
    if not isinstance(val, str) or not val.strip():
        return []
    return [harmonize_name(x.strip()) for x in val.split(";") if x.strip()]


# ── ISO3 / COW lookup ─────────────────────────────────────────────────────────
def build_lookup():
    wto_mem  = pd.read_csv(p("wto_mem_list.csv"))
    wto_lkp  = wto_mem.set_index("member")[["iso3c", "ccode"]].to_dict("index")
    try:
        baci_map = pd.read_csv(p("baci_to_iso3_mapping.csv"))
        baci_lkp = baci_map.set_index("country_name")[["iso3", "ccode"]].to_dict("index")
    except FileNotFoundError:
        baci_lkp = {}
    return wto_lkp, baci_lkp


def get_country_info(name, wto_lkp, baci_lkp):
    name = harmonize_name(str(name))
    if name in wto_lkp:
        return wto_lkp[name]["iso3c"], wto_lkp[name]["ccode"]
    if name in baci_lkp:
        return baci_lkp[name]["iso3"], baci_lkp[name]["ccode"]
    return None, None


# ── main build ────────────────────────────────────────────────────────────────
def build():
    wto_cases = pd.read_csv(p("wto_cases_v2.csv"), encoding="utf-8", dtype={"case": str})
    wto_lkp, baci_lkp = build_lookup()

    rows = []
    for _, row in wto_cases.iterrows():
        base = row.to_dict()
        comp  = parse_country_field(row.get("complainant",   ""))
        resp  = parse_country_field(row.get("respondent",    ""))
        third = parse_country_field(row.get("third_parties", ""))

        for c in comp:
            for r in resp:
                r_new = base.copy()
                r_new.update({"country1": c, "country2": r,
                               "relationship": "complainant-respondent"})
                rows.append(r_new)

        for tp in third:
            for r in resp:
                r_new = base.copy()
                r_new.update({"country1": tp, "country2": r,
                               "relationship": "third_party-respondent"})
                rows.append(r_new)

        for c in comp:
            for tp in third:
                r_new = base.copy()
                r_new.update({"country1": c, "country2": tp,
                               "relationship": "complainant-third_party"})
                rows.append(r_new)

    df = pd.DataFrame(rows)

    # Add ISO3 / COW codes
    res1 = df["country1"].apply(lambda x: get_country_info(x, wto_lkp, baci_lkp))
    df["iso3_1"] = [x[0] for x in res1]
    df["ccode1"] = [x[1] for x in res1]

    res2 = df["country2"].apply(lambda x: get_country_info(x, wto_lkp, baci_lkp))
    df["iso3_2"] = [x[0] for x in res2]
    df["ccode2"] = [x[1] for x in res2]

    # Reorder columns
    fixed_cols = ["case", "country1", "country2", "relationship",
                  "iso3_1", "iso3_2", "ccode1", "ccode2"]
    remaining  = [c for c in df.columns if c not in fixed_cols]
    df = df[fixed_cols + remaining]

    df.to_csv(p("wto_dyadic_v2.csv"), index=False, encoding="utf-8")
    print(f"Saved wto_dyadic_v2.csv: {len(df):,} rows from {len(wto_cases)} cases")

    # Report unmatched
    unmatched = (set(df.loc[df["iso3_1"].isna(), "country1"].unique()) |
                 set(df.loc[df["iso3_2"].isna(), "country2"].unique()))
    if unmatched:
        print(f"\nUnmatched countries ({len(unmatched)}) — add to NAME_HARMONIZATION if needed:")
        for c in sorted(unmatched):
            n = (df["country1"] == c).sum() + (df["country2"] == c).sum()
            print(f"  [{n:>3}] {c}")
    else:
        print("All countries matched.")


if __name__ == "__main__":
    build()
