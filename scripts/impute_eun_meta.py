"""
impute_eun_meta.py
==================
Imputes EUN (EU as unitary actor) rows in country_meta_1995_2024.csv.

Aggregation rules per year t (members where eu_member==1 in year t):
  gdp           : sum of member GDPs
  pop           : sum of member populations
  gdppc         : gdp * 1e6 / pop  (gdp in millions USD)
  log_gdppc     : ln(gdppc)
  log_pop       : ln(pop)
  idealpointfp  : GDP-weighted mean; 2024 falls back to idealpointfp (idealpointall universally missing)
  idealpointall : GDP-weighted mean; 2024 falls back to idealpointfp
  v2x_polyarchy : GDP-weighted mean
  v2x_libdem    : GDP-weighted mean
  v2x_regime    : GDP-weighted mean, rounded to nearest integer (ordinal 0–3)
  WGI (voice, stability, efficiency, reg_quality, law, corruption):
                  GDP-weighted mean; 2024 falls back to available members (WGI lags 1 year)
  unemployment_rate: GDP-weighted mean
  gdp_growth_rate  : computed from EUN summed GDP: (gdp_t - gdp_{t-1}) / gdp_{t-1} * 100
  fdi_inflow_usd   : sum of member FDI inflows
  region        : hard-coded "Europe"
  income        : hard-coded "High income"
  longitude     : hard-coded 4.3517  (Brussels)
  latitude      : hard-coded 50.8503 (Brussels)

Left as NaN (principled):
  idealpointlegacy : EU is not a UN member; legacy data
  cinc             : EU not a COW state; data ends 2016 for all countries anyway
  trade, fdi, exp_share, imp_share : % of GDP — intra-EU trade inflates, meaningless for EUN
  election_binary  : EU Parliament elections are supranational, not comparable to national

Usage:
    python scripts/impute_eun_meta.py              # dry-run: print summary
    python scripts/impute_eun_meta.py --write      # write changes to CSV
"""

import os
import argparse
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Data")

WGI_COLS = ["voice", "stability", "efficiency", "reg_quality", "law", "corruption"]
VDEM_COLS = ["v2x_polyarchy", "v2x_libdem", "v2x_regime"]


def gdp_weighted_mean(values: pd.Series, gdp: pd.Series) -> float:
    """GDP-weighted mean, ignoring NaN in values."""
    mask = values.notna() & gdp.notna()
    if mask.sum() == 0:
        return np.nan
    v, w = values[mask], gdp[mask]
    if w.sum() == 0:
        return np.nan
    return (v * w).sum() / w.sum()


def impute_eun(meta: pd.DataFrame, eu_mem: pd.DataFrame) -> pd.DataFrame:
    meta = meta.copy()

    members_by_year = (
        eu_mem[eu_mem["eu_member"] == 1]
        .groupby("year")["iso3c"]
        .apply(set)
    )
    years = sorted(members_by_year.index)
    print(f"Years to impute: {years[0]}–{years[-1]}")

    for year in years:
        members = members_by_year[year]
        sub = meta[(meta["iso3c"].isin(members)) & (meta["year"] == year)]
        eun_mask = (meta["iso3c"] == "EUN") & (meta["year"] == year)

        if sub.empty or eun_mask.sum() == 0:
            print(f"  WARNING: skipping {year}")
            continue

        # ── GDP / Pop / GDPPC ────────────────────────────────────────────────
        gdp_sum = sub["gdp"].sum(min_count=1)
        pop_sum = sub["pop"].sum(min_count=1)
        if pd.notna(gdp_sum) and pd.notna(pop_sum) and pop_sum > 0:
            gdppc_val = gdp_sum * 1e6 / pop_sum
            log_gdppc = np.log(gdppc_val)
        else:
            gdppc_val = log_gdppc = np.nan
        log_pop = np.log(pop_sum) if pd.notna(pop_sum) and pop_sum > 0 else np.nan

        # ── GDP growth rate (GDP-weighted mean of member rates) ──────────────
        # Using member growth rates (not EUN-sum-over-sum) avoids spurious
        # jumps when membership changes (2004 enlargement, 2021 UK exit).
        gdp_growth = gdp_weighted_mean(sub["gdp_growth_rate"], sub["gdp"])

        # ── FDI inflow (sum) ─────────────────────────────────────────────────
        fdi_inflow = sub["fdi_inflow_usd"].sum(min_count=1)

        # ── Unemployment (GDP-weighted) ──────────────────────────────────────
        unemp = gdp_weighted_mean(sub["unemployment_rate"], sub["gdp"])

        # ── Ideal points (GDP-weighted) ──────────────────────────────────────
        ip_fp = gdp_weighted_mean(sub["idealpointfp"], sub["gdp"])
        if sub["idealpointall"].notna().sum() == 0:
            ip_all = ip_fp
        else:
            ip_all = gdp_weighted_mean(sub["idealpointall"], sub["gdp"])

        # ── V-Dem (GDP-weighted) ─────────────────────────────────────────────
        vdem = {c: gdp_weighted_mean(sub[c], sub["gdp"]) for c in VDEM_COLS}
        # Round v2x_regime to nearest integer (ordinal 0–3)
        if pd.notna(vdem["v2x_regime"]):
            vdem["v2x_regime"] = int(round(vdem["v2x_regime"]))

        # ── WGI (GDP-weighted) ───────────────────────────────────────────────
        wgi = {c: gdp_weighted_mean(sub[c], sub["gdp"]) for c in WGI_COLS}

        # ── Hard-coded geographic/categorical ────────────────────────────────
        region    = "Europe"
        income    = "High income"
        longitude = 4.3517    # Brussels
        latitude  = 50.8503

        # ── Write ────────────────────────────────────────────────────────────
        meta.loc[eun_mask, "gdp"]             = gdp_sum
        meta.loc[eun_mask, "pop"]             = pop_sum
        meta.loc[eun_mask, "gdppc"]           = gdppc_val
        meta.loc[eun_mask, "log_gdppc"]       = log_gdppc
        meta.loc[eun_mask, "log_pop"]         = log_pop
        meta.loc[eun_mask, "gdp_growth_rate"] = gdp_growth
        meta.loc[eun_mask, "fdi_inflow_usd"]  = fdi_inflow
        meta.loc[eun_mask, "unemployment_rate"] = unemp
        meta.loc[eun_mask, "idealpointfp"]    = ip_fp
        meta.loc[eun_mask, "idealpointall"]   = ip_all
        for c, v in vdem.items():
            meta.loc[eun_mask, c] = v
        for c, v in wgi.items():
            meta.loc[eun_mask, c] = v
        meta.loc[eun_mask, "region"]    = region
        meta.loc[eun_mask, "income"]    = income
        meta.loc[eun_mask, "longitude"] = longitude
        meta.loc[eun_mask, "latitude"]  = latitude

        growth_str = f"{gdp_growth*100:+.1f}%" if pd.notna(gdp_growth) else "nan"
        unemp_str  = f"{unemp*100:.1f}%"    if pd.notna(unemp)      else "nan"
        print(
            f"  {year}: {len(sub):2d} members | gdppc={gdppc_val:,.0f} | "
            f"growth={growth_str} | unemp={unemp_str} | "
            f"WGI_law={wgi['law']:.2f} | polyarchy={vdem['v2x_polyarchy']:.3f} | "
            f"regime={vdem['v2x_regime']}"
        )

    return meta


def verify(original: pd.DataFrame, updated: pd.DataFrame) -> None:
    eun_orig = original[original["iso3c"] == "EUN"]
    eun_new  = updated[updated["iso3c"] == "EUN"]
    all_imputed = (
        ["gdp", "pop", "gdppc", "log_gdppc", "log_pop",
         "gdp_growth_rate", "fdi_inflow_usd", "unemployment_rate",
         "idealpointfp", "idealpointall"]
        + VDEM_COLS + WGI_COLS
        + ["region", "income", "longitude", "latitude"]
    )
    print("\n── Verification: EUN missing value counts ──")
    print(f"{'Column':<22} {'Before':>8} {'After':>8}")
    print("-" * 42)
    for c in all_imputed:
        before = eun_orig[c].isna().sum()
        after  = eun_new[c].isna().sum()
        flag = " ✓" if after == 0 else ""
        print(f"{c:<22} {before:>8} {after:>8}{flag}")

    still_missing = [c for c in eun_new.columns if eun_new[c].isna().all()]
    print(f"\nColumns still all-NaN for EUN ({len(still_missing)}): {still_missing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="Write imputed values back to country_meta_1995_2024.csv")
    args = parser.parse_args()

    meta_path   = os.path.join(DATA, "country_meta_1995_2024.csv")
    eu_mem_path = os.path.join(DATA, "eu_membership_1995_2024.csv")

    print(f"Loading {meta_path} ...")
    meta   = pd.read_csv(meta_path)
    eu_mem = pd.read_csv(eu_mem_path)

    print("Running EUN imputation ...")
    updated = impute_eun(meta, eu_mem)
    verify(meta, updated)

    if args.write:
        updated.to_csv(meta_path, index=False)
        print(f"\nSaved → {meta_path}")
    else:
        print("\nDry-run complete. Pass --write to save changes.")


if __name__ == "__main__":
    main()
