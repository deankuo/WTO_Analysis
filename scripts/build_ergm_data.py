"""
build_ergm_data.py
==================
Constructs ERGM-ready datasets from WTO dispute and trade data.

Outputs
-------
Data/wto_cases_enriched.csv         644 rows — case-level: severity + HS + year
Data/wto_dyadic_enriched.csv        8,373 rows — case-dyad: severity by role + sector trade
Data/ergm_dyad_year_eun.csv         ~545k rows — directed dyad-year, EU as EUN
Data/ergm_dyad_year_eu_disagg.csv   EU disputes disaggregated to individual member states

Design notes
------------
- Universe: bilateral_trade_wto (all WTO-member directed dyad-years, 1995-2024)
- Outcome: has_dispute = 1 when exporter filed complaint against importer in year t
- dyadic_severity: CR->case score; TP-R->0.5 placeholder; C-TP->0
- Multiple cases per dyad-year: _max (most severe) and _avg (average) versions
- Trade lags t-1/t-2/t-3; backward imputation: 1995->NaN, 1996->t-2=t-3=t-1, 1997->t-3=t-2
- Node attributes: contemporaneous (year t), 44 cols from country_meta, suffixed _1/_2
- Annual WTO counts: n_complainant_t, n_respondent_t, n_tp_t per country-year
- EUN DESTA fix: inherit from EU member state agreements; EUN ATOP=0 by design
- EU disagg: 395 EUN-only->expand; 37 mixed->drop EUN keep individuals; 30 individual-only->unchanged
- Taiwan: NaN for ideal points (not UN member) — expected
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── paths ──────────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Data")
OUT  = os.path.join(DATA, "Output")

def p(name): return os.path.join(DATA, name)
def o(name): return os.path.join(OUT, name)

# ── country_meta columns to keep (48 total, drop noisy/redundant cols) ─────────
META_EXCLUDE = {
    "nvotesfp","qofp","q5fp","q10fp","q50fp","q90fp","q95fp","q100fp",
    "nvotesall","qoall","q5all","q10all","q50all","q90all","q95all","q100all",
    "nvotesLegacy","v2eltype_0","v2eltype_1","v2eltype_6","v2eltype_7",
    "is_leg_elec","is_pres_elec","gdp","milex","milper","pec","tpop","upop",
}
# When merging node attributes into the dyadic dataset, keep only these identifier
# columns from country_meta (the rest are attribute cols we'll suffix _1/_2)
META_ID_COLS = {"iso3c", "ccode", "year"}
# Identifier cols from country_meta to DROP when suffixing (we already have them
# in bilateral_trade_wto as exporter/importer + exporter_ccode/importer_ccode)
META_DROP_ON_MERGE = {"country", "stateabb", "un_country_name", "COWcode",
                      "wto_accession_year", "eu_member", "euro_join_year",
                      "euro_member"}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_year(date_series):
    """Parse a date string column and return the integer year."""
    return pd.to_datetime(date_series, errors="coerce").dt.year


def case_str_to_int(s):
    """'DS123' -> 123; already int -> as-is."""
    if isinstance(s, str):
        return int(s.replace("DS", "").strip())
    return int(s)


def backward_impute_lags(df, base_col, lag_cols):
    """
    Apply backward imputation for early years where lagged data is unavailable.
    lag_cols: dict {lag_num: col_name} e.g. {1: 'x_t1', 2: 'x_t2', 3: 'x_t3'}
    Rules (applied per row based on df['year']):
      1995 -> all lags NaN  (no data before 1995)
      1996 -> t-2 = t-3 = t-1
      1997 -> t-3 = t-2
    """
    df = df.copy()
    mask_1996 = df["year"] == 1996
    mask_1997 = df["year"] == 1997
    if 2 in lag_cols and 1 in lag_cols:
        df.loc[mask_1996, lag_cols[2]] = df.loc[mask_1996, lag_cols[1]]
    if 3 in lag_cols and 1 in lag_cols:
        df.loc[mask_1996, lag_cols[3]] = df.loc[mask_1996, lag_cols[1]]
    if 3 in lag_cols and 2 in lag_cols:
        df.loc[mask_1997, lag_cols[3]] = df.loc[mask_1997, lag_cols[2]]
    return df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: wto_cases_enriched.csv
# ══════════════════════════════════════════════════════════════════════════════

def build_cases_enriched():
    """Join case metadata with severity scores and HS sections."""
    print("[Step 1] Building wto_cases_enriched.csv ...")

    cases    = pd.read_csv(p("wto_cases_v2.csv"))
    severity = pd.read_csv(o("severity_scores_raw.csv"))
    hs       = pd.read_csv(o("case_hs_sections.csv"))
    hs_exp   = pd.read_csv(o("case_section_expanded.csv"))

    # Standardize case_id: int
    cases["case_id"] = cases["case"].apply(case_str_to_int)

    # Extract consultation_year; fallback to panel_requested
    cases["consultation_year"] = extract_year(cases["consultations_requested"])
    fallback_year = extract_year(cases["panel_requested"])
    cases["consultation_year"] = cases["consultation_year"].fillna(fallback_year)
    cases["consultation_year"] = cases["consultation_year"].astype("Int64")

    # Merge severity (DS1-DS626 only)
    sev_cols = ["case_id", "rhetorical_aggressiveness", "systemic_reach",
                "escalation_ultimatum", "domestic_victimhood", "severity_score",
                "reasoning", "evidence"]
    cases = cases.merge(severity[sev_cols], on="case_id", how="left")

    # Merge HS sections
    hs_cols = ["case_id", "hs_sections", "title_hs_sections", "case_type",
               "extraction_method", "confidence"]
    cases = cases.merge(hs[hs_cols], on="case_id", how="left")

    # Flag horizontal policy cases (all 21 sections)
    sections_per_case = hs_exp.groupby("case_id")["hs_section"].count()
    cases["is_horizontal_policy"] = cases["case_id"].map(
        lambda x: sections_per_case.get(x, 0) == 21
    ).fillna(False)

    out_path = p("wto_cases_enriched.csv")
    cases.to_csv(out_path, index=False)
    print(f"  -> {out_path}  ({len(cases)} rows, {len(cases.columns)} cols)")
    return cases


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: wto_dyadic_enriched.csv
# ══════════════════════════════════════════════════════════════════════════════

def build_dyadic_enriched(cases_enriched):
    """
    Join wto_dyadic_v2 with case attributes; assign dyadic_severity by role;
    add disputed sector trade for t, t-1, t-2, t-3.
    """
    print("[Step 2] Building wto_dyadic_enriched.csv ...")

    dyadic  = pd.read_csv(p("wto_dyadic_v2.csv"))
    sec_tr  = pd.read_csv(p("bilateral_trade_section_wto.csv"),
                          usecols=["year","exporter","importer",
                                   "section_num","trade_value_ij_s",
                                   "partner_sector_dependence"])
    hs_exp  = pd.read_csv(o("case_section_expanded.csv"))

    # Standardize case_id
    dyadic["case_id"] = dyadic["case"].apply(case_str_to_int)

    # Merge case-level attributes
    case_attrs = cases_enriched[[
        "case_id","consultation_year","severity_score",
        "hs_sections","case_type","is_horizontal_policy",
        "rhetorical_aggressiveness","systemic_reach",
        "escalation_ultimatum","domestic_victimhood"
    ]].copy()
    dyadic = dyadic.merge(case_attrs, on="case_id", how="left")

    # Assign dyadic_severity by relationship role
    def assign_severity(row):
        rel = row["relationship"]
        score = row["severity_score"]
        if rel == "complainant-respondent":
            return score if pd.notna(score) else np.nan
        elif rel == "third_party-respondent":
            return 0.5   # placeholder until TP scoring complete
        elif rel == "complainant-third_party":
            return 0.0
        return np.nan

    dyadic["dyadic_severity"] = dyadic.apply(assign_severity, axis=1)

    # ── Disputed sector trade (both directions) ────────────────────────────────
    # Build case -> list of hs_section numbers
    case_sections = hs_exp.groupby("case_id")["hs_section"].apply(list).to_dict()

    # Aggregate section trade to (exporter, importer, year) for sets of sections
    # We'll do this efficiently: group sec_tr by (exporter, importer, year, section_num)
    sec_tr_idx = sec_tr.set_index(["exporter","importer","year","section_num"])

    def get_disputed_trade(exporter, importer, year, sections):
        """Sum trade_value and avg partner_sector_dependence for given sections."""
        if not sections or pd.isna(year):
            return np.nan, np.nan
        year = int(year)
        rows = []
        for sec in sections:
            key = (exporter, importer, year, sec)
            try:
                rows.append(sec_tr_idx.loc[key])
            except KeyError:
                pass
        if not rows:
            return np.nan, np.nan
        sub = pd.DataFrame(rows)
        return sub["trade_value_ij_s"].sum(), sub["partner_sector_dependence"].mean()

    print("  Computing disputed sector trade (t, t-1, t-2, t-3) — may take ~3 min ...")

    results = []
    for _, row in dyadic.iterrows():
        c_year = row["consultation_year"]
        sections = case_sections.get(row["case_id"], [])
        i1, i2 = row["iso3_1"], row["iso3_2"]
        entry = {}
        for lag, lbl in [(0,"t0"),(1,"t1"),(2,"t2"),(3,"t3")]:
            y = None if pd.isna(c_year) else int(c_year) - lag
            tv_ij, dep_ij = get_disputed_trade(i1, i2, y, sections)
            tv_ji, dep_ji = get_disputed_trade(i2, i1, y, sections)
            entry[f"disputed_trade_ij_{lbl}"]  = tv_ij
            entry[f"disputed_dep_ij_{lbl}"]    = dep_ij
            entry[f"disputed_trade_ji_{lbl}"]  = tv_ji
            entry[f"disputed_dep_ji_{lbl}"]    = dep_ji
        results.append(entry)

    trade_df = pd.DataFrame(results)
    dyadic = pd.concat([dyadic.reset_index(drop=True),
                        trade_df.reset_index(drop=True)], axis=1)

    # ── Multiple cases per dyad-year: flag most_severe row ────────────────────
    # For C-R relationship only; for TP, we'll handle in ergm step
    cr_mask = dyadic["relationship"] == "complainant-respondent"
    cr = dyadic[cr_mask].copy()
    cr_best = cr.sort_values("severity_score", ascending=False, na_position="last")\
                .groupby(["iso3_1","iso3_2","consultation_year"]).head(1)\
                .set_index(["case_id","iso3_1","iso3_2","consultation_year"]).index
    dyadic["is_most_severe_for_dyad_year"] = False
    idx = dyadic[cr_mask].apply(
        lambda r: (r["case_id"], r["iso3_1"], r["iso3_2"], r["consultation_year"]) in cr_best,
        axis=1
    )
    dyadic.loc[dyadic[cr_mask].index, "is_most_severe_for_dyad_year"] = idx.values

    out_path = p("wto_dyadic_enriched.csv")
    dyadic.to_csv(out_path, index=False)
    print(f"  -> {out_path}  ({len(dyadic)} rows, {len(dyadic.columns)} cols)")
    return dyadic


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Annual WTO activity counts per country-year
# ══════════════════════════════════════════════════════════════════════════════

def build_annual_wto_counts(dyadic_enriched):
    """
    Count how many cases each country participated in per year (not cumulative).
    Returns a DataFrame with columns: iso3c, year, n_complainant_t, n_respondent_t, n_tp_t
    """
    print("[Step 3] Building annual WTO activity counts ...")

    cr = dyadic_enriched[
        dyadic_enriched["relationship"] == "complainant-respondent"
    ][["case_id","iso3_1","iso3_2","consultation_year"]].drop_duplicates()

    tp_r = dyadic_enriched[
        dyadic_enriched["relationship"] == "third_party-respondent"
    ][["case_id","iso3_1","consultation_year"]].drop_duplicates()

    c_tp = dyadic_enriched[
        dyadic_enriched["relationship"] == "complainant-third_party"
    ][["case_id","iso3_2","consultation_year"]].drop_duplicates()

    # Complainant count
    n_comp = cr.groupby(["iso3_1","consultation_year"])["case_id"].nunique()\
               .reset_index().rename(columns={"iso3_1":"iso3c",
                                              "consultation_year":"year",
                                              "case_id":"n_complainant_t"})
    # Respondent count
    n_resp = cr.groupby(["iso3_2","consultation_year"])["case_id"].nunique()\
               .reset_index().rename(columns={"iso3_2":"iso3c",
                                              "consultation_year":"year",
                                              "case_id":"n_respondent_t"})
    # Third-party count (country appears as TP in any case)
    tp_all = pd.concat([
        tp_r.rename(columns={"iso3_1":"iso3c"})[["iso3c","consultation_year","case_id"]],
        c_tp.rename(columns={"iso3_2":"iso3c"})[["iso3c","consultation_year","case_id"]],
    ])
    n_tp = tp_all.groupby(["iso3c","consultation_year"])["case_id"].nunique()\
                 .reset_index().rename(columns={"consultation_year":"year",
                                                "case_id":"n_tp_t"})

    counts = n_comp.merge(n_resp, on=["iso3c","year"], how="outer")\
                   .merge(n_tp,  on=["iso3c","year"], how="outer")\
                   .fillna(0)
    counts["n_complainant_t"] = counts["n_complainant_t"].astype(int)
    counts["n_respondent_t"]  = counts["n_respondent_t"].astype(int)
    counts["n_tp_t"]          = counts["n_tp_t"].astype(int)
    counts["year"] = counts["year"].astype("Int64")
    print(f"  Annual counts: {len(counts)} country-year rows with WTO activity")
    return counts


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: EUN DESTA fix + EUN node attribute aggregation
# ══════════════════════════════════════════════════════════════════════════════

def fix_eun_desta(trade_df, eu_mem_df):
    """
    EUN rows in bilateral_trade_wto have label=0 because DESTA records EU
    trade agreements through individual member states.
    Fix: for each (EUN, partner, year), check if any EU member has label=1
    with that partner; if so, inherit the DESTA variables.
    """
    print("[Step 4a] Fixing EUN DESTA values ...")

    desta_cols = ["label","number","base_treaty","name","entry_type",
                  "typememb","depth_index","depth_rasch","flexrigid",
                  "flexescape","enforce","enforce01"]

    # Build EU member set per year
    eu_by_year = eu_mem_df[eu_mem_df["eu_member"]==1]\
                     .groupby("year")["iso3c"].apply(set).to_dict()

    # Get all individual EU member rows in bilateral_trade_wto
    all_eu_iso = set(eu_mem_df["iso3c"].unique())
    eu_member_rows = trade_df[trade_df["exporter"].isin(all_eu_iso) &
                              ~trade_df["exporter"].eq("EUN")].copy()

    # For each (partner, year), find best DESTA match among EU members
    # "Best" = label=1 with highest depth_index
    eu_desta = eu_member_rows[eu_member_rows["label"]==1][
        ["importer","year"] + desta_cols
    ].sort_values("depth_index", ascending=False, na_position="last")\
     .drop_duplicates(subset=["importer","year"])

    # Merge onto EUN rows
    eun_mask = trade_df["exporter"] == "EUN"
    eun_rows = trade_df[eun_mask].copy()
    eun_rows = eun_rows.drop(columns=desta_cols)
    eun_rows = eun_rows.merge(eu_desta, on=["importer","year"], how="left")

    # Also fix importer=EUN (EUN as importer)
    eun_imp_mask = trade_df["importer"] == "EUN"
    eun_imp_rows = trade_df[eun_imp_mask].copy()
    eu_desta_exp = eu_member_rows[eu_member_rows["label"]==1][
        ["exporter","year"] + desta_cols
    ].sort_values("depth_index", ascending=False, na_position="last")\
     .drop_duplicates(subset=["exporter","year"])
    eun_imp_rows = eun_imp_rows.drop(columns=desta_cols)
    eun_imp_rows = eun_imp_rows.merge(eu_desta_exp, on=["exporter","year"], how="left")

    # Reconstruct
    non_eun = trade_df[~eun_mask & ~eun_imp_mask]
    fixed = pd.concat([non_eun, eun_rows, eun_imp_rows], ignore_index=True)
    n_fixed = (eun_rows["label"]==1).sum() + (eun_imp_rows["label"]==1).sum()
    print(f"  EUN DESTA rows updated: {n_fixed} (from 0 -> 1)")
    return fixed


def build_eun_node_attrs(meta_df, eu_mem_df):
    """
    Aggregate numeric attributes (gdppc, pop, V-Dem, etc.) for EUN from individual
    EU member states.  WTO participation columns (complainant/respondent/cum_*) are
    intentionally NOT computed here — they come from the existing EUN rows in
    country_meta (which correctly track EU's collective WTO filings under
    "European Communities" / "European Union").
      - sum: pop
      - average (GDP-weighted): all other eligible numeric cols
    Returns a DataFrame with iso3c='EUN' and year, used to fill NaN cols in patching step.
    """
    print("[Step 4b] Aggregating EUN node attributes from member states ...")

    # Cols we keep in the final dataset
    all_keep = [c for c in meta_df.columns if c not in META_EXCLUDE]
    num_cols = meta_df[all_keep].select_dtypes(include="number").columns.tolist()
    num_cols = [c for c in num_cols if c not in {"ccode","year","COWcode"}]

    # Columns to skip: WTO participation data comes from existing EUN rows in
    # country_meta (correct collective EU cases) — don't aggregate from member states.
    skip_cols = {"complainant", "respondent", "third_party", "wto_participant",
                 "cum_complainant", "cum_respondent", "cum_third_party",
                 "wto_member", "wto_accession_year",
                 "eu_member", "euro_join_year", "euro_member"}

    sum_cols = ["pop"]   # sum across EU members
    avg_cols = [c for c in num_cols
                if c not in skip_cols and c not in sum_cols and c != "pop"]

    eu_by_year = eu_mem_df[eu_mem_df["eu_member"]==1].groupby("year")["iso3c"].apply(set)

    rows = []
    for year, members in eu_by_year.items():
        sub = meta_df[(meta_df["iso3c"].isin(members)) & (meta_df["year"]==year)]
        if sub.empty:
            continue
        row = {"iso3c":"EUN","year":year}
        for c in sum_cols:
            row[c] = sub[c].sum(min_count=1)
        # GDP-weighted average where possible
        w = sub["pop"].fillna(sub["pop"].median())  # fallback weight
        w = w / w.sum() if w.sum() > 0 else pd.Series(1/len(sub), index=sub.index)
        for c in avg_cols:
            valid = sub[c].dropna()
            if valid.empty:
                row[c] = np.nan
            else:
                valid_w = w.loc[valid.index]
                valid_w = valid_w / valid_w.sum()
                row[c] = (valid * valid_w).sum()
        rows.append(row)

    eun_attrs = pd.DataFrame(rows)
    print(f"  EUN node attrs built: {len(eun_attrs)} year rows")
    return eun_attrs


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: TP covariates
# ══════════════════════════════════════════════════════════════════════════════

def build_tp_covariates(dyadic_enriched):
    """
    Build TP covariate: for each (i, j, year), has country i historically
    acted as TP in any case where j was the complainant (i supports j)?

    Returns DataFrame with cols: iso3_i, iso3_j, year, tp_with_j_comp_i, tp_count_i_supporting_j
    """
    print("[Step 5] Building TP covariates ...")

    # complainant-third_party rows: iso3_1 = complainant (j), iso3_2 = third_party (i)
    c_tp = dyadic_enriched[dyadic_enriched["relationship"]=="complainant-third_party"]\
               [["iso3_1","iso3_2","consultation_year","case_id"]].dropna(subset=["consultation_year"])
    c_tp = c_tp.rename(columns={"iso3_1":"iso3_j","iso3_2":"iso3_i"})
    c_tp["consultation_year"] = c_tp["consultation_year"].astype(int)

    # Historical flag: for each (i, j), cumulative count up to year t
    tp_hist = c_tp.groupby(["iso3_i","iso3_j","consultation_year"])["case_id"]\
                  .nunique().reset_index().rename(columns={"case_id":"tp_count_year"})
    tp_hist = tp_hist.sort_values(["iso3_i","iso3_j","consultation_year"])
    tp_hist["tp_count_i_supporting_j"] = tp_hist.groupby(["iso3_i","iso3_j"])["tp_count_year"]\
                                                 .cumsum()
    # Flag: any prior TP support (before year t, not same year)
    tp_hist["tp_with_j_comp_i"] = (tp_hist["tp_count_i_supporting_j"] > 0).astype(int)

    # Lag by 1: the covariate at year t should reflect activity through year t-1
    tp_hist["year"] = tp_hist["consultation_year"] + 1

    result = tp_hist[["iso3_i","iso3_j","year","tp_with_j_comp_i","tp_count_i_supporting_j"]]
    print(f"  TP covariate rows: {len(result)}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6: Build ergm_dyad_year_eun.csv
# ══════════════════════════════════════════════════════════════════════════════

def build_ergm_eun(dyadic_enriched, annual_counts, tp_covariates, eun_node_attrs):
    """
    Build the main ERGM directed dyad-year dataset with EUN as unitary EU actor.
    Universe: bilateral_trade_wto.
    """
    print("[Step 6] Building ergm_dyad_year_eun.csv ...")

    trade    = pd.read_csv(p("bilateral_trade_wto.csv"))
    meta     = pd.read_csv(p("country_meta_1995_2024.csv"))
    eu_mem   = pd.read_csv(p("eu_membership_1995_2024.csv"))

    # Fix EUN DESTA
    trade = fix_eun_desta(trade, eu_mem)

    # Meta column selection
    keep_cols = [c for c in meta.columns if c not in META_EXCLUDE]
    meta = meta[keep_cols].copy()

    # Patch EUN node attributes:
    # Keep existing EUN rows (correct WTO participation, complainant/respondent/cum_* data).
    # Fill only NaN columns (gdppc, pop, V-Dem, etc.) from member-state aggregated attrs.
    # Hard-override EU identity columns that are wrong (0/NaN) in the source data.
    eun_existing_df = meta[meta["iso3c"]=="EUN"].copy()
    meta = meta[meta["iso3c"]!="EUN"].copy()

    agg_fill_cols = [c for c in eun_node_attrs.columns if c not in ("iso3c","year")]
    eun_merged = eun_existing_df.merge(
        eun_node_attrs[["year"] + agg_fill_cols],
        on="year", how="left", suffixes=("","_agg")
    )
    for col in agg_fill_cols:
        agg_col = f"{col}_agg"
        if agg_col in eun_merged.columns:
            eun_merged[col] = eun_merged[col].fillna(eun_merged[agg_col])
            eun_merged = eun_merged.drop(columns=[agg_col])

    # Hard overrides regardless of existing values
    eun_merged["eu_member"]      = 1
    eun_merged["euro_join_year"] = 1999
    eun_merged["euro_member"]    = (eun_merged["year"] >= 1999).astype(int)

    meta = pd.concat([meta, eun_merged], ignore_index=True)

    # Merge annual counts into meta
    meta = meta.merge(annual_counts, on=["iso3c","year"], how="left")
    meta[["n_complainant_t","n_respondent_t","n_tp_t"]] = \
        meta[["n_complainant_t","n_respondent_t","n_tp_t"]].fillna(0).astype(int)

    # ── Dispute aggregation: max and avg severity per (exporter, importer, year) ──
    cr = dyadic_enriched[dyadic_enriched["relationship"]=="complainant-respondent"].copy()
    cr = cr.rename(columns={"iso3_1":"exporter","iso3_2":"importer"})
    cr = cr.dropna(subset=["consultation_year"])
    cr["year"] = cr["consultation_year"].astype(int)

    # HS section dummies (from most severe case per dyad-year)
    hs_exp = pd.read_csv(o("case_section_expanded.csv"))
    case_sections = hs_exp.groupby("case_id")["hs_section"].apply(list).to_dict()

    def get_section_dummies(case_id):
        secs = case_sections.get(case_id, [])
        return {f"section_{s}": 1 for s in secs}

    # Group C-R by dyad-year
    grp_cols = ["exporter","importer","year"]

    # Aggregate C-R disputes per dyad-year (avoid groupby.apply which loses group keys in pandas 2.x)
    sec_cols = [f"section_{i}" for i in range(1, 22)]
    cr_sorted = cr.sort_values("severity_score", ascending=False, na_position="last")
    cr_best   = cr_sorted.groupby(grp_cols, sort=False).first().reset_index()

    cr_agg = cr.groupby(grp_cols).agg(
        dispute_count    = ("case_id",         "count"),
        severity_avg     = ("severity_score",   "mean"),
        dyadic_severity_avg = ("dyadic_severity", "mean"),
    ).reset_index()
    cr_agg["has_dispute"] = 1

    best_cols = grp_cols + ["case_id","severity_score","dyadic_severity"]
    dispute_agg = cr_agg.merge(
        cr_best[best_cols].rename(columns={
            "case_id"         : "case_id_max",
            "severity_score"  : "severity_max",
            "dyadic_severity" : "dyadic_severity_max",
        }),
        on=grp_cols, how="left",
    )

    # HS section dummies from most severe case per dyad-year
    for c in sec_cols:
        dispute_agg[c] = 0
    for idx, row in dispute_agg.iterrows():
        cid = row["case_id_max"]
        if pd.notna(cid):
            for s in case_sections.get(int(cid), []):
                col = f"section_{s}"
                if col in dispute_agg.columns:
                    dispute_agg.at[idx, col] = 1

    # ── Build trade lags ───────────────────────────────────────────────────────
    trade_lag_cols = ["total_trade_ij","export_dependence","n_products_ij",
                      "n_sections_ij","trade_dependence","atopally","defense",
                      "offense","neutral","nonagg","consul","label","depth_index",
                      "depth_rasch","enforce","enforce01"]
    existing_lag_cols = [c for c in trade_lag_cols if c in trade.columns]

    trade_base = trade[["year","exporter","importer"] + existing_lag_cols].copy()

    lags = {}
    for lag in [1, 2, 3]:
        lag_df = trade_base.copy()
        lag_df["year"] = lag_df["year"] + lag   # shift up so t-1 aligns with year t
        rename = {c: f"{c}_t{lag}" for c in existing_lag_cols}
        lag_df = lag_df.rename(columns=rename)
        lags[lag] = lag_df

    # Start from the full trade universe (year t)
    df = trade.copy()

    for lag, lag_df in lags.items():
        df = df.merge(lag_df, on=["year","exporter","importer"], how="left")

    # Apply backward imputation to trade lag cols
    for base_col in existing_lag_cols:
        lag_map = {1: f"{base_col}_t1", 2: f"{base_col}_t2", 3: f"{base_col}_t3"}
        df = backward_impute_lags(df, base_col, lag_map)

    # ── Merge dispute info ─────────────────────────────────────────────────────
    df = df.merge(dispute_agg, on=grp_cols, how="left")
    df["has_dispute"] = df["has_dispute"].fillna(0).astype(int)
    df["dispute_count"] = df["dispute_count"].fillna(0).astype(int)
    for c in sec_cols:
        df[c] = df[c].fillna(0).astype(int)

    # ── Add disputed sector trade from wto_dyadic_enriched ────────────────────
    # Only for C-R relationships; aggregate _max and _avg per dyad-year
    disp_trade_cols = [c for c in dyadic_enriched.columns if c.startswith("disputed_")]
    cr_dt = dyadic_enriched[dyadic_enriched["relationship"]=="complainant-respondent"].copy()
    cr_dt = cr_dt.rename(columns={"iso3_1":"exporter","iso3_2":"importer"})
    cr_dt = cr_dt.dropna(subset=["consultation_year"])
    cr_dt["year"] = cr_dt["consultation_year"].astype(int)
    cr_dt_agg_max = cr_dt.sort_values("severity_score", ascending=False, na_position="last")\
                         .groupby(grp_cols)[disp_trade_cols].first().reset_index()
    cr_dt_agg_avg = cr_dt.groupby(grp_cols)[disp_trade_cols].mean().reset_index()
    cr_dt_agg_avg.columns = [f"{c}_avg" if c in disp_trade_cols else c
                              for c in cr_dt_agg_avg.columns]
    cr_dt_agg_max.columns = [f"{c}_max" if c in disp_trade_cols else c
                              for c in cr_dt_agg_max.columns]
    df = df.merge(cr_dt_agg_max, on=grp_cols, how="left")
    df = df.merge(cr_dt_agg_avg, on=grp_cols, how="left")

    # ── Merge node attributes (contemporaneous, suffixed _1/_2) ──────────────
    meta_attr_cols = [c for c in meta.columns
                      if c not in META_DROP_ON_MERGE and c not in {"iso3c","year"}]
    meta_slim = meta[["iso3c","year"] + meta_attr_cols].copy()

    df = df.merge(meta_slim.rename(columns={c: f"{c}_1" for c in meta_attr_cols}
                                   | {"iso3c":"exporter"}),
                  on=["exporter","year"], how="left")
    df = df.merge(meta_slim.rename(columns={c: f"{c}_2" for c in meta_attr_cols}
                                   | {"iso3c":"importer"}),
                  on=["importer","year"], how="left")

    # ── Merge TP covariates ────────────────────────────────────────────────────
    tp_cov = tp_covariates.rename(columns={"iso3_i":"exporter","iso3_j":"importer"})
    df = df.merge(tp_cov, on=["exporter","importer","year"], how="left")
    df["tp_with_j_comp_i"] = df["tp_with_j_comp_i"].fillna(0).astype(int)
    df["tp_count_i_supporting_j"] = df["tp_count_i_supporting_j"].fillna(0).astype(int)

    out_path = p("ergm_dyad_year_eun.csv")
    df.to_csv(out_path, index=False)
    print(f"  -> {out_path}  ({len(df):,} rows, {len(df.columns)} cols)")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7: Build ergm_dyad_year_eu_disagg.csv
# ══════════════════════════════════════════════════════════════════════════════

def build_ergm_eu_disagg(ergm_eun, dyadic_enriched):
    """
    EU-disaggregated robustness version.
    Rules:
      - 395 EUN-only cases: EUN dispute flags propagated to individual EU member rows
      - 37 mixed cases (EUN + individual EU members both listed): drop EUN rows, keep individuals
      - 30 individual-EU-only cases: unchanged (already individual member rows)
    Individual EU member rows are already in ergm_eun (from bilateral_trade_wto).
    We only need to:
      1. Propagate dispute flags from EUN rows to individual member rows (EUN-only cases)
      2. Drop EUN rows
    """
    print("[Step 7] Building ergm_dyad_year_eu_disagg.csv ...")

    eu_mem = pd.read_csv(p("eu_membership_1995_2024.csv"))
    eu_by_year = eu_mem[eu_mem["eu_member"]==1]\
                     .groupby("year")["iso3c"].apply(set).to_dict()

    # Identify EUN-only vs mixed cases
    dyadic = pd.read_csv(p("wto_dyadic_v2.csv"))
    dyadic["case_id"] = dyadic["case"].apply(case_str_to_int)
    eu_all_iso = set(eu_mem["iso3c"].unique())

    eun_cases = set(dyadic[(dyadic["iso3_1"]=="EUN")|(dyadic["iso3_2"]=="EUN")]["case_id"])
    mixed_cases = set()
    for cid in eun_cases:
        rows = dyadic[dyadic["case_id"]==cid]
        has_indiv = any(
            (r in eu_all_iso and r != "EUN")
            for r in rows["iso3_1"].tolist() + rows["iso3_2"].tolist()
        )
        if has_indiv:
            mixed_cases.add(cid)
    eun_only_cases = eun_cases - mixed_cases

    print(f"  EUN-only cases: {len(eun_only_cases)}  |  Mixed: {len(mixed_cases)}")

    df = ergm_eun.copy()

    # For EUN-only cases: find rows where exporter=EUN or importer=EUN and has_dispute=1
    # Propagate has_dispute=1 to individual EU member rows in the same year
    dispute_cols = ["has_dispute","dispute_count","case_id_max","severity_max","severity_avg",
                    "dyadic_severity_max","dyadic_severity_avg"] + \
                   [f"section_{i}" for i in range(1,22)] + \
                   [c for c in df.columns if c.startswith("disputed_")]

    # Get EUN dispute rows for EUN-only cases
    cr_eun_only = dyadic_enriched[
        (dyadic_enriched["relationship"]=="complainant-respondent") &
        (dyadic_enriched["case_id"].isin(eun_only_cases))
    ].copy()
    cr_eun_only = cr_eun_only.rename(columns={"iso3_1":"exporter","iso3_2":"importer"})
    cr_eun_only = cr_eun_only.dropna(subset=["consultation_year"])
    cr_eun_only["year"] = cr_eun_only["consultation_year"].astype(int)

    # For each EUN-involved row, expand to individual EU members
    expanded_flags = []
    for _, row in cr_eun_only.iterrows():
        yr = row["year"]
        eu_members_yr = eu_by_year.get(yr, set())
        if row["exporter"] == "EUN":
            for mem in eu_members_yr:
                expanded_flags.append({
                    "exporter": mem, "importer": row["importer"], "year": yr,
                    "_prop_has_dispute": 1,
                    "_prop_case_id_max": row.get("case_id", np.nan),
                    "_prop_severity_max": row.get("severity_score", np.nan),
                })
        elif row["importer"] == "EUN":
            for mem in eu_members_yr:
                expanded_flags.append({
                    "exporter": row["exporter"], "importer": mem, "year": yr,
                    "_prop_has_dispute": 1,
                    "_prop_case_id_max": row.get("case_id", np.nan),
                    "_prop_severity_max": row.get("severity_score", np.nan),
                })

    if expanded_flags:
        exp_df = pd.DataFrame(expanded_flags)
        # Aggregate: if multiple cases propagate to same (exporter, importer, year),
        # take max severity
        exp_agg = exp_df.sort_values("_prop_severity_max", ascending=False, na_position="last")\
                        .groupby(["exporter","importer","year"]).first().reset_index()

        # Merge propagated flags onto df (only where rows exist)
        df = df.merge(exp_agg[["exporter","importer","year",
                                "_prop_has_dispute","_prop_case_id_max","_prop_severity_max"]],
                      on=["exporter","importer","year"], how="left")
        mask = df["_prop_has_dispute"].notna()
        df.loc[mask, "has_dispute"]   = 1
        df.loc[mask & df["case_id_max"].isna(), "case_id_max"]   = df.loc[mask, "_prop_case_id_max"]
        df.loc[mask & df["severity_max"].isna(), "severity_max"] = df.loc[mask, "_prop_severity_max"]
        df = df.drop(columns=["_prop_has_dispute","_prop_case_id_max","_prop_severity_max"])

    # Drop EUN rows
    df = df[(df["exporter"] != "EUN") & (df["importer"] != "EUN")].copy()

    out_path = p("ergm_dyad_year_eu_disagg.csv")
    df.to_csv(out_path, index=False)
    print(f"  -> {out_path}  ({len(df):,} rows, {len(df.columns)} cols)")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8: Verification summary
# ══════════════════════════════════════════════════════════════════════════════

def verify_outputs():
    """Print a quick summary of all output files."""
    print("\n[Step 8] Verification summary")
    print("=" * 60)
    files = [
        ("wto_cases_enriched.csv",       "Data"),
        ("wto_dyadic_enriched.csv",      "Data"),
        ("ergm_dyad_year_eun.csv",       "Data"),
        ("ergm_dyad_year_eu_disagg.csv", "Data"),
    ]
    for fname, loc in files:
        path = p(fname) if loc=="Data" else o(fname)
        if os.path.exists(path):
            df_full = pd.read_csv(path, nrows=0)
            total = sum(1 for _ in open(path, encoding="utf-8")) - 1
            # Rough line count; for files with embedded newlines, load to get exact count
            try:
                exact = len(pd.read_csv(path, usecols=[df_full.columns[0]]))
            except Exception:
                exact = total
            print(f"  {fname}: {exact:,} rows x {len(df_full.columns)} cols")
            # Key checks
            if "has_dispute" in df_full.columns:
                hd = pd.read_csv(path, usecols=["has_dispute"])
                print(f"    has_dispute: {hd['has_dispute'].sum():,} dispute rows "
                      f"/ {len(hd):,} total ({100*hd['has_dispute'].mean():.2f}%)")
        else:
            print(f"  {fname}: NOT FOUND")
    print("=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("Building ERGM datasets ...\n")

    # Step 1
    cases_enriched = build_cases_enriched()

    # Step 2
    dyadic_enriched = build_dyadic_enriched(cases_enriched)

    # Step 3
    annual_counts = build_annual_wto_counts(dyadic_enriched)

    # Step 4
    eu_mem = pd.read_csv(p("eu_membership_1995_2024.csv"))
    meta   = pd.read_csv(p("country_meta_1995_2024.csv"))
    keep_cols = [c for c in meta.columns if c not in META_EXCLUDE]
    eun_attrs = build_eun_node_attrs(meta[keep_cols], eu_mem)

    # Step 5
    tp_covariates = build_tp_covariates(dyadic_enriched)

    # Step 6
    ergm_eun = build_ergm_eun(dyadic_enriched, annual_counts, tp_covariates, eun_attrs)

    # Step 7
    build_ergm_eu_disagg(ergm_eun, dyadic_enriched)

    # Step 8
    verify_outputs()

    print("\nDone.")


if __name__ == "__main__":
    main()
