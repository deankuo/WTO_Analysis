"""Content extraction and text cleaning for WTO DSB documents.

ContentParser: extracts date, header codes, agreement indicators, document type,
  and case title from first-page PDF text.
TextCleaner: removes WTO boilerplate headers/codes for clean RAG embeddings.
"""

import re
from typing import List, Optional, Tuple


AGREEMENT_CODE_MAP = {
    'G/SPS/':   'Sanitary and Phytosanitary Measures (SPS)',
    'G/TBT/':   'Technical Barriers to Trade (TBT)',
    'G/SCM/':   'Subsidies and Countervailing Measures (SCM)',
    'G/ADP/':   'Anti-Dumping Practices (ADP)',
    'G/AG/':    'Agriculture (AG)',
    'G/SG/':    'Safeguards (SG)',
    'G/TRIMS/': 'Trade-Related Investment Measures (TRIMS)',
    'G/RO/':    'Rules of Origin (RO)',
    'G/VAL/':   'Customs Valuation (VAL)',
    'G/LIC/':   'Import Licensing (LIC)',
    'G/IT/':    'Information Technology Agreement (ITA)',
    'G/L/':     'General Council',
    'S/L/':     'General Agreement on Trade in Services (GATS)',
    'IP/D/':    'Trade-Related Aspects of Intellectual Property Rights (TRIPS)',
    'WT/DS':    'Dispute Settlement',
}

# Document type extraction patterns - ORDERED by specificity (most specific first)
DOC_TYPE_PATTERNS = [
    # Appellate Body + Panel combined
    (r'appellate\s+body\s+report\s+and\s+panel\s+report', 'Appellate_Body_Report_And_Panel_Report'),
    # Appellate Body
    (r'report\s+of\s+the\s+appellate\s+body', 'Report_Of_Appellate_Body'),
    (r'appellate\s+body\s+report', 'Report_Of_Appellate_Body'),
    # Panel
    (r'report\s+of\s+the\s+panel', 'Report_Of_Panel'),
    (r'panel\s+report', 'Report_Of_Panel'),
    # Requests
    (r'request\s+for\s+(?:the\s+)?establishment\s+of\s+(?:a\s+)?panel', 'Request_For_Establishment_Of_Panel'),
    (r'acceptance\s+.*\s+to\s+join\s+(?:further\s+)?consultations?', 'Request_To_Join_Consultations'),
    (r'acceptance\s+.*\s+requests?\s+to\s+join\s+consultations?', 'Request_To_Join_Consultations'),
    (r'requests?\s+to\s+join\s+(?:the\s+)?consultations?', 'Request_To_Join_Consultations'),
    (r'request\s+(?:to|for)\s+join(?:ing)?\s+(?:the\s+)?consultations?', 'Request_To_Join_Consultations'),
    (r'request\s+for\s+consultations?\s+(?:by|from)\s+', 'Request_For_Consultations'),
    (r'request\s+for\s+consultations?', 'Request_For_Consultations'),
    (r'request\s+(?:for|to)\s+reactivat(?:e|ion)\s+(?:of\s+)?consultations?', 'Request_To_Reactivate_Consultations'),
    (r'request\s+for\s+arbitration', 'Request_For_Arbitration'),
    (r'request\s+(?:by|from)\s+.+?\s+for\s+arbitration', 'Request_For_Arbitration'),
    (r'request\s+.*\s+regarding\s+consultations?', 'Request_Regarding_Consultations'),
    (r'request\s+(?:by|from)\s+\w+\s+for\s+(?:the\s+)?establishment', 'Request_For_Establishment_Of_Panel'),
    (r'request\s+(?:by|from)\s+.+?\s+for\s+(?:a\s+)?decision', 'Request_For_Decision'),
    (r'joint\s+request\s+.*\s+for\s+(?:a\s+)?decision', 'Request_For_Decision'),
    # Notifications
    (r'notification\s+of\s+(?:an?\s+)?appeal\s+(?:by|from)\s+', 'Notification_Of_Appeal'),
    (r'notification\s+of\s+(?:an?\s+)?appeal', 'Notification_Of_Appeal'),
    (r'notification\s+of\s+(?:a\s+)?mutually[\s-]agreed\s+solution', 'Notification_Of_Mutually_Agreed_Solution'),
    (r'notification\s+of\s+(?:a\s+)?mutually\s+satisfactory', 'Notification_Of_Mutually_Agreed_Solution'),
    (r'mutually\s+accept(?:able|ed)\s+solution', 'Notification_Of_Mutually_Agreed_Solution'),
    (r'notification\s+of\s+an?\s+understanding', 'Notification_Of_Understanding'),
    (r'notification\s+of\s+(?:an?\s+)?agreement', 'Notification_Of_Agreement'),
    # Notes (prioritize over constitution/composition)
    (r'note\s+by\s+the\s+secretariat', 'Note_By_Secretariat'),
    # Communications (consolidated - keep source detail in doc_type_raw)
    (r'communication\s+from\s+the\s+director[\s-]general', 'Communication'),
    (r'report\s+by\s+the\s+director[\s-]general', 'Report_By_Director_General'),
    (r'communication\s+(?:from|by)\s+', 'Communication'),
    # Panel composition/constitution (consolidated)
    (r'constitution\s+of\s+the\s+panel', 'Panel_Composition'),
    (r'composition\s+of\s+the\s+panel', 'Panel_Composition'),
    # Arbitration (consolidated Award + Decision)
    (r'award\s+of\s+the\s+arbitrator', 'Arbitration_Award'),
    (r'decision\s+(?:by|of)\s+(?:the\s+)?arbitrator', 'Arbitration_Award'),
    (r'decision\s+by\s+arbitrators?', 'Arbitration_Award'),
    (r'arbitration\s+(?:award|report|decision)', 'Arbitration'),
    (r'appointment\s+of\s+(?:the\s+)?arbitrator', 'Appointment_Of_Arbitrator'),
    (r'constitution\s+of\s+(?:the\s+)?arbitrator', 'Constitution_Of_Arbitrator'),
    # Recourse (consolidated - keep article detail in doc_type_raw)
    (r'recourse\s+(?:by\s+.+?\s+)?to\s+article\s+(?:21\.5|22\.6|22|25|4)', 'Recourse'),
    (r'objection\s+.*\s+to\s+recourse', 'Objection_To_Recourse'),
    # Status
    (r'status\s+report', 'Status_Report'),
    # Procedures
    (r'working\s+procedures', 'Working_Procedures'),
    (r'(?:additional|supplementary)\s+procedures?', 'Additional_Procedures'),
    (r'agreed\s+procedures', 'Agreed_Procedures'),
    (r'procedural\s+agreement', 'Agreed_Procedures'),
    (r'agreement\s+on\s+procedures', 'Agreed_Procedures'),
    # Suspension/Resumption
    (r'suspension\s+of\s+(?:panel\s+)?proceedings', 'Suspension_Of_Proceedings'),
    (r'suspension\s+of\s+(?:concessions|obligations)', 'Suspension_Of_Concessions'),
    (r'resumption\s+of\s+(?:panel\s+)?proceedings', 'Resumption_Of_Proceedings'),
    # DSB Action
    (r'action\s+by\s+the\s+dispute\s+settlement\s+body', 'DSB_Action'),
    # Surveillance/Implementation
    (r'surveillance\s+of\s+implementation', 'Surveillance_Of_Implementation'),
    (r'implementation\s+of\s+(?:the\s+)?recommendations', 'Implementation_Report'),
    # Agreements/Understandings
    (r'agreement\s+under\s+article\s+21\.3', 'Agreement_Art_21_3'),
    (r'understanding\s+(?:between|on|regarding)', 'Understanding'),
    (r'extension\s+of\s+(?:the\s+)?(?:time\s+)?period', 'Extension_Of_Time_Period'),
    (r'proposed\s+modification', 'Proposed_Modification'),
    # Terms of Reference
    (r'terms\s+of\s+reference', 'Terms_Of_Reference'),
    # Withdrawal/Cancellation
    (r'withdrawal\s+of', 'Withdrawal'),
    (r'erroneously\s+published.*cancelled', 'Cancelled_Document'),
    (r'document.*cancelled', 'Cancelled_Document'),
    # Executive summary
    (r'executive\s+summary', 'Executive_Summary'),
    # Submissions (consolidated - oral, third-party, first, second)
    (r'third[\s-]party\s+(?:submission|communication)', 'Submission'),
    (r'first\s+(?:written\s+)?submissions?\s+(?:by|of)\s+(?:the\s+)?parties', 'Submission'),
    (r'second\s+(?:written\s+)?submissions?\s+(?:by|of)\s+(?:the\s+)?parties', 'Submission'),
    (r'oral\s+statements?', 'Submission'),
    (r'statement\s+(?:by|from)\s+', 'Statement'),
    # Questions and Replies (consolidated)
    (r'questions?\s+and\s+(?:answers?|replies)', 'Questions_And_Replies'),
    (r'replies?\s+(?:from|by)\s+', 'Questions_And_Replies'),
    (r'transcript\s+of\s+(?:the\s+)?proceedings', 'Transcript'),
    (r'interim\s+review', 'Interim_Review'),
    # Modification
    (r'modification\s+of', 'Modification'),
    # Addendum/Corrigendum (standalone doc types)
    (r'addendum', 'Addendum'),
    (r'corrigendum', 'Corrigendum'),
]


class ContentParser:
    """Extracts metadata from the first page of a WTO PDF."""

    # English months
    MONTHS_EN = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    # French months
    MONTHS_FR = r'(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)'
    # Spanish months
    MONTHS_ES = r'(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)'

    # Month name to English mapping
    MONTH_MAP = {
        # French
        'janvier': 'January', 'février': 'February', 'mars': 'March', 'avril': 'April',
        'mai': 'May', 'juin': 'June', 'juillet': 'July', 'août': 'August',
        'septembre': 'September', 'octobre': 'October', 'novembre': 'November', 'décembre': 'December',
        # Spanish
        'enero': 'January', 'febrero': 'February', 'marzo': 'March', 'abril': 'April',
        'mayo': 'May', 'junio': 'June', 'julio': 'July', 'agosto': 'August',
        'septiembre': 'September', 'octubre': 'October', 'noviembre': 'November', 'diciembre': 'December',
    }

    @staticmethod
    def extract_date(text: str) -> Optional[str]:
        """Extract date in English, French, or Spanish format.

        Returns date normalized to English format (DD MonthName YYYY).
        """
        # Try English first
        match = re.search(rf'(\d{{1,2}})\s+({ContentParser.MONTHS_EN})\s+(\d{{4}})', text, re.IGNORECASE)
        if match:
            return f"{match.group(1)} {match.group(2).capitalize()} {match.group(3)}"

        # Try French
        match = re.search(rf'(\d{{1,2}})\s+({ContentParser.MONTHS_FR})\s+(\d{{4}})', text, re.IGNORECASE)
        if match:
            month_fr = match.group(2).lower()
            month_en = ContentParser.MONTH_MAP.get(month_fr, match.group(2))
            return f"{match.group(1)} {month_en} {match.group(3)}"

        # Try Spanish
        match = re.search(rf'(\d{{1,2}})\s+de\s+({ContentParser.MONTHS_ES})\s+de\s+(\d{{4}})', text, re.IGNORECASE)
        if match:
            month_es = match.group(2).lower()
            month_en = ContentParser.MONTH_MAP.get(month_es, match.group(2))
            return f"{match.group(1)} {month_en} {match.group(3)}"

        return None

    @staticmethod
    def extract_header_codes(text: str) -> List[str]:
        codes = []
        header_text = text[:800]

        for m in re.finditer(r'WT/DS\d+/[A-Za-z0-9/.\-]+', header_text):
            codes.append(m.group(0).strip())
        for m in re.finditer(r'G/[A-Z]+/[A-Za-z0-9/.\-]+', header_text):
            codes.append(m.group(0).strip())
        for m in re.finditer(r'S/L/\d+', header_text):
            codes.append(m.group(0).strip())
        for m in re.finditer(r'IP/D/\d+', header_text):
            codes.append(m.group(0).strip())

        return codes

    @staticmethod
    def map_agreement_indicators(codes: List[str]) -> List[str]:
        agreements = set()
        for code in codes:
            for prefix, agreement_name in AGREEMENT_CODE_MAP.items():
                if code.startswith(prefix) and agreement_name != 'Dispute Settlement':
                    agreements.add(agreement_name)
        return sorted(agreements)

    @staticmethod
    def extract_doc_type(text: str) -> Tuple[str, str]:
        """Extract document type from first-page content.

        Strategy:
        1. Find the case title (ALL CAPS text with dash/en-dash)
        2. Extract text between case title and body start
        3. Match that narrow text against known patterns
        This avoids false matches from body text mentioning "panel report" etc.
        """
        lines = text[:2000].split('\n')

        # Phase 1: Find the case title
        case_title_end_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 10:
                continue
            has_dash = bool(re.search(r'[–\-—]', stripped))
            is_upper = stripped.isupper() or (
                len(stripped) > 5 and
                sum(1 for c in stripped if c.isupper()) > len(stripped) * 0.5
            )
            if has_dash and is_upper:
                case_title_end_idx = i
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j].strip()
                    if next_line and (next_line.isupper() or
                        (len(next_line) > 5 and
                         sum(1 for c in next_line if c.isupper()) > len(next_line) * 0.5)):
                        case_title_end_idx = j
                    else:
                        break
                break

        # Phase 2: Collect doc type text (between case title and body start)
        doc_type_lines = []
        search_start = case_title_end_idx + 1 if case_title_end_idx >= 0 else 0

        for i in range(search_start, min(search_start + 15, len(lines))):
            stripped = lines[i].strip()
            if not stripped:
                if doc_type_lines:
                    continue
                continue

            # Body start indicators
            if re.match(r'^The following\s', stripped, re.IGNORECASE):
                break
            if re.match(r'^_{3,}', stripped):
                break
            if re.match(r'^\d+\.?\s+[A-Z]', stripped):
                break
            if re.match(r'^Pursuant\s', stripped, re.IGNORECASE):
                break
            if re.match(r'^I\.\s', stripped):
                break
            if re.match(r'^At its meeting', stripped, re.IGNORECASE):
                break
            if re.match(r'^This (addendum|report|document)', stripped, re.IGNORECASE):
                break
            if re.match(r'^The report of the', stripped, re.IGNORECASE):
                break

            doc_type_lines.append(stripped)

        doc_type_text = ' '.join(doc_type_lines).strip()

        # Phase 3: Match patterns in the narrow doc type text
        if doc_type_text:
            for pattern, doc_type in DOC_TYPE_PATTERNS:
                match = re.search(pattern, doc_type_text, re.IGNORECASE)
                if match:
                    return doc_type, doc_type_text

        # Phase 4: Fallback - full header area (first 1200 chars)
        fallback_text = re.sub(r'\s+', ' ', text[:1200])
        for pattern, doc_type in DOC_TYPE_PATTERNS:
            match = re.search(pattern, fallback_text, re.IGNORECASE)
            if match:
                return doc_type, match.group(0).strip()

        return 'UNKNOWN', doc_type_text or ''

    @staticmethod
    def extract_case_title(text: str) -> str:
        """Extract the main case title (RESPONDENT - MEASURE) from first page."""
        lines = text[:1500].split('\n')
        title_lines = []
        found_start = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if found_start and title_lines:
                    break
                continue

            if re.match(r'^(WORLD\s+TRADE|ORGANIZATION|ORGANISATION|ORGANIZACIÓN)', stripped, re.IGNORECASE):
                continue
            if re.match(r'^WT/', stripped):
                continue
            if re.match(r'^G/', stripped):
                continue
            if re.match(r'^S/L/', stripped):
                continue
            if re.match(r'^IP/', stripped):
                continue
            if re.match(r'^\d{1,2}\s+\w+\s+\d{4}', stripped):
                continue
            if re.match(r'^\(\d{2}-\d{4,5}\)', stripped):
                continue
            if re.match(r'^Original:', stripped, re.IGNORECASE):
                continue
            if re.match(r'^Page:', stripped, re.IGNORECASE):
                continue

            has_dash = bool(re.search(r'[–\-—]', stripped))
            is_upper = stripped.isupper() or (sum(1 for c in stripped if c.isupper()) > len(stripped) * 0.6)

            if has_dash and is_upper and len(stripped) > 10:
                found_start = True
                title_lines.append(stripped)
            elif found_start and is_upper and len(stripped) > 5:
                title_lines.append(stripped)
            elif found_start:
                break

        return ' '.join(title_lines).strip() if title_lines else ''


class TextCleaner:
    """Cleans WTO document text for RAG embeddings."""

    @staticmethod
    def is_toc_page(page_text: str) -> bool:
        """Detect if a page is a table of contents page.

        TOC pages in WTO reports are identified by:
        - Roman numeral page headers (Page i, Page ii, etc.)
        - "TABLE OF CONTENTS" label
        - Dense dot leader lines (section titles followed by ...... and page numbers)
        """
        text = page_text.strip()
        if len(text) < 50:
            return False

        # Roman numeral page numbers in header (Page i, Page ii, Page iii, etc.)
        if re.search(r'Page\s+[ivxlc]+\s*$', text[:300], re.IGNORECASE | re.MULTILINE):
            return True

        # Explicit TABLE OF CONTENTS label
        if re.search(r'TABLE\s+OF\s+CONTENTS', text, re.IGNORECASE):
            return True

        # Dense dot leader lines (>30% of non-empty lines have 10+ consecutive dots)
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if lines:
            dot_lines = sum(1 for l in lines if re.search(r'\.{10,}', l))
            if dot_lines / len(lines) > 0.3:
                return True

        return False

    HEADER_PATTERNS = [
        r'WORLD\s+TRADE\s*\n?\s*ORGANIZATION',
        r'ORGANISATION\s+MONDIALE\s+DU\s+COMMERCE',
        r'ORGANIZACIÓN\s+MUNDIAL\s+DEL\s+COMERCIO',
        r'WT/DS\d+/[A-Za-z0-9/.\-]+',
        r'G/[A-Z]+/[A-Za-z0-9/.\-]+',
        r'S/L/\d+(?:/[A-Za-z0-9.]+)*',
        r'IP/D/\d+(?:/[A-Za-z0-9.]+)*',
        r'\(\d{2}-\d{4,5}\)\s*(?:Page:\s*\d+/\d+)?',
        r'Page:\s*\d+/\d+',
        r'^\s*\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*$',
        r'Original:\s*(?:English|French|Spanish)(?:/\w+)*',
        r'logo:\s*World Trade Organization.*?(?=\n\n|\Z)',
        r'Visible Text and Design\s*:.*?(?=\n\n|\Z)',
        r'Dimensions and Placement\s*:.*?(?=\n\n|\Z)',
        r'Analysis\s*:.*?(?=\n\n|\Z)',
        r'<!--.*?-->',
    ]

    # Non-English detection word sets (common function words)
    _FRENCH_WORDS = frozenset({
        'le', 'la', 'les', 'des', 'du', 'une', 'un', 'qui', 'que',
        'dans', 'par', 'pour', 'avec', 'sur', 'sont', 'cette',
        'ces', 'aux', 'ont', 'nous', 'leur', 'pas', 'mais', 'aussi',
        'peut', 'soit', 'tous', 'tout', 'ses', 'elle',
    })
    _SPANISH_WORDS = frozenset({
        'el', 'los', 'las', 'del', 'una', 'un', 'que', 'por', 'para',
        'con', 'como', 'esta', 'este', 'sus', 'pero', 'sin',
        'entre', 'sobre', 'desde', 'hasta', 'todos', 'puede', 'cada',
    })
    _NON_EN_WORDS = _FRENCH_WORDS | _SPANISH_WORDS

    @classmethod
    def clean(cls, text: str, case_title: str = '') -> str:
        """Clean WTO document text for RAG embeddings.

        Removes: WTO boilerplate headers, RESTRICTED markers, page numbers,
        footnote blocks, non-English paragraphs, repeated page headers,
        and punctuation artifacts.
        """
        if not text:
            return ""

        cleaned = text

        # 1. Remove WTO header patterns (org names, codes, dates, etc.)
        for pattern in cls.HEADER_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)

        # 2. Remove RESTRICTED keyword (standalone on a line)
        cleaned = re.sub(r'^\s*RESTRICTED\s*$', '', cleaned, flags=re.MULTILINE)

        # 3. Remove language markers (anglais, inglés)
        cleaned = re.sub(r'^\s*\(?\s*(?:anglais|ingles|inglés)\s*\)?\s*$', '',
                         cleaned, flags=re.MULTILINE | re.IGNORECASE)

        # 4. Remove page number artifacts
        cleaned = cls._remove_page_numbers(cleaned)

        # 5. Remove footnote blocks (underscore separator + numbered text)
        cleaned = cls._remove_footnotes(cleaned)

        # 6. Remove non-English paragraphs (French/Spanish)
        cleaned = cls._remove_non_english(cleaned)

        # 7. Remove repeated case title headers (appear on each page)
        if case_title:
            cleaned = cls._remove_repeated_headers(cleaned, case_title)

        # 8. Remove punctuation noise lines
        cleaned = cls._remove_punctuation_noise(cleaned)

        # 9. Final whitespace cleanup
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r' +\n', '\n', cleaned)
        cleaned = cleaned.strip()

        return cleaned

    @staticmethod
    def _remove_page_numbers(text: str) -> str:
        """Remove page number artifacts from PDF extraction."""
        # "Page N" or "Page A-N" style
        text = re.sub(r'^\s*Page\s+[A-Z]?-?\d+\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
        # Centered "- N -" page numbers
        text = re.sub(r'^\s*-\s*\d+\s*-\s*$', '', text, flags=re.MULTILINE)
        return text

    @staticmethod
    def _remove_footnotes(text: str) -> str:
        """Remove footnote blocks demarcated by underscore separators.

        WTO PDFs have footnotes at page bottoms separated by an underscore
        line (___), followed by numbered footnote text (e.g., "1 See ...").
        Multi-line footnotes are handled by continuing to skip lines after
        a footnote number until the next footnote number or blank line.
        """
        lines = text.split('\n')
        result = []
        i = 0

        while i < len(lines):
            stripped = lines[i].strip()

            # Detect footnote separator (3+ underscores)
            if re.match(r'^_{3,}\s*$', stripped):
                i += 1
                saw_footnote = False
                # Skip footnote content after separator
                while i < len(lines):
                    s = lines[i].strip()
                    if re.match(r'^\d{1,3}[\s.)]', s):
                        # Numbered footnote line
                        saw_footnote = True
                        i += 1
                    elif saw_footnote and s and not s[0].isupper():
                        # Continuation of previous footnote (lowercase start)
                        i += 1
                    elif not s:
                        # Blank line: check if more footnotes follow
                        j = i + 1
                        while j < len(lines) and not lines[j].strip():
                            j += 1
                        if j < len(lines) and re.match(r'^\d{1,3}[\s.)]', lines[j].strip()):
                            i += 1  # Skip blank between footnotes
                        else:
                            break  # End of footnote block
                    else:
                        break  # Non-footnote content reached
                continue

            result.append(lines[i])
            i += 1

        return '\n'.join(result)

    @classmethod
    def _remove_non_english(cls, text: str) -> str:
        """Remove paragraphs that are primarily in French or Spanish.

        Uses word-frequency detection: if >15% of words in a paragraph
        are common French/Spanish function words, the paragraph is removed.
        Short paragraphs (<8 words) are kept to avoid false positives.
        """
        paragraphs = re.split(r'\n\s*\n', text)
        kept = []
        for para in paragraphs:
            words = re.findall(r'\b[a-zà-ÿ]+\b', para.lower())
            if len(words) < 8:
                kept.append(para)
                continue
            non_en_count = sum(1 for w in words if w in cls._NON_EN_WORDS)
            ratio = non_en_count / len(words)
            if ratio < 0.15:
                kept.append(para)
        return '\n\n'.join(kept)

    @staticmethod
    def _remove_repeated_headers(text: str, case_title: str) -> str:
        """Remove repeated case title headers that appear on each page."""
        if not case_title or len(case_title) < 10:
            return text
        # Build flexible pattern from case title (allow whitespace variation)
        escaped = re.escape(case_title)
        flexible = re.sub(r'\\\s+', r'\\s+', escaped)
        # Keep the first occurrence, remove all subsequent ones
        match = re.search(flexible, text, re.IGNORECASE)
        if match:
            first_end = match.end()
            before = text[:first_end]
            after = re.sub(flexible, '', text[first_end:], flags=re.IGNORECASE)
            text = before + after
        return text

    @staticmethod
    def _remove_punctuation_noise(text: str) -> str:
        """Remove lines that are primarily punctuation artifacts from PDF extraction."""
        # Lines that are just punctuation/whitespace (e.g., ". /.", ", ,")
        text = re.sub(r'^\s*[.,:;/\\|*#@!?(){}\[\]]+\s*$', '', text, flags=re.MULTILINE)
        return text
