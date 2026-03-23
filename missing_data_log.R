###############################################################################
# Missing Data Decision Log
# WTO Dispute Analysis — TERGM / SERGM
# Reference document for methods section of paper
###############################################################################

# Variable              | Missing % | Treatment              | Justification
# ----------------------|-----------|------------------------|---------------------------
# total_trade_ij        | ~0%       | NA → 0                 | No trade = 0 by definition
# export_dependence     | ~2.4%     | NA → 0                 | No trade → zero dependence
# disputed_trade_*      | ~99%      | NA → 0                 | No dispute = no disputed trade
# atopally (+ subtypes) | ~0%       | NA → 0; 2019-24 fwd-  | No alliance = 0; ATOP ends 2018,
#                       |           | filled from 2018       | forward-fill documented
# pta_exists (derived)  | ~0%       | NA → 0 (from label)   | DESTA non-coverage treated as
#                       |           |                        | "no PTA"; document in paper
# depth_index           | ~62%      | NA → 0                 | No PTA → depth = 0; conflates
#                       |           |                        | with shallow PTA; use pta_exists
#                       |           |                        | as primary, depth as robustness
# severity_*            | ~99%      | NA → 0                 | No dispute = no severity
# has_dispute           | 0%        | —                      | Outcome variable; complete
# ----------------------|-----------|------------------------|---------------------------
# idealpointfp          | ~3%       | NA retained            | Taiwan, HK, Macao, EU missing;
#                       |           |                        | ergm skips affected dyads in
#                       |           |                        | edgecov terms; report in paper
# v2x_polyarchy         | ~5%       | NA retained            | Micro-states, EU; not in main
#                       |           |                        | model; robustness only
# election_binary       | ~5%       | NA → 0                 | No record = no election observed
# gdp, gdppc, pop       | ~1-2%    | Carry-forward (LOCF)   | Small gaps in WDI; LOCF
#                       |           | + backward fill        | standard practice
# gdp_growth_rate       | ~2%      | Carry-forward           | Same as above
# fdi                   | ~5%      | NOT included            | High missing; not theoretically
#                       |           |                        | central
# cinc (NMC)            | ~27%     | NOT included            | Ends 2016; use GDP instead
# unemployment_rate     | ~43%     | NOT included            | Too sparse for network model
# WGI (6 indicators)    | ~5-9%    | Pre-2002 interpolated; | Standard WGI practice; NK and
#                       |           | remaining NA retained  | micro-states missing
# ----------------------|-----------|------------------------|---------------------------
#
# NOTES:
# 1. Analysis period: 1995-2018 (ATOP native) or 1995-2024 (ATOP forward-filled)
# 2. Node set: All WTO members with bilateral trade in any year
# 3. EU: Treated as unitary actor (EUN); node attributes GDP-weighted from members
# 4. Taiwan: In network but missing UN voting & ATOP; ~3% of dyads affected
# 5. DESTA EUN artifact: Pipeline corrects via fix_eun_desta()
