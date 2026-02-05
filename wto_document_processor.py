"""
WTO Document Processor for RAG System
Processes WTO DSB case documents, cleans text, identifies document types,
and prepares data for RAG-based LLM judge system.
"""

import re
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
from datetime import datetime
from langchain_community.document_loaders import PyPDFLoader
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ProcessedDocument:
    """Structured data for a processed WTO document"""
    case_number: str
    original_filename: str
    new_filename: str
    doc_sequence: int
    doc_type: str
    doc_type_raw: str  # Original extracted text
    case_title: str
    clean_text: str
    page_count: int
    processing_date: str
    # Case metadata
    complainant: Optional[str] = None
    respondent: Optional[str] = None
    third_parties: Optional[str] = None
    case_summary: Optional[str] = None
    agreements_cited: Optional[str] = None
    dispute_stage: Optional[str] = None


class DocumentTypeClassifier:
    """Identifies WTO document types from text"""

    # Comprehensive document type patterns
    DOC_TYPE_PATTERNS = {
        'REQUEST_FOR_CONSULTATIONS': r'REQUEST FOR CONSULTATIONS?\s+(?:BY|FROM)\s+([A-Z\s,]+)',
        'REQUEST_FOR_ESTABLISHMENT_OF_PANEL': r'REQUEST FOR (?:THE )?ESTABLISHMENT OF (?:A )?PANEL',
        'PANEL_REPORT': r'(?:REPORT OF THE )?PANEL(?:\s+REPORT)?(?!\s+LAPSED)',
        'APPELLATE_BODY_REPORT': r'REPORT OF THE APPELLATE BODY|APPELLATE BODY REPORT',
        'NOTIFICATION_OF_MUTUALLY_AGREED_SOLUTION': r'NOTIFICATION OF (?:A )?MUTUALLY AGREED SOLUTION',
        'NOTIFICATION_OF_APPEAL': r'NOTIFICATION OF (?:AN )?APPEAL',
        'COMMUNICATION': r'COMMUNICATION\s+(?:FROM|BY)\s+([A-Z\s,]+)',
        'ARBITRATION_AWARD': r'ARBITRATION AWARD|AWARD OF THE ARBITRATOR',
        'ARBITRATION_DECISION': r'ARBITRATION DECISION|DECISION BY THE ARBITRATOR',
        'ARBITRATION_REPORT': r'ARBITRATION REPORT|REPORT OF THE ARBITRATOR',
        'CORRIGENDUM': r'CORRIGENDUM|CORRECTION',
        'ADDENDUM': r'ADDENDUM',
        'MINUTES': r'MINUTES OF (?:THE )?MEETING',
        'PANEL_ESTABLISHED': r'(?:CONSTITUTION|COMPOSITION) OF (?:THE )?PANEL',
        'STATUS_REPORT': r'STATUS REPORT',
        'AGREEMENT': r'AGREED PROCEDURES|AGREED SOLUTION',
        'WITHDRAWAL': r'WITHDRAWAL OF (?:THE )?(?:REQUEST|COMPLAINT)',
        'THIRD_PARTY_SUBMISSION': r'THIRD[- ]PARTY\s+(?:SUBMISSION|COMMUNICATION)',
        'EXECUTIVE_SUMMARY': r'EXECUTIVE SUMMARY',
    }

    # Filename-based patterns (for coded filenames like 135ABR.pdf)
    FILENAME_CODES = {
        'ABR': 'APPELLATE_BODY_REPORT',
        'R': 'PANEL_REPORT',
        'RA': 'ARBITRATION_REPORT',
        'RA1': 'ART_21_5_PANEL_REPORT',  # Article 21.5 recourse
        'RA2': 'ART_22_6_ARBITRATION',   # Article 22.6 arbitration
        'C': 'COMMUNICATION',
        'C1': 'CORRIGENDUM',
    }

    @classmethod
    def identify_from_text(cls, text: str) -> Tuple[str, str]:
        """
        Identify document type from text content
        Returns: (standardized_type, raw_matched_text)
        """
        # Search in first 2000 characters (headers)
        search_text = text[:2000].upper()

        for doc_type, pattern in cls.DOC_TYPE_PATTERNS.items():
            match = re.search(pattern, search_text)
            if match:
                raw_text = match.group(0)
                return doc_type, raw_text

        return 'UNKNOWN', ''

    @classmethod
    def identify_from_filename(cls, filename: str) -> Optional[str]:
        """Identify document type from filename codes"""
        # Extract code from filename (e.g., 135ABR.pdf -> ABR)
        match = re.search(r'\d+([A-Z]+\d*)[.-]', filename)
        if match:
            code = match.group(1)
            return cls.FILENAME_CODES.get(code, None)
        return None

    @classmethod
    def get_clean_name(cls, doc_type: str) -> str:
        """Convert document type to clean filename component"""
        return doc_type.replace('_', ' ').title().replace(' ', '_')


class TextCleaner:
    """Cleans WTO document text by removing headers, footers, and boilerplate"""

    # Patterns to remove
    REMOVE_PATTERNS = [
        # WTO document codes
        r'WT/DS\d+/[A-Z0-9/]+(?:/Corr\.\d+)?',
        r'G/L/\d+(?:/Corr\.\d+)?',
        r'G/SCM/D\d+/\d+(?:/Corr\.\d+)?',
        r'G/[A-Z]+/[A-Z0-9/]+',

        # Page numbers and document numbers
        r'\(\d{2}-\d{4,5}\)\s*(?:Page:\s*\d+/\d+)?',
        r'Page:\s*\d+/\d+',

        # Dates
        r'\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',

        # Language indicators
        r'Original:\s*(?:English|French|Spanish)(?:/\w+)*',
        r'Original:\s*\w+/\w+/\w+',

        # HTML comments
        r'<!--.*?-->',

        # WTO logo descriptions
        r'logo:\s*World Trade Organization.*?(?=\n\n|\n[A-Z])',
        r'Visible Text and Design\s*:.*?(?=\n\n|\n[A-Z])',
        r'Dimensions and Placement\s*:.*?(?=\n\n|\n[A-Z])',
        r'Analysis\s*:.*?(?=\n\n|\n[A-Z])',

        # Common boilerplate
        r'The following (?:communication|document).*?is circulated.*?DSU\.',
    ]

    @classmethod
    def clean(cls, text: str) -> str:
        """Clean text by removing headers, footers, and boilerplate"""
        if not text:
            return ""

        cleaned = text

        # Apply all removal patterns
        for pattern in cls.REMOVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned, flags=re.DOTALL | re.IGNORECASE)

        # Clean up whitespace
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # Max 2 newlines
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)     # Single spaces
        cleaned = re.sub(r' +\n', '\n', cleaned)      # Remove trailing spaces
        cleaned = cleaned.strip()

        return cleaned

    @classmethod
    def extract_case_title(cls, text: str) -> str:
        """Extract the main case title from text"""
        # Look for all-caps title in first 1500 chars
        search_text = text[:1500]

        # Pattern: Two or more consecutive lines in all caps
        lines = search_text.split('\n')
        title_lines = []

        for line in lines:
            line = line.strip()
            # Check if line is mostly uppercase and has substance
            if len(line) > 10 and line.isupper() and not re.match(r'^[A-Z]{2,4}/[A-Z0-9/]+$', line):
                title_lines.append(line)
                if len(title_lines) >= 2:  # Title found
                    break

        if title_lines:
            return ' '.join(title_lines[:2])

        return ''


class WTODocumentProcessor:
    """Main processor for WTO documents"""

    def __init__(self, cases_dir: Path, metadata_csv: Path):
        self.cases_dir = Path(cases_dir)
        self.metadata_csv = Path(metadata_csv)
        self.case_metadata = self._load_metadata()

    def _load_metadata(self) -> pd.DataFrame:
        """Load case metadata from CSV"""
        try:
            # Read with proper handling of large file
            df = pd.read_csv(self.metadata_csv, low_memory=False)
            logger.info(f"Loaded metadata for {len(df)} cases")
            return df
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
            return pd.DataFrame()

    def _get_case_metadata(self, case_number: str) -> Dict:
        """Get metadata for specific case"""
        if self.case_metadata.empty:
            return {}

        # Try to find case by number
        case_row = self.case_metadata[self.case_metadata['case'].str.contains(f'DS{case_number}', na=False)]

        if case_row.empty:
            return {}

        row = case_row.iloc[0]
        return {
            'complainant': str(row.get('Complainant', '')),
            'respondent': str(row.get('Respondent', '')),
            'third_parties': str(row.get('third_parties', '')),
            'case_summary': str(row.get('summary', ''))[:500],  # Truncate for CSV
            'agreements_cited': str(row.get('agreements_cited', '')),
            'dispute_stage': str(row.get('dispute_stage', '')),
        }

    def process_pdf(self, pdf_path: Path, case_number: str, sequence: int) -> Optional[ProcessedDocument]:
        """Process a single PDF file"""
        try:
            logger.info(f"Processing: {pdf_path.name}")

            # Load PDF
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()

            if not pages:
                logger.warning(f"No pages extracted from {pdf_path.name}")
                return None

            # Combine all pages
            full_text = '\n'.join([page.page_content for page in pages])
            page_count = len(pages)

            # Identify document type
            doc_type_text, doc_type_raw = DocumentTypeClassifier.identify_from_text(full_text)

            # If not found in text, try filename
            if doc_type_text == 'UNKNOWN':
                filename_type = DocumentTypeClassifier.identify_from_filename(pdf_path.name)
                if filename_type:
                    doc_type_text = filename_type

            # Extract case title
            case_title = TextCleaner.extract_case_title(full_text)

            # Clean text
            clean_text = TextCleaner.clean(full_text)

            # Generate new filename
            doc_type_clean = DocumentTypeClassifier.get_clean_name(doc_type_text)
            new_filename = f"DS{case_number}_SEQ{sequence:02d}_{doc_type_clean}.pdf"

            # Get case metadata
            case_meta = self._get_case_metadata(case_number)

            # Create processed document
            doc = ProcessedDocument(
                case_number=case_number,
                original_filename=pdf_path.name,
                new_filename=new_filename,
                doc_sequence=sequence,
                doc_type=doc_type_text,
                doc_type_raw=doc_type_raw,
                case_title=case_title,
                clean_text=clean_text,
                page_count=page_count,
                processing_date=datetime.now().isoformat(),
                **case_meta
            )

            logger.info(f"  → Type: {doc_type_text}, Pages: {page_count}, Title: {case_title[:50]}...")

            return doc

        except Exception as e:
            logger.error(f"Failed to process {pdf_path.name}: {e}")
            return None

    def process_case(self, case_number: str) -> List[ProcessedDocument]:
        """Process all documents in a case folder"""
        case_dir = self.cases_dir / str(case_number)

        if not case_dir.exists():
            logger.error(f"Case directory not found: {case_dir}")
            return []

        # Get all PDFs sorted by name
        pdf_files = sorted(case_dir.glob('*.pdf'))
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing Case DS{case_number}: {len(pdf_files)} documents")
        logger.info(f"{'='*60}")

        processed_docs = []

        for idx, pdf_path in enumerate(pdf_files, start=1):
            doc = self.process_pdf(pdf_path, case_number, idx)
            if doc:
                processed_docs.append(doc)

        return processed_docs

    def process_multiple_cases(self, case_numbers: List[str]) -> List[ProcessedDocument]:
        """Process multiple cases"""
        all_docs = []

        for case_num in case_numbers:
            docs = self.process_case(case_num)
            all_docs.extend(docs)

        return all_docs

    @staticmethod
    def create_csv(documents: List[ProcessedDocument], output_path: Path):
        """Create CSV from processed documents"""
        if not documents:
            logger.warning("No documents to save")
            return

        # Convert to DataFrame
        data = [vars(doc) for doc in documents]
        df = pd.DataFrame(data)

        # Reorder columns for readability
        column_order = [
            'case_number', 'doc_sequence', 'doc_type', 'doc_type_raw',
            'original_filename', 'new_filename',
            'case_title', 'complainant', 'respondent', 'third_parties',
            'dispute_stage', 'agreements_cited',
            'page_count', 'clean_text', 'case_summary', 'processing_date'
        ]

        # Only include columns that exist
        column_order = [col for col in column_order if col in df.columns]
        df = df[column_order]

        # Save
        df.to_csv(output_path, index=False, encoding='utf-8')
        logger.info(f"\n{'='*60}")
        logger.info(f"CSV saved to: {output_path}")
        logger.info(f"Total documents: {len(df)}")
        logger.info(f"{'='*60}")

    @staticmethod
    def create_rename_manifest(documents: List[ProcessedDocument], output_path: Path):
        """Create a JSON manifest of rename operations"""
        manifest = []

        for doc in documents:
            manifest.append({
                'case': doc.case_number,
                'original': doc.original_filename,
                'new': doc.new_filename,
                'type': doc.doc_type,
                'sequence': doc.doc_sequence
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        logger.info(f"Rename manifest saved to: {output_path}")

    @staticmethod
    def execute_renames(documents: List[ProcessedDocument], cases_dir: Path, dry_run: bool = True):
        """Execute file renaming operations"""
        logger.info(f"\n{'='*60}")
        logger.info(f"{'DRY RUN - ' if dry_run else ''}Renaming {len(documents)} files")
        logger.info(f"{'='*60}\n")

        for doc in documents:
            old_path = cases_dir / doc.case_number / doc.original_filename
            new_path = cases_dir / doc.case_number / doc.new_filename

            if old_path == new_path:
                logger.info(f"SKIP (no change): {old_path.name}")
                continue

            if new_path.exists():
                logger.warning(f"CONFLICT: {new_path.name} already exists!")
                continue

            logger.info(f"{doc.original_filename} → {doc.new_filename}")

            if not dry_run:
                old_path.rename(new_path)

        if dry_run:
            logger.info(f"\nDRY RUN completed. Use dry_run=False to execute.")


def main_sample():
    """Process sample cases"""

    # Configuration
    CASES_DIR = Path("/Users/deankuo/Desktop/python/selenium/WTO/WTO_DSB_Cases")
    METADATA_CSV = Path("/Users/deankuo/Desktop/python/selenium/WTO/data/wto_cases.csv")
    OUTPUT_DIR = Path("/Users/deankuo/Desktop/python/selenium/WTO/Output")
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Sample cases: recent simple cases + one complex case
    SAMPLE_CASES = ['624', '625', '626', '135']

    # Initialize processor
    processor = WTODocumentProcessor(CASES_DIR, METADATA_CSV)

    # Process cases
    processed_docs = processor.process_multiple_cases(SAMPLE_CASES)

    # Create CSV
    csv_path = OUTPUT_DIR / "wto_processed_sample.csv"
    processor.create_csv(processed_docs, csv_path)

    # Create rename manifest
    manifest_path = OUTPUT_DIR / "rename_manifest_sample.json"
    processor.create_rename_manifest(processed_docs, manifest_path)

    # Show proposed renames (dry run)
    processor.execute_renames(processed_docs, CASES_DIR, dry_run=True)

    logger.info(f"\n{'='*60}")
    logger.info("Sample processing complete!")
    logger.info(f"Review outputs in: {OUTPUT_DIR}")
    logger.info(f"CSV: {csv_path.name}")
    logger.info(f"Manifest: {manifest_path.name}")
    logger.info(f"{'='*60}")

    return processed_docs


if __name__ == "__main__":
    main_sample()
