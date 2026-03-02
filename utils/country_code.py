"""
Unified country code harmonization for WTO-ERGM analysis.

Maps country names across three data sources to ISO 3166-1 alpha-3 codes:
- wto_cases.csv: informal country names (U.S., EU, etc.)
- WTO_mem_list.xlsx: official WTO member names
- IdealPoint.dta: UN voting data (already has iso3c)

Special cases:
- EU assigned 'EUN' (not a standard ISO code; EU is a WTO member but not a UN GA voter)
- Hong Kong (HKG) and Macao (MAC) are WTO members but not in UN voting data
- Chinese Taipei / Taiwan (TWN) is a WTO member; in UN voting data historically (pre-1971)
- North Korea typo fixed directly in wto_cases.csv → South Korea
"""

import ast
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

# ── WTO official member name (from WTO_mem_list.xlsx) → ISO3C ─────────────

WTO_MEMBER_TO_ISO3C: Dict[str, str] = {
    'Afghanistan': 'AFG',
    'Albania': 'ALB',
    'Angola': 'AGO',
    'Antigua and Barbuda': 'ATG',
    'Argentina': 'ARG',
    'Armenia': 'ARM',
    'Australia': 'AUS',
    'Austria': 'AUT',
    'Bahrain, Kingdom of': 'BHR',
    'Bangladesh': 'BGD',
    'Barbados': 'BRB',
    'Belgium': 'BEL',
    'Belize': 'BLZ',
    'Benin': 'BEN',
    'Bolivia, Plurinational State of': 'BOL',
    'Botswana': 'BWA',
    'Brazil': 'BRA',
    'Brunei Darussalam': 'BRN',
    'Bulgaria': 'BGR',
    'Burkina Faso': 'BFA',
    'Burundi': 'BDI',
    'Cabo Verde': 'CPV',
    'Cambodia': 'KHM',
    'Cameroon': 'CMR',
    'Canada': 'CAN',
    'Central African Republic': 'CAF',
    'Chad': 'TCD',
    'Chile': 'CHL',
    'China': 'CHN',
    'Colombia': 'COL',
    'Comoros': 'COM',
    'Congo': 'COG',
    'Costa Rica': 'CRI',
    "C\u00f4te d\u2019Ivoire": 'CIV',  # Côte d'Ivoire (right single quote)
    "C\u00f4te d'Ivoire": 'CIV',       # Côte d'Ivoire (ASCII apostrophe)
    'Croatia': 'HRV',
    'Cuba': 'CUB',
    'Cyprus': 'CYP',
    'Czech Republic': 'CZE',
    'Democratic Republic of the Congo': 'COD',
    'Denmark': 'DNK',
    'Djibouti': 'DJI',
    'Dominica': 'DMA',
    'Dominican Republic': 'DOM',
    'Ecuador': 'ECU',
    'Egypt': 'EGY',
    'El Salvador': 'SLV',
    'Estonia': 'EST',
    'Eswatini': 'SWZ',
    'European Union': 'EUN',
    'Fiji': 'FJI',
    'Finland': 'FIN',
    'France': 'FRA',
    'Gabon': 'GAB',
    'Gambia': 'GMB',
    'Georgia': 'GEO',
    'Germany': 'DEU',
    'Ghana': 'GHA',
    'Greece': 'GRC',
    'Grenada': 'GRD',
    'Guatemala': 'GTM',
    'Guinea': 'GIN',
    'Guinea-Bissau': 'GNB',
    'Guyana': 'GUY',
    'Haiti': 'HTI',
    'Honduras': 'HND',
    'Hong Kong, China': 'HKG',
    'Hungary': 'HUN',
    'Iceland': 'ISL',
    'India': 'IND',
    'Indonesia': 'IDN',
    'Ireland': 'IRL',
    'Israel': 'ISR',
    'Italy': 'ITA',
    'Jamaica': 'JAM',
    'Japan': 'JPN',
    'Jordan': 'JOR',
    'Kazakhstan': 'KAZ',
    'Kenya': 'KEN',
    'Korea, Republic of': 'KOR',
    'Kuwait, the State of': 'KWT',
    'Kyrgyz Republic': 'KGZ',
    "Lao People\u2019s Democratic Republic": 'LAO',  # curly apostrophe from Excel
    "Lao People's Democratic Republic": 'LAO',       # ASCII apostrophe fallback
    'Latvia': 'LVA',
    'Lesotho': 'LSO',
    'Liberia': 'LBR',
    'Liechtenstein': 'LIE',
    'Lithuania': 'LTU',
    'Luxembourg': 'LUX',
    'Macao, China': 'MAC',
    'Madagascar': 'MDG',
    'Malawi': 'MWI',
    'Malaysia': 'MYS',
    'Maldives': 'MDV',
    'Mali': 'MLI',
    'Malta': 'MLT',
    'Mauritania': 'MRT',
    'Mauritius': 'MUS',
    'Mexico': 'MEX',
    'Moldova, Republic of': 'MDA',
    'Mongolia': 'MNG',
    'Montenegro': 'MNE',
    'Morocco': 'MAR',
    'Mozambique': 'MOZ',
    'Myanmar': 'MMR',
    'Namibia': 'NAM',
    'Nepal': 'NPL',
    'Netherlands': 'NLD',
    'New Zealand': 'NZL',
    'Nicaragua': 'NIC',
    'Niger': 'NER',
    'Nigeria': 'NGA',
    'North Macedonia': 'MKD',
    'Norway': 'NOR',
    'Oman': 'OMN',
    'Pakistan': 'PAK',
    'Panama': 'PAN',
    'Papua New Guinea': 'PNG',
    'Paraguay': 'PRY',
    'Peru': 'PER',
    'Philippines': 'PHL',
    'Poland': 'POL',
    'Portugal': 'PRT',
    'Qatar': 'QAT',
    'Romania': 'ROU',
    'Russian Federation': 'RUS',
    'Rwanda': 'RWA',
    'Saint Kitts and Nevis': 'KNA',
    'Saint Lucia': 'LCA',
    'Saint Vincent and the Grenadines': 'VCT',
    'Samoa': 'WSM',
    'Saudi Arabia, Kingdom of': 'SAU',
    'Senegal': 'SEN',
    'Seychelles': 'SYC',
    'Sierra Leone': 'SLE',
    'Singapore': 'SGP',
    'Slovak Republic': 'SVK',
    'Slovenia': 'SVN',
    'Solomon Islands': 'SLB',
    'South Africa': 'ZAF',
    'Spain': 'ESP',
    'Sri Lanka': 'LKA',
    'Suriname': 'SUR',
    'Sweden': 'SWE',
    'Switzerland': 'CHE',
    'Chinese Taipei': 'TWN',
    'Tajikistan': 'TJK',
    'Tanzania': 'TZA',
    'Thailand': 'THA',
    'Timor-Leste': 'TLS',
    'Togo': 'TGO',
    'Tonga': 'TON',
    'Trinidad and Tobago': 'TTO',
    'Tunisia': 'TUN',
    'T\u00fcrkiye': 'TUR',  # Türkiye
    'Uganda': 'UGA',
    'Ukraine': 'UKR',
    'United Arab Emirates': 'ARE',
    'United Kingdom': 'GBR',
    'United States': 'USA',
    'Uruguay': 'URY',
    'Vanuatu': 'VUT',
    'Venezuela, Bolivarian Republic of': 'VEN',
    'Viet Nam': 'VNM',
    'Yemen': 'YEM',
    'Zambia': 'ZMB',
    'Zimbabwe': 'ZWE',
}

# ── wto_cases.csv informal country name → ISO3C ──────────────────────────

WTO_CASE_NAME_TO_ISO3C: Dict[str, str] = {
    # --- Names needing remapping (differ from WTO member list) ---
    'South Korea': 'KOR',
    'U.S.': 'USA',
    'EU': 'EUN',
    'UAE': 'ARE',
    'Hong Kong': 'HKG',
    'Taiwan': 'TWN',
    'Dominican': 'DOM',        # Truncated "Dominican Republic"
    'Russia': 'RUS',
    'Moldova': 'MDA',
    'Venezuela': 'VEN',
    'Vietnam': 'VNM',
    'Kyrgyzstan': 'KGZ',
    'Turkey': 'TUR',
    'Bahrain': 'BHR',
    'Saudi Arabia': 'SAU',
    # --- Names that match WTO member list directly ---
    'Afghanistan': 'AFG',
    'Antigua and Barbuda': 'ATG',
    'Argentina': 'ARG',
    'Armenia': 'ARM',
    'Australia': 'AUS',
    'Bangladesh': 'BGD',
    'Barbados': 'BRB',
    'Belgium': 'BEL',
    'Belize': 'BLZ',
    'Benin': 'BEN',
    'Bolivia, Plurinational State of': 'BOL',
    'Botswana': 'BWA',
    'Brazil': 'BRA',
    'Cameroon': 'CMR',
    'Canada': 'CAN',
    'Chad': 'TCD',
    'Chile': 'CHL',
    'China': 'CHN',
    'Colombia': 'COL',
    'Costa Rica': 'CRI',
    "C\u00f4te d\u2019Ivoire": 'CIV',
    "C\u00f4te d'Ivoire": 'CIV',
    'Croatia': 'HRV',
    'Cuba': 'CUB',
    'Czech Republic': 'CZE',
    'Denmark': 'DNK',
    'Dominica': 'DMA',
    'Ecuador': 'ECU',
    'Egypt': 'EGY',
    'El Salvador': 'SLV',
    'Eswatini': 'SWZ',
    'Fiji': 'FJI',
    'France': 'FRA',
    'Germany': 'DEU',
    'Ghana': 'GHA',
    'Greece': 'GRC',
    'Grenada': 'GRD',
    'Guatemala': 'GTM',
    'Guyana': 'GUY',
    'Honduras': 'HND',
    'Hungary': 'HUN',
    'Iceland': 'ISL',
    'India': 'IND',
    'Indonesia': 'IDN',
    'Ireland': 'IRL',
    'Israel': 'ISR',
    'Italy': 'ITA',
    'Jamaica': 'JAM',
    'Japan': 'JPN',
    'Kazakhstan': 'KAZ',
    'Kenya': 'KEN',
    'Kuwait, the State of': 'KWT',
    'Lithuania': 'LTU',
    'Madagascar': 'MDG',
    'Malawi': 'MWI',
    'Malaysia': 'MYS',
    'Mauritius': 'MUS',
    'Mexico': 'MEX',
    'Morocco': 'MAR',
    'Namibia': 'NAM',
    'Netherlands': 'NLD',
    'New Zealand': 'NZL',
    'Nicaragua': 'NIC',
    'Nigeria': 'NGA',
    'Norway': 'NOR',
    'Oman': 'OMN',
    'Pakistan': 'PAK',
    'Panama': 'PAN',
    'Paraguay': 'PRY',
    'Peru': 'PER',
    'Philippines': 'PHL',
    'Poland': 'POL',
    'Portugal': 'PRT',
    'Qatar': 'QAT',
    'Romania': 'ROU',
    'Saint Kitts and Nevis': 'KNA',
    'Saint Lucia': 'LCA',
    'Saint Vincent and the Grenadines': 'VCT',
    'Saudi Arabia': 'SAU',
    'Senegal': 'SEN',
    'Singapore': 'SGP',
    'Slovak Republic': 'SVK',
    'South Africa': 'ZAF',
    'Spain': 'ESP',
    'Sri Lanka': 'LKA',
    'Suriname': 'SUR',
    'Sweden': 'SWE',
    'Switzerland': 'CHE',
    'Tajikistan': 'TJK',
    'Tanzania': 'TZA',
    'Thailand': 'THA',
    'Trinidad and Tobago': 'TTO',
    'Tunisia': 'TUN',
    'T\u00fcrkiye': 'TUR',  # Türkiye
    'Ukraine': 'UKR',
    'United Kingdom': 'GBR',
    'Uruguay': 'URY',
    'Yemen': 'YEM',
    'Zambia': 'ZMB',
    'Zimbabwe': 'ZWE',
}

# ── EU member states (EU-27, post-Brexit 2020) ───────────────────────────
# All 27 are also individual WTO members

EU_MEMBER_ISO3C: Set[str] = {
    'AUT', 'BEL', 'BGR', 'HRV', 'CYP', 'CZE', 'DNK', 'EST', 'FIN',
    'FRA', 'DEU', 'GRC', 'HUN', 'IRL', 'ITA', 'LVA', 'LTU', 'LUX',
    'MLT', 'NLD', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'ESP', 'SWE',
}

# ── EU accession year by iso3c ────────────────────────────────────────────
# Tracks when each country joined the EU (not the WTO).
# EU-6 (1958) → EU-9 (1973) → EU-10 (1981) → EU-12 (1986)
# → EU-15 (1995) → EU-25 (2004) → EU-27 (2007) → EU-28 (2013)
# → EU-27 (2020, Brexit)

EU_ACCESSION_YEAR: Dict[str, int] = {
    # EU-6 founding members (Treaty of Rome, 1958)
    'BEL': 1958, 'DEU': 1958, 'FRA': 1958, 'ITA': 1958, 'LUX': 1958, 'NLD': 1958,
    # EU-9 (1973)
    'DNK': 1973, 'IRL': 1973, 'GBR': 1973,
    # EU-10 (1981)
    'GRC': 1981,
    # EU-12 (1986)
    'ESP': 1986, 'PRT': 1986,
    # EU-15 (1995)
    'AUT': 1995, 'FIN': 1995, 'SWE': 1995,
    # EU-25 (2004)
    'CYP': 2004, 'CZE': 2004, 'EST': 2004, 'HUN': 2004, 'LVA': 2004,
    'LTU': 2004, 'MLT': 2004, 'POL': 2004, 'SVK': 2004, 'SVN': 2004,
    # EU-27 (2007)
    'BGR': 2007, 'ROU': 2007,
    # EU-28 (2013)
    'HRV': 2013,
}

# UK left the EU on 31 January 2020
EU_EXIT_YEAR: Dict[str, int] = {
    'GBR': 2020,
}

# ── Eurozone membership (year of euro adoption) ──────────────────────────
# Not all EU members use the euro. Denmark has an opt-out; Sweden, Poland,
# Czech Republic, Hungary, Romania, Bulgaria have not yet adopted.

EUROZONE_YEAR: Dict[str, int] = {
    # Wave 1 (1999) — euro introduced as accounting currency
    'AUT': 1999, 'BEL': 1999, 'FIN': 1999, 'FRA': 1999, 'DEU': 1999,
    'IRL': 1999, 'ITA': 1999, 'LUX': 1999, 'NLD': 1999, 'PRT': 1999, 'ESP': 1999,
    # 2001
    'GRC': 2001,
    # 2007
    'SVN': 2007,
    # 2008
    'CYP': 2008, 'MLT': 2008,
    # 2009
    'SVK': 2009,
    # 2011
    'EST': 2011,
    # 2014
    'LVA': 2014,
    # 2015
    'LTU': 2015,
    # 2023
    'HRV': 2023,
}
# Non-eurozone EU members (as of 2024): BGR, CZE, DNK, HUN, POL, ROU, SWE

# ISO3C → short display name (for readable output)
ISO3C_TO_SHORT_NAME: Dict[str, str] = {
    v: k for k, v in WTO_MEMBER_TO_ISO3C.items()
}
# Override with shorter names for readability
ISO3C_TO_SHORT_NAME.update({
    'BHR': 'Bahrain',
    'BOL': 'Bolivia',
    'COD': 'DR Congo',
    'CIV': "Cote d'Ivoire",
    'DOM': 'Dominican Republic',
    'EUN': 'European Union',
    'HKG': 'Hong Kong',
    'KOR': 'South Korea',
    'KWT': 'Kuwait',
    'KGZ': 'Kyrgyzstan',
    'LAO': 'Laos',
    'MAC': 'Macao',
    'MDA': 'Moldova',
    'MKD': 'North Macedonia',
    'RUS': 'Russia',
    'SAU': 'Saudi Arabia',
    'TWN': 'Taiwan',
    'TUR': 'Turkey',
    'ARE': 'UAE',
    'USA': 'United States',
    'GBR': 'United Kingdom',
    'VEN': 'Venezuela',
    'VNM': 'Vietnam',
})


# ── Functions ─────────────────────────────────────────────────────────────

def _parse_country_list(val: str) -> List[str]:
    """Parse a stringified Python list from wto_cases.csv."""
    if pd.isna(val):
        return []
    try:
        names = ast.literal_eval(val)
        return [n.strip() for n in names if n.strip()]
    except (ValueError, SyntaxError):
        return []


def build_wto_node_set(wto_mem_path: str) -> pd.DataFrame:
    """
    Build the 166-member WTO node set from WTO_mem_list.xlsx.

    Returns DataFrame with columns:
    - iso3c: unified country code (index)
    - wto_name: official WTO member name
    - accession_date: datetime of WTO accession
    - accession_year: int year of accession
    - is_eu_member: whether this is a current EU-27 member state
    - eu_accession_year: year country joined the EU (NaN if not EU)
    - eu_exit_year: year country left the EU (NaN if still member or never EU)
    - is_eurozone: whether this country uses the euro
    - eurozone_year: year of euro adoption (NaN if not eurozone)
    """
    wto_mem = pd.read_excel(wto_mem_path, sheet_name='mem-obs-list')

    rows = []
    unmapped = []
    for _, row in wto_mem.iterrows():
        name = row['Members']
        iso3c = WTO_MEMBER_TO_ISO3C.get(name)
        if iso3c is None:
            unmapped.append(name)
            continue

        date_str = row['Membership Date']
        try:
            acc_date = pd.to_datetime(date_str, format='%d %B %Y')
        except (ValueError, TypeError):
            acc_date = pd.NaT

        rows.append({
            'iso3c': iso3c,
            'wto_name': name,
            'accession_date': acc_date,
            'accession_year': acc_date.year if pd.notna(acc_date) else None,
            'is_eu_member': iso3c in EU_MEMBER_ISO3C,
            'eu_accession_year': EU_ACCESSION_YEAR.get(iso3c),
            'eu_exit_year': EU_EXIT_YEAR.get(iso3c),
            'is_eurozone': iso3c in EUROZONE_YEAR,
            'eurozone_year': EUROZONE_YEAR.get(iso3c),
        })

    if unmapped:
        print(f"WARNING: {len(unmapped)} WTO members could not be mapped:")
        for n in unmapped:
            print(f"  '{n}'")

    df = pd.DataFrame(rows).set_index('iso3c').sort_index()
    print(f"WTO node set: {len(df)} members")
    return df


def is_eu_member_at(iso3c: str, year: int) -> bool:
    """Check if a country was an EU member in a given year."""
    join_year = EU_ACCESSION_YEAR.get(iso3c)
    if join_year is None or year < join_year:
        return False
    exit_year = EU_EXIT_YEAR.get(iso3c)
    if exit_year is not None and year >= exit_year:
        return False
    return True


def get_eu_solo_cases(cases_df: pd.DataFrame) -> pd.DataFrame:
    """
    Find WTO cases where EU member states acted as sole actors
    (complainant or respondent) without the EU entity.

    Args:
        cases_df: raw wto_cases.csv DataFrame

    Returns:
        DataFrame with case, year, role, country, iso3c, was_eu_member
    """
    eu_state_names = {
        'Austria', 'Belgium', 'Bulgaria', 'Croatia', 'Cyprus', 'Czech Republic',
        'Denmark', 'Estonia', 'Finland', 'France', 'Germany', 'Greece', 'Hungary',
        'Ireland', 'Italy', 'Latvia', 'Lithuania', 'Luxembourg', 'Malta',
        'Netherlands', 'Poland', 'Portugal', 'Romania', 'Slovak Republic',
        'Slovenia', 'Spain', 'Sweden', 'United Kingdom',
    }

    rows = []
    for _, row in cases_df.iterrows():
        comp_list = _parse_country_list(row.get('Complainant', ''))
        resp_list = _parse_country_list(row.get('Respondent', ''))
        has_eu = 'EU' in comp_list or 'EU' in resp_list

        year_str = str(row.get('consultations_requested', ''))[:4]
        year = int(year_str) if year_str.isdigit() else None

        for name in comp_list:
            if name in eu_state_names:
                iso3c = WTO_CASE_NAME_TO_ISO3C.get(name)
                rows.append({
                    'case': row['case'],
                    'year': year,
                    'role': 'complainant',
                    'country': name,
                    'iso3c': iso3c,
                    'joint_with_eu': has_eu,
                    'was_eu_member': is_eu_member_at(iso3c, year) if (iso3c and year) else None,
                })

        for name in resp_list:
            if name in eu_state_names:
                iso3c = WTO_CASE_NAME_TO_ISO3C.get(name)
                rows.append({
                    'case': row['case'],
                    'year': year,
                    'role': 'respondent',
                    'country': name,
                    'iso3c': iso3c,
                    'joint_with_eu': has_eu,
                    'was_eu_member': is_eu_member_at(iso3c, year) if (iso3c and year) else None,
                })

    return pd.DataFrame(rows)


def harmonize_case_countries(cases_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert wto_cases.csv country names to iso3c codes.

    Adds columns: complainant_iso3c, respondent_iso3c, third_party_iso3c
    (each is a list of iso3c codes).

    Returns a copy of the dataframe with new columns added.
    """
    df = cases_df.copy()
    unmapped = set()

    def _map_names(val: str) -> List[str]:
        names = _parse_country_list(val)
        codes = []
        for name in names:
            code = WTO_CASE_NAME_TO_ISO3C.get(name)
            if code is None:
                unmapped.add(name)
            else:
                codes.append(code)
        return codes

    df['complainant_iso3c'] = df['Complainant'].apply(_map_names)
    df['respondent_iso3c'] = df['Respondent'].apply(_map_names)
    df['third_party_iso3c'] = df['third_parties'].apply(_map_names)

    if unmapped:
        print(f"WARNING: {len(unmapped)} country names could not be mapped:")
        for n in sorted(unmapped):
            print(f"  '{n}'")

    return df


def check_un_voting_coverage(
    node_set: pd.DataFrame,
    ideal_point_path: str,
    year_range: Optional[Tuple[int, int]] = None,
) -> Tuple[Set[str], Set[str]]:
    """
    Cross-reference WTO members against UN voting (IdealPoint) data.

    Args:
        node_set: DataFrame from build_wto_node_set() (iso3c as index)
        ideal_point_path: path to IdealPoint.dta
        year_range: optional (start, end) to check coverage within a period

    Returns:
        (covered, not_covered) - sets of iso3c codes
    """
    un = pd.read_stata(ideal_point_path)

    if year_range:
        un = un[(un['year'] >= year_range[0]) & (un['year'] <= year_range[1])]

    un_iso3c = set(un['iso3c'].dropna().unique())
    wto_iso3c = set(node_set.index)

    covered = wto_iso3c & un_iso3c
    not_covered = wto_iso3c - un_iso3c

    return covered, not_covered


def get_dispute_participation(cases_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each country (iso3c), count participation as complainant,
    respondent, or third party across all WTO disputes.

    Args:
        cases_df: DataFrame from harmonize_case_countries()
            (must have complainant_iso3c, respondent_iso3c, third_party_iso3c)

    Returns:
        DataFrame with columns:
        - iso3c (index)
        - as_complainant: count of cases
        - as_respondent: count of cases
        - as_third_party: count of cases
        - total_participations: sum of all roles
    """
    comp_counts: Dict[str, int] = {}
    resp_counts: Dict[str, int] = {}
    tp_counts: Dict[str, int] = {}

    for _, row in cases_df.iterrows():
        for c in row.get('complainant_iso3c', []):
            comp_counts[c] = comp_counts.get(c, 0) + 1
        for c in row.get('respondent_iso3c', []):
            resp_counts[c] = resp_counts.get(c, 0) + 1
        for c in row.get('third_party_iso3c', []):
            tp_counts[c] = tp_counts.get(c, 0) + 1

    all_codes = set(comp_counts) | set(resp_counts) | set(tp_counts)
    rows = []
    for code in sorted(all_codes):
        rows.append({
            'iso3c': code,
            'as_complainant': comp_counts.get(code, 0),
            'as_respondent': resp_counts.get(code, 0),
            'as_third_party': tp_counts.get(code, 0),
        })

    df = pd.DataFrame(rows).set_index('iso3c')
    df['total_participations'] = (
        df['as_complainant'] + df['as_respondent'] + df['as_third_party']
    )
    return df.sort_values('total_participations', ascending=False)


def build_ergm_node_table(
    wto_mem_path: str,
    cases_path: str,
    ideal_point_path: str,
) -> pd.DataFrame:
    """
    Build the complete ERGM node attribute table.

    Combines WTO membership, dispute participation, and UN voting coverage
    into a single table with 166 rows (one per WTO member).

    Returns DataFrame indexed by iso3c with columns:
    - wto_name, accession_date, accession_year
    - is_eu_member, eu_accession_year, eu_exit_year
    - is_eurozone, eurozone_year
    - as_complainant, as_respondent, as_third_party, total_participations
    - has_un_voting: whether this member has UN voting data in IdealPoint
    """
    # 1. Build node set
    node_set = build_wto_node_set(wto_mem_path)

    # 2. Harmonize cases and get participation
    cases = pd.read_csv(cases_path)
    cases = harmonize_case_countries(cases)
    participation = get_dispute_participation(cases)

    # 3. Check UN voting coverage
    covered, not_covered = check_un_voting_coverage(node_set, ideal_point_path)

    # 4. Merge
    result = node_set.join(participation, how='left')
    result[['as_complainant', 'as_respondent', 'as_third_party',
            'total_participations']] = result[[
        'as_complainant', 'as_respondent', 'as_third_party',
        'total_participations'
    ]].fillna(0).astype(int)

    result['has_un_voting'] = result.index.isin(covered)

    return result
