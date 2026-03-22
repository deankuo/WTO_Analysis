#!/usr/bin/env python3
"""
WTO Dispute Settlement Network Analysis
========================================
Builds annual dispute networks from wto_cases_v2.csv and computes:
  - Basic stats: nodes, edges, disputes, density, avg degree
  - Relationship counts: CR, CTP, RTP edges
  - Conflict density and support ratio
  - Louvain community detection + modularity
  - Top countries by degree and betweenness centrality
  - Top countries by role (complainant / respondent / third party)

Outputs:
  Data/wto_network_analysis_1995-2025.json  — per-year detailed metrics
  Data/wto_network_stats_1995-2025.csv      — flat CSV summary
  Output/sna/disputes_per_year.png
  Output/sna/network_metrics.png
  Output/sna/relationship_types.png

Usage:
  python scripts/run_network_analysis.py
  python scripts/run_network_analysis.py --years 2000 2010 2020
  python scripts/run_network_analysis.py --no-plots
"""

import os
import sys
import json
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):  return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray):     return obj.tolist()
        return super().default(obj)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "Data")
OUT  = os.path.join(BASE, "Output", "sna")


# ── data loading ────────────────────────────────────────────────────────────

def parse_semicolon(s):
    """Parse semicolon-separated country string to list."""
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [x.strip() for x in str(s).split(";") if x.strip()]


def load_cases(path=None):
    path = path or os.path.join(DATA, "wto_cases_v2.csv")
    df = pd.read_csv(path)
    df["year"] = pd.to_datetime(
        df["consultations_requested"], format="mixed", errors="coerce"
    ).dt.year
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    df["comp_list"] = df["complainant"].apply(parse_semicolon)
    df["resp_list"] = df["respondent"].apply(parse_semicolon)
    df["tp_list"]   = df["third_parties"].apply(parse_semicolon)
    return df


# ── network construction ─────────────────────────────────────────────────────

def build_graph(year_df):
    """
    Build a directed MultiGraph for one year.
    Edge relations:
      CR  — Complainant → Respondent   (conflict)
      CTP — Complainant → ThirdParty   (alliance / support)
      RTP — Respondent  → ThirdParty   (conflict)
    """
    G = nx.MultiDiGraph()
    for _, row in year_df.iterrows():
        comp = row["comp_list"]
        resp = row["resp_list"]
        tps  = row["tp_list"]
        case = row["case"]
        for c in comp:
            for r in resp:
                G.add_edge(c, r, relation="CR",  case=case)
        for c in comp:
            for tp in tps:
                G.add_edge(c, tp, relation="CTP", case=case)
        for r in resp:
            for tp in tps:
                G.add_edge(r, tp, relation="RTP", case=case)
    return G


# ── metrics ──────────────────────────────────────────────────────────────────

def edge_type_counts(G):
    counts = defaultdict(int)
    for _, _, d in G.edges(data=True):
        counts[d["relation"]] += 1
    return dict(counts)


def community_metrics(G):
    """Louvain on interaction-weighted undirected graph."""
    uG = nx.Graph()
    for u, v, d in G.edges(data=True):
        if uG.has_edge(u, v):
            uG[u][v]["weight"] += 1
        else:
            uG.add_edge(u, v, weight=1)
    if uG.number_of_nodes() == 0:
        return [], 0.0
    try:
        comms = list(nx.community.louvain_communities(uG, weight="weight", seed=42))
        mod   = nx.community.modularity(uG, comms, weight="weight")
    except Exception:
        comms = [set(uG.nodes())]
        mod   = 0.0
    return [sorted(list(c)) for c in comms], round(float(mod), 4)


def top_n(d, n=10):
    return sorted(d, key=lambda x: d[x], reverse=True)[:n]


def role_counts(year_df):
    comp_c = defaultdict(int)
    resp_c = defaultdict(int)
    tp_c   = defaultdict(int)
    for _, row in year_df.iterrows():
        for c in row["comp_list"]: comp_c[c] += 1
        for r in row["resp_list"]: resp_c[r] += 1
        for t in row["tp_list"]:   tp_c[t]   += 1
    return comp_c, resp_c, tp_c


def analyze_year(year, year_df):
    G      = build_graph(year_df)
    etypes = edge_type_counts(G)
    n_cr   = etypes.get("CR",  0)
    n_ctp  = etypes.get("CTP", 0)
    n_rtp  = etypes.get("RTP", 0)
    total  = n_cr + n_ctp + n_rtp

    comms, mod = community_metrics(G)
    comp_c, resp_c, tp_c = role_counts(year_df)

    uG  = G.to_undirected()
    deg = dict(uG.degree())
    avg_deg = sum(deg.values()) / max(len(deg), 1)

    try:
        btw = nx.betweenness_centrality(uG)
    except Exception:
        btw = {n: 0.0 for n in uG.nodes()}

    return {
        "year":             year,
        "n_disputes":       int(len(year_df)),
        "n_nodes":          int(G.number_of_nodes()),
        "n_edges":          int(G.number_of_edges()),
        "density":          round(float(nx.density(uG)), 4),
        "avg_degree":       round(float(avg_deg), 3),
        "n_cr":             int(n_cr),
        "n_ctp":            int(n_ctp),
        "n_rtp":            int(n_rtp),
        "conflict_density": round((n_cr + n_rtp) / total, 4) if total else 0.0,
        "support_ratio":    round(n_ctp / total, 4) if total else 0.0,
        "n_communities":    int(len(comms)),
        "modularity":       mod,
        "communities":      comms,
        "top_degree_10":    top_n(deg, 10),
        "top_betweenness_10": top_n(btw, 10),
        "top_complainants_5": top_n(comp_c, 5),
        "top_respondents_5":  top_n(resp_c, 5),
        "top_tp_5":           top_n(tp_c, 5),
    }


# ── plots ─────────────────────────────────────────────────────────────────────

def plot_trends(stats_df, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    # 1. Disputes per year (bar)
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(stats_df["year"], stats_df["n_disputes"], color="#4a90d9", alpha=0.85)
    ax.set_xlabel("Year")
    ax.set_ylabel("Number of disputes")
    ax.set_title("WTO Disputes Filed per Year (1995–2025)")
    ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    p = os.path.join(out_dir, "disputes_per_year.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {p}")

    # 2. Network metrics (2x2)
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("WTO Dispute Network Metrics (1995–2025)", fontsize=14, fontweight="bold")
    specs = [
        (axes[0, 0], "n_nodes",          "Active countries",  "#e74c3c"),
        (axes[0, 1], "density",           "Network density",   "#2ecc71"),
        (axes[1, 0], "conflict_density",  "Conflict density",  "#e67e22"),
        (axes[1, 1], "modularity",        "Louvain modularity","#9b59b6"),
    ]
    for ax, col, label, color in specs:
        ax.plot(stats_df["year"], stats_df[col], marker="o", ms=4, lw=1.5, color=color)
        ax.set_title(label)
        ax.set_xlabel("Year")
        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.grid(alpha=0.3)
    plt.tight_layout()
    p = os.path.join(out_dir, "network_metrics.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {p}")

    # 3. Relationship type stacked area
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.stackplot(
        stats_df["year"],
        stats_df["n_cr"], stats_df["n_ctp"], stats_df["n_rtp"],
        labels=["Complainant-Respondent", "Complainant-ThirdParty", "Respondent-ThirdParty"],
        colors=["#e74c3c", "#3498db", "#f39c12"], alpha=0.8,
    )
    ax.set_xlabel("Year")
    ax.set_ylabel("Edge count")
    ax.set_title("Dispute Relationship Types by Year")
    ax.legend(loc="upper right")
    ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    p = os.path.join(out_dir, "relationship_types.png")
    plt.savefig(p, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {p}")


# ── cumulative metrics ────────────────────────────────────────────────────────

def cumulative_role_summary(df):
    """
    Aggregate across all years: total disputes per country by role.
    Returns a DataFrame sorted by total activity.
    """
    comp_c = defaultdict(int)
    resp_c = defaultdict(int)
    tp_c   = defaultdict(int)
    for _, row in df.iterrows():
        for c in row["comp_list"]: comp_c[c] += 1
        for r in row["resp_list"]: resp_c[r] += 1
        for t in row["tp_list"]:   tp_c[t]   += 1
    countries = set(comp_c) | set(resp_c) | set(tp_c)
    rows = []
    for ctry in countries:
        rows.append({
            "country":    ctry,
            "complainant": comp_c.get(ctry, 0),
            "respondent":  resp_c.get(ctry, 0),
            "third_party": tp_c.get(ctry, 0),
        })
    summary = pd.DataFrame(rows)
    summary["total"] = summary["complainant"] + summary["respondent"] + summary["third_party"]
    return summary.sort_values("total", ascending=False).reset_index(drop=True)


# ── main ─────────────────────────────────────────────────────────────────────

def run(years=None, save=True, plots=True, cases_path=None):
    df = load_cases(cases_path)
    available = sorted(df["year"].unique())
    if years:
        available = [y for y in available if y in set(years)]

    yr_min, yr_max = available[0], available[-1]
    print(f"[SNA] Analyzing {len(available)} years: {yr_min}–{yr_max}")

    results  = {}
    stat_rows = []
    for yr in available:
        yr_df   = df[df["year"] == yr]
        metrics = analyze_year(yr, yr_df)
        results[yr] = metrics
        stat_rows.append({k: v for k, v in metrics.items() if not isinstance(v, list)})
        print(f"  {yr}: {metrics['n_disputes']:3d} disputes | "
              f"{metrics['n_nodes']:3d} nodes | "
              f"mod={metrics['modularity']:.3f} | "
              f"{metrics['n_communities']} communities")

    stats_df = pd.DataFrame(stat_rows).sort_values("year").reset_index(drop=True)

    if save:
        os.makedirs(OUT, exist_ok=True)
        json_path = os.path.join(DATA, f"wto_network_analysis_{yr_min}-{yr_max}.json")
        # Convert int64 keys to plain int for JSON serialization
        # Convert numpy int64 keys to plain int
        results_clean = {int(k): v for k, v in results.items()}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results_clean, f, indent=2, ensure_ascii=False, cls=_NumpyEncoder)
        print(f"  JSON: {json_path}")

        csv_path = os.path.join(DATA, f"wto_network_stats_{yr_min}-{yr_max}.csv")
        stats_df.to_csv(csv_path, index=False)
        print(f"  CSV:  {csv_path}")

        role_path = os.path.join(DATA, "wto_country_roles_cumulative.csv")
        cumulative_role_summary(df).to_csv(role_path, index=False)
        print(f"  Roles: {role_path}")

    if plots:
        plot_trends(stats_df, OUT)

    return results, stats_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, help="Specific years to analyze")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--no-save",  action="store_true")
    args = parser.parse_args()
    run(years=args.years, save=not args.no_save, plots=not args.no_plots)
