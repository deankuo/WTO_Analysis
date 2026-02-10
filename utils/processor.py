"""Main WTO Document Processor orchestrating filename parsing, content extraction,
naming generation, and output.

Key changes from monolithic version:
  - Two-pass suffix numbering: counts type occurrences first, then assigns
    zero-padded _00, _01, _02 suffixes for duplicates
  - Separate outputs: metadata CSV (no clean_text) + JSONL (with clean_text)
  - case_summary is NOT truncated
"""

import re
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict

from langchain_community.document_loaders import PyPDFLoader

# Set up logging first before any code that might use it
csv.field_size_limit(sys.maxsize)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("OCR libraries not available. Install: pip install pytesseract pdf2image")

from .filename_parser import FileInfo, FilenameParser, DOC_CLASS_PRIORITY
from .text_cleaner import ContentParser, TextCleaner


@dataclass
class ProcessedDocument:
    """Complete processed document with all metadata."""
    folder_number: str
    case_number: str
    original_filename: str
    new_filename: str
    doc_sequence: int
    doc_type: str
    doc_type_raw: str
    doc_class: str
    variant: Optional[str]
    part_number: Optional[int]
    case_title: str
    date: Optional[str]
    header_codes: str
    agreement_indicators: str
    complainant: Optional[str]
    respondent: Optional[str]
    third_parties: Optional[str]
    dispute_stage: Optional[str]
    agreements_cited: Optional[str]
    case_summary: Optional[str]
    page_count: int
    clean_text: str
    processing_date: str


class NamingGenerator:
    """Generates semantic filenames for WTO documents.

    Uses two-pass approach: caller provides total count of plain (no variant/part)
    occurrences per type and the 0-based index, so duplicates get _00, _01, _02.
    """

    @staticmethod
    def generate(case_number: str, seq: int, doc_type: str, file_info: FileInfo,
                 plain_idx: Optional[int], plain_total: int) -> str:
        """Generate new filename.

        Args:
            case_number: DS case number
            seq: Sequential number within case
            doc_type: Normalized document type
            file_info: Parsed filename info
            plain_idx: 0-based index among plain occurrences of this type (None if variant/part)
            plain_total: Total plain occurrences of this type in the case
        """
        name = f"DS{case_number}_SEQ{seq:02d}_{doc_type}"

        # Variant suffix (Add, Corr, Rev, Sup)
        if file_info.variant:
            if file_info.variant_number and file_info.variant_number > 1:
                name += f"_{file_info.variant}{file_info.variant_number}"
            else:
                name += f"_{file_info.variant}"

        # Part number for multi-part documents
        if file_info.part_number is not None:
            name += f"_{file_info.part_number:02d}"

        # Zero-padded duplicate counter for plain files with multiple occurrences
        if plain_total > 1 and plain_idx is not None:
            name += f"_{plain_idx:02d}"

        return name + ".pdf"


class ThirdPartyDetector:
    """Detects third-party joining from document types and content."""

    @staticmethod
    def detect(doc_type: str, first_page_text: str, case_number: str,
               date: Optional[str]) -> Optional[Dict]:
        if 'Join' not in doc_type and 'join' not in doc_type.lower():
            return None

        text_norm = re.sub(r'\s+', ' ', first_page_text[:1500])

        country = None
        m = re.search(r'communication\s+from\s+(\w[\w\s]+?)(?:\s*the\s+following|\s*$)',
                      text_norm, re.IGNORECASE)
        if m:
            country = m.group(1).strip()

        if not country:
            m = re.search(r'join(?:ing)?\s+(?:the\s+)?consultations?\s*(?:by|from)\s+(\w[\w\s]+?)(?:\s*the\s+following|\s*$)',
                          text_norm, re.IGNORECASE)
            if m:
                country = m.group(1).strip()

        if not country:
            m = re.search(r'communication\s+from\s+([A-Z][\w\s]+)', text_norm, re.IGNORECASE)
            if m:
                country = m.group(1).strip()
                country = re.sub(r'\s+the\s+following.*$', '', country, flags=re.IGNORECASE).strip()

        return {
            'case_number': case_number,
            'country': country or 'UNKNOWN',
            'joining_date': date,
            'document_type': doc_type,
        }


class WTODocumentProcessor:
    """Main orchestrator for processing WTO DSB documents."""

    def __init__(self, cases_dir: Path, metadata_csv: Path, output_dir: Path):
        self.cases_dir = Path(cases_dir)
        self.metadata_csv = Path(metadata_csv)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.case_metadata_cache: Dict[str, Dict] = {}
        self.manual_review: List[Dict] = []
        self.third_party_joinings: List[Dict] = []
        self._load_case_metadata()

    def _load_case_metadata(self):
        try:
            with open(self.metadata_csv, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    case_id = row.get('case', '')
                    m = re.search(r'DS(\d+)', case_id)
                    if m:
                        num = m.group(1)
                        self.case_metadata_cache[num] = {
                            'complainant': row.get('Complainant', ''),
                            'respondent': row.get('Respondent', ''),
                            'third_parties': row.get('third_parties', ''),
                            'case_summary': row.get('summary', '') or '',
                            'agreements_cited': row.get('agreements_cited', ''),
                            'dispute_stage': row.get('dispute_stage', ''),
                            'case_title_csv': row.get('title', ''),
                        }
            logger.info(f"Loaded metadata for {len(self.case_metadata_cache)} cases")
        except Exception as e:
            logger.error(f"Failed to load case metadata: {e}")

    def _get_case_meta(self, case_number: str) -> Dict:
        return self.case_metadata_cache.get(case_number, {})

    @staticmethod
    def _get_ocr_cache_path(pdf_path: Path) -> Path:
        """Get cache file path for OCR results."""
        cache_dir = Path('.ocr_cache')
        cache_dir.mkdir(exist_ok=True)
        # Use PDF path + modification time as cache key
        mtime = pdf_path.stat().st_mtime
        cache_key = f"{pdf_path.stem}_{int(mtime)}.json"
        return cache_dir / cache_key

    @staticmethod
    def _ocr_pdf(pdf_path: Path, max_pages: int = 10) -> Tuple[str, int, str]:
        """Extract text from scanned PDF using OCR.

        Returns (first_page_text, total_pages, full_text).
        Uses disk cache to avoid re-OCR of same files.
        """
        if not OCR_AVAILABLE:
            logger.warning(f"OCR not available for {pdf_path.name}")
            return '', 0, ''

        # Check cache first
        cache_path = WTODocumentProcessor._get_ocr_cache_path(pdf_path)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                    logger.info(f"  Using cached OCR for {pdf_path.name}")
                    return cached['first_page'], cached['page_count'], cached['full_text']
            except Exception as e:
                logger.warning(f"  Cache read failed, re-running OCR: {e}")

        try:
            # Convert PDF to images (limit to max_pages to save time)
            images = convert_from_path(str(pdf_path), dpi=300, first_page=1, last_page=max_pages)
            if not images:
                return '', 0, ''

            # OCR each page
            all_pages = []
            for image in images:
                text = pytesseract.image_to_string(image, lang='eng')
                all_pages.append(text)

            first_page = all_pages[0] if all_pages else ''
            page_count = len(all_pages)
            full_text = '\n\n'.join(all_pages)

            # Save to cache
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'first_page': first_page,
                        'page_count': page_count,
                        'full_text': full_text
                    }, f)
            except Exception as e:
                logger.warning(f"  Failed to save OCR cache: {e}")

            return first_page, page_count, full_text

        except Exception as e:
            logger.error(f"OCR failed for {pdf_path.name}: {e}")
            return '', 0, ''

    @staticmethod
    def _validate_date(date_str: Optional[str]) -> Optional[str]:
        """Validate date is after WTO establishment (1995-01-01).

        Returns None if date is invalid or before 1995.
        Accepts formats: "DD Month YYYY" or "YYYY-MM-DD"
        """
        if not date_str:
            return None

        try:
            # Extract year from end of string (format: "13 January 1995")
            # or from beginning (format: "1995-01-01")
            import re
            year_match = re.search(r'\b(\d{4})\b', date_str)
            if year_match:
                year = int(year_match.group(1))
                if year < 1995:
                    return None
                return date_str
            return None
        except:
            return None

    def _read_pdf(self, pdf_path: Path) -> Tuple[str, int, str]:
        """Read PDF and return (first_page_text, total_pages, full_text).

        For long documents (>5 pages), TOC and blank pages are excluded
        from full_text to avoid polluting RAG embeddings.

        Falls back to OCR if PyPDFLoader extracts very little text (scanned PDF).
        """
        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load()
        if not pages:
            return '', 0, ''
        first_page = pages[0].page_content
        page_count = len(pages)

        # Check if this is a scanned PDF (very little text extracted)
        if len(first_page.strip()) < 50 and OCR_AVAILABLE:
            logger.info(f"  Scanned PDF detected, using OCR: {pdf_path.name}")
            return self._ocr_pdf(pdf_path)

        if page_count > 5:
            content_pages = []
            for p in pages:
                text = p.page_content
                if len(text.strip()) < 50:
                    continue
                if TextCleaner.is_toc_page(text):
                    continue
                content_pages.append(text)
            full_text = '\n'.join(content_pages) if content_pages else first_page
        else:
            full_text = '\n'.join(p.page_content for p in pages)

        return first_page, page_count, full_text

    def process_folder(self, folder_path: Path) -> List[ProcessedDocument]:
        """Process all PDFs in a single case folder."""
        folder_name = folder_path.name
        # Match both .pdf and .PDF extensions
        pdf_files = list(folder_path.glob('*.pdf')) + list(folder_path.glob('*.PDF'))
        if not pdf_files:
            return []

        logger.info(f"\n{'='*60}")
        logger.info(f"Processing folder {folder_name}: {len(pdf_files)} files")
        logger.info(f"{'='*60}")

        # Step 1: Parse all filenames
        file_infos = []
        for pdf in pdf_files:
            fi = FilenameParser.parse(pdf.name, folder_name)
            file_infos.append((pdf, fi))

        # Step 2: Group by case number
        case_groups: Dict[str, List[Tuple[Path, FileInfo]]] = defaultdict(list)
        for pdf, fi in file_infos:
            case_groups[fi.file_case_number].append((pdf, fi))

        # Step 3: Process each case group
        all_docs = []
        for case_num in sorted(case_groups.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            docs = self._process_case_group(case_num, case_groups[case_num], folder_name)
            all_docs.extend(docs)

        return all_docs

    def _process_case_group(self, case_number: str, files: List[Tuple[Path, FileInfo]],
                            folder_name: str) -> List[ProcessedDocument]:
        """Process a group of files belonging to the same case number.

        Two-pass approach:
          Pass 1: Read all files, extract content metadata, determine doc types.
          Pass 2: Count plain occurrences per type, generate zero-padded names.
        """
        files.sort(key=lambda x: x[1].sort_key)
        case_meta = self._get_case_meta(case_number)

        # ---- Pass 1: Extract content metadata ----
        file_data = []
        parent_doc_types: Dict[Optional[int], str] = {}  # Legacy: for variant inheritance

        # NEW: Track first part of each document group for inheritance
        # Key: (doc_number, doc_class, variant, variant_number)
        # Value: {doc_type, date, case_title}
        first_part_metadata: Dict[tuple, Dict] = {}
        # Track minimum part number seen for each group
        min_part_by_group: Dict[tuple, int] = {}

        for seq, (pdf_path, file_info) in enumerate(files, start=1):
            try:
                logger.info(f"  [{seq:02d}] {pdf_path.name} (class={file_info.doc_class})")
                first_page, page_count, full_text = self._read_pdf(pdf_path)

                if page_count == 0:
                    logger.warning(f"    No pages extracted from {pdf_path.name}")
                    self.manual_review.append({
                        'folder': folder_name, 'filename': pdf_path.name,
                        'case_number': case_number, 'error': 'No pages extracted',
                        'reason': 'empty_pdf',
                    })
                    continue

                date = ContentParser.extract_date(first_page)
                header_codes = ContentParser.extract_header_codes(first_page)
                agreement_indicators = ContentParser.map_agreement_indicators(header_codes)
                case_title = ContentParser.extract_case_title(first_page)
                doc_type, doc_type_raw = ContentParser.extract_doc_type(first_page)

                # Validate date (must be >= 1995)
                date = self._validate_date(date)

                # ========== NEW INHERITANCE LOGIC ==========
                # Create grouping key for this document
                # Groups documents that should share metadata (all parts of same doc)
                # sort_key[1] distinguishes RW/RW2/RW3, R/R2, etc.
                group_key = (
                    file_info.doc_number,
                    file_info.doc_class,
                    file_info.variant,
                    file_info.variant_number,
                    file_info.sort_key[1] if len(file_info.sort_key) > 1 else 0  # RW number, R number, etc.
                )

                # Special case: 457-17-02.pdf inherits from 457-17-01.pdf
                if pdf_path.name == '457-17-02.pdf' and case_number == '457':
                    # Will inherit from first part of group (457-17-01.pdf)
                    pass

                # Determine if this is the first part of a multi-part group
                # Only track files that actually have part_number (multi-part docs)
                if file_info.part_number is not None:
                    # Track minimum part number for this group
                    if group_key not in min_part_by_group:
                        min_part_by_group[group_key] = file_info.part_number
                    else:
                        min_part_by_group[group_key] = min(min_part_by_group[group_key], file_info.part_number)

                    is_first_part = (file_info.part_number == min_part_by_group[group_key])
                else:
                    is_first_part = False  # Non-part files are never "first part"

                # If not the first part, try to inherit from first part
                if not is_first_part and file_info.part_number is not None:
                    first_meta = first_part_metadata.get(group_key)
                    if first_meta:
                        # Inherit doc_type if current is UNKNOWN or generic
                        if doc_type in ('UNKNOWN', 'Addendum', 'Corrigendum'):
                            doc_type = first_meta.get('doc_type', doc_type)
                        # Inherit date if missing
                        if not date:
                            date = first_meta.get('date')
                        # Inherit case_title if empty
                        if not case_title:
                            case_title = first_meta.get('case_title', '')
                            logger.debug(f"      Inherited case_title")

                # Legacy: Corrigendum/Addendum variant inheritance (for non-multi-part)
                if doc_type in ('Corrigendum', 'Addendum') and file_info.variant and file_info.part_number is None:
                    parent_type = parent_doc_types.get(file_info.doc_number)
                    if parent_type and parent_type not in ('Corrigendum', 'Addendum', 'UNKNOWN'):
                        doc_type = parent_type

                if doc_type == 'UNKNOWN':
                    doc_type = self._fallback_doc_type(file_info)
                    if doc_type == 'UNKNOWN':
                        # Determine specific reason for manual review
                        text_len = len(first_page.strip())
                        if text_len < 50:
                            reason = 'scanned_pdf'
                        elif 'ORGANISATION MONDIALE' in first_page or 'ORGANIZACIÓN MUNDIAL' in first_page:
                            reason = 'non_english'
                        else:
                            reason = 'unknown_doc_type'
                        logger.warning(f"    Could not identify type for {pdf_path.name} ({reason})")
                        self.manual_review.append({
                            'folder': folder_name, 'filename': pdf_path.name,
                            'case_number': case_number, 'doc_class': file_info.doc_class,
                            'first_page_preview': first_page[:500],
                            'reason': reason,
                        })

                # Record parent types for legacy variant inheritance
                if file_info.variant is None and file_info.doc_number is not None:
                    parent_doc_types[file_info.doc_number] = doc_type

                # Record first part metadata for multi-part inheritance
                if is_first_part and file_info.part_number is not None:
                    first_part_metadata[group_key] = {
                        'doc_type': doc_type,
                        'date': date,
                        'case_title': case_title,
                    }

                file_data.append({
                    'pdf_path': pdf_path, 'file_info': file_info, 'seq': seq,
                    'first_page': first_page, 'page_count': page_count,
                    'full_text': full_text, 'date': date,
                    'header_codes': header_codes,
                    'agreement_indicators': agreement_indicators,
                    'case_title': case_title, 'doc_type': doc_type,
                    'doc_type_raw': doc_type_raw,
                })

            except Exception as e:
                logger.error(f"  ERROR processing {pdf_path.name}: {e}")
                self.manual_review.append({
                    'folder': folder_name, 'filename': pdf_path.name,
                    'case_number': case_number, 'error': str(e),
                    'reason': 'processing_error',
                })

        # ---- Count plain (no variant, no part) occurrences per type ----
        type_plain_counts: Dict[str, int] = defaultdict(int)
        for fd in file_data:
            fi = fd['file_info']
            if fi.variant is None and fi.part_number is None:
                type_plain_counts[fd['doc_type']] += 1

        # ---- Pass 2: Generate names and build documents ----
        type_plain_counter: Dict[str, int] = defaultdict(int)
        processed = []

        for fd in file_data:
            fi = fd['file_info']
            doc_type = fd['doc_type']

            # Determine plain occurrence index
            plain_idx = None
            plain_total = type_plain_counts.get(doc_type, 0)
            if fi.variant is None and fi.part_number is None:
                plain_idx = type_plain_counter[doc_type]
                type_plain_counter[doc_type] += 1

            new_filename = NamingGenerator.generate(
                case_number, fd['seq'], doc_type, fi, plain_idx, plain_total
            )

            # Third-party detection
            tp_info = ThirdPartyDetector.detect(doc_type, fd['first_page'], case_number, fd['date'])
            if tp_info:
                self.third_party_joinings.append(tp_info)

            clean_text = TextCleaner.clean(fd['full_text'])

            doc = ProcessedDocument(
                folder_number=folder_name,
                case_number=case_number,
                original_filename=fd['pdf_path'].name,
                new_filename=new_filename,
                doc_sequence=fd['seq'],
                doc_type=doc_type,
                doc_type_raw=fd['doc_type_raw'],
                doc_class=fi.doc_class,
                variant=fi.variant,
                part_number=fi.part_number,
                case_title=fd['case_title'],
                date=fd['date'],
                header_codes='; '.join(fd['header_codes']),
                agreement_indicators='; '.join(fd['agreement_indicators']),
                complainant=case_meta.get('complainant', ''),
                respondent=case_meta.get('respondent', ''),
                third_parties=case_meta.get('third_parties', ''),
                dispute_stage=case_meta.get('dispute_stage', ''),
                agreements_cited=case_meta.get('agreements_cited', ''),
                case_summary=case_meta.get('case_summary', ''),
                page_count=fd['page_count'],
                clean_text=clean_text,
                processing_date=datetime.now().isoformat(),
            )

            logger.info(f"    -> {doc_type} | {fd['date'] or 'no date'} | {fd['page_count']}p | -> {new_filename}")
            processed.append(doc)

        return processed

    @staticmethod
    def _fallback_doc_type(fi: FileInfo) -> str:
        class_map = {
            'PANEL_REPORT': 'Report_Of_Panel',
            'PANEL_REPORT_ADD': 'Report_Of_Panel',
            'PANEL_REPORT_CORR': 'Report_Of_Panel',
            'PANEL_REPORT_SUP': 'Report_Of_Panel',
            'AB_REPORT': 'Report_Of_Appellate_Body',
            'AB_REPORT_ADD': 'Report_Of_Appellate_Body',
            'AB_REPORT_CORR': 'Report_Of_Appellate_Body',
            'RECOURSE': 'Art_21_5_Recourse',
            'RECOURSE_ADD': 'Art_21_5_Recourse',
            'AB_RECOURSE': 'Art_21_5_Recourse',
            'AB_RECOURSE_ADD': 'Art_21_5_Recourse',
            'ARBITRATION': 'Arbitration',
            'ARBITRATION_ADD': 'Arbitration',
            'D_FILE': 'Request_For_Consultations',
            'W_FILE': 'Working_Document',
        }
        doc_type = class_map.get(fi.doc_class)
        if doc_type:
            return doc_type
        # Fall back to variant if present
        if fi.variant == 'Add':
            return 'Addendum'
        if fi.variant == 'Corr':
            return 'Corrigendum'
        if fi.variant == 'Rev':
            return 'Revision'
        return 'UNKNOWN'

    # ---- Output methods ----

    def save_csv(self, documents: List[ProcessedDocument], filename: str = 'wto_documents.csv'):
        """Save metadata CSV (excludes clean_text — use save_jsonl for text)."""
        path = self.output_dir / filename
        if not documents:
            logger.warning("No documents to save")
            return path

        fieldnames = [
            'folder_number', 'case_number', 'doc_sequence', 'doc_type', 'doc_type_raw',
            'doc_class', 'variant', 'part_number',
            'original_filename', 'new_filename',
            'case_title', 'date', 'header_codes', 'agreement_indicators',
            'complainant', 'respondent', 'third_parties',
            'dispute_stage', 'agreements_cited',
            'page_count', 'case_summary', 'processing_date',
        ]

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for doc in documents:
                writer.writerow(asdict(doc))

        logger.info(f"CSV saved: {path} ({len(documents)} documents)")
        return path

    def save_jsonl(self, documents: List[ProcessedDocument], filename: str = 'wto_documents.jsonl'):
        """Save JSONL with all fields including clean_text (source for vector DB)."""
        path = self.output_dir / filename
        if not documents:
            logger.warning("No documents to save")
            return path

        with open(path, 'w', encoding='utf-8') as f:
            for doc in documents:
                f.write(json.dumps(asdict(doc), ensure_ascii=False) + '\n')

        logger.info(f"JSONL saved: {path} ({len(documents)} documents)")
        return path

    def save_rename_manifest(self, documents: List[ProcessedDocument],
                              filename: str = 'rename_manifest.json'):
        path = self.output_dir / filename
        manifest = []
        for doc in documents:
            manifest.append({
                'folder': doc.folder_number,
                'case': doc.case_number,
                'original': doc.original_filename,
                'new': doc.new_filename,
                'type': doc.doc_type,
                'sequence': doc.doc_sequence,
                'date': doc.date,
            })

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logger.info(f"Rename manifest saved: {path}")
        return path

    def save_manual_review(self, filename: str = 'manual_review.json'):
        path = self.output_dir / filename
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.manual_review, f, indent=2, ensure_ascii=False)
        logger.info(f"Manual review list saved: {path} ({len(self.manual_review)} files)")
        return path

    def save_third_party_joinings(self, filename: str = 'third_party_early_joiners.json'):
        path = self.output_dir / filename
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.third_party_joinings, f, indent=2, ensure_ascii=False)
        logger.info(f"Third-party joinings saved: {path} ({len(self.third_party_joinings)} entries)")
        return path

    def execute_renames(self, documents: List[ProcessedDocument], dry_run: bool = True):
        mode = "DRY RUN" if dry_run else "EXECUTING"
        logger.info(f"\n{'='*60}")
        logger.info(f"{mode}: Renaming {len(documents)} files")
        logger.info(f"{'='*60}")

        renamed = 0
        skipped = 0
        conflicts = 0

        for doc in documents:
            old_path = self.cases_dir / doc.folder_number / doc.original_filename
            new_path = self.cases_dir / doc.folder_number / doc.new_filename

            if not old_path.exists():
                logger.warning(f"  MISSING: {old_path}")
                skipped += 1
                continue

            if old_path.name == new_path.name:
                skipped += 1
                continue

            if new_path.exists():
                logger.warning(f"  CONFLICT: {new_path.name} already exists!")
                conflicts += 1
                continue

            logger.info(f"  {doc.original_filename} -> {doc.new_filename}")
            if not dry_run:
                old_path.rename(new_path)
            renamed += 1

        logger.info(f"\n{mode} complete: {renamed} renamed, {skipped} skipped, {conflicts} conflicts")

    def process_cases(self, case_numbers: Optional[List[str]] = None) -> List[ProcessedDocument]:
        """Process specified cases (or all if None)."""
        all_docs = []

        if case_numbers:
            # Only process folders whose names match the requested case numbers
            # (don't scan file contents to avoid pulling in unrelated folders)
            folders_to_process = set()
            for folder in sorted(self.cases_dir.iterdir()):
                if not folder.is_dir():
                    continue
                if folder.name in case_numbers:
                    folders_to_process.add(folder)

            for folder in sorted(folders_to_process, key=lambda f: int(f.name) if f.name.isdigit() else 0):
                docs = self.process_folder(folder)
                # Filter to only docs belonging to requested cases
                docs = [d for d in docs if d.case_number in case_numbers]
                all_docs.extend(docs)
        else:
            for folder in sorted(self.cases_dir.iterdir(),
                                  key=lambda f: int(f.name) if f.name.isdigit() else 0):
                if folder.is_dir():
                    docs = self.process_folder(folder)
                    all_docs.extend(docs)

        return all_docs
