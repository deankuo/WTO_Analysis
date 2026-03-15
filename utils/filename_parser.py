"""Filename parser for WTO DSB document PDFs.

Parses WTO PDF filenames to extract structural metadata (case number,
document class, variant, part number, etc.) from 20+ filename patterns.

Patterns handled:
  135-2.pdf        -> NUMBERED, doc_number=2
  135-2A1.pdf      -> NUMBERED, variant=Add
  135-2C1.pdf      -> NUMBERED, variant=Corr
  135R.pdf         -> PANEL_REPORT
  135R-00.pdf      -> PANEL_REPORT, part=0
  135RA1-00.pdf    -> PANEL_REPORT_ADD
  135ABR.pdf       -> AB_REPORT
  135RW.pdf        -> RECOURSE
  135ARB.pdf       -> ARBITRATION
  D15.pdf          -> D_FILE
"""

import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


DOC_CLASS_PRIORITY = {
    'NUMBERED': 0,
    'PANEL_REPORT': 1,
    'PANEL_REPORT_ADD': 2,
    'PANEL_REPORT_CORR': 3,
    'PANEL_REPORT_SUP': 4,
    'AB_REPORT': 5,
    'AB_REPORT_ADD': 6,
    'AB_REPORT_CORR': 7,
    'RECOURSE': 8,
    'RECOURSE_ADD': 9,
    'AB_RECOURSE': 10,
    'AB_RECOURSE_ADD': 11,
    'ARBITRATION': 12,
    'ARBITRATION_ADD': 13,
    'D_FILE': -1,
    'W_FILE': -2,  # Working documents (WT/DSB/W/)
}


@dataclass
class FileInfo:
    """Structural metadata parsed from filename alone."""
    original_filename: str
    folder_number: str
    file_case_number: str       # Case number from filename prefix (or folder for D-files)
    doc_number: Optional[int]   # Sequence number for numbered docs (e.g., 2 for 135-2.pdf)
    doc_class: str              # NUMBERED, PANEL_REPORT, AB_REPORT, etc.
    variant: Optional[str]      # Add, Corr, Rev, Sup, or None
    variant_number: Optional[int]
    part_number: Optional[int]  # For multi-part files (0, 1, 2...)
    is_d_file: bool
    d_reference: Optional[str]  # Original D-file name (e.g., "D15")
    sub_number: Optional[int] = None
    sort_key: tuple = field(default_factory=tuple)


class FilenameParser:
    """Parses WTO PDF filenames to extract structural metadata."""

    @staticmethod
    def parse(filename: str, folder_name: str) -> FileInfo:
        stem = Path(filename).stem

        # --- Already-renamed DS files: DS{case}_SEQ{nn}_{DocType}[_Variant][_Part].pdf ---
        ds_match = re.match(r'^DS(\d+)_SEQ(\d+)_(.+)$', stem)
        if ds_match:
            case_num = ds_match.group(1)
            seq_num = int(ds_match.group(2))
            rest = ds_match.group(3)

            # Parse suffixes from the end of the doc type string
            part_number = None
            variant = None
            variant_number = None

            # Strip trailing two-digit numbers (part number and/or dup index)
            trailing_nums = []
            while re.search(r'_(\d{2})$', rest):
                m = re.search(r'_(\d{2})$', rest)
                trailing_nums.insert(0, int(m.group(1)))
                rest = rest[:m.start()]

            # Check for variant suffix (_Add, _Corr, _Rev, _Sup with optional number)
            var_match = re.search(r'_(Add|Corr|Rev|Sup)(\d*)$', rest)
            if var_match:
                variant = var_match.group(1)
                variant_number = int(var_match.group(2)) if var_match.group(2) else 1
                rest = rest[:var_match.start()]

            # Assign part number from trailing numbers
            if trailing_nums:
                part_number = trailing_nums[0]

            # Infer doc_class from the doc type name
            doc_class = 'NUMBERED'
            rest_lower = rest.lower()
            if 'report_of_panel' in rest_lower:
                doc_class = 'PANEL_REPORT'
            elif 'appellate' in rest_lower:
                doc_class = 'AB_REPORT'
            elif 'recourse' in rest_lower:
                doc_class = 'RECOURSE'
            elif 'arbitration' in rest_lower:
                doc_class = 'ARBITRATION'

            return FileInfo(
                original_filename=filename,
                folder_number=folder_name,
                file_case_number=case_num,
                doc_number=seq_num,
                doc_class=doc_class,
                variant=variant,
                variant_number=variant_number,
                part_number=part_number,
                is_d_file=False,
                d_reference=None,
                sub_number=None,
                sort_key=(DOC_CLASS_PRIORITY.get(doc_class, 0), seq_num,
                          0 if not variant else (1 if variant == 'Add' else 2 if variant == 'Corr' else 3),
                          variant_number or 0, part_number or 0),
            )

        # --- D-files ---
        d_match = re.match(r'^D(\d+)(?:-(\d+))?$', stem)
        if d_match:
            d_ref = d_match.group(0)
            sub = int(d_match.group(2)) if d_match.group(2) else None
            return FileInfo(
                original_filename=filename,
                folder_number=folder_name,
                file_case_number=folder_name,
                doc_number=1,
                doc_class='D_FILE',
                variant=None,
                variant_number=None,
                part_number=sub,
                is_d_file=True,
                d_reference=d_ref,
                sub_number=None,
                sort_key=(-1, 1, 0, 0, sub or 0),
            )

        # --- D-files with variants (addendum/corrigendum) ---
        # Patterns: D11A3.pdf, D27A1.pdf, D15C1.pdf
        d_var_match = re.match(r'^D(\d+)([AC])(\d+)$', stem)
        if d_var_match:
            d_num = int(d_var_match.group(1))
            var_type = d_var_match.group(2)
            var_num = int(d_var_match.group(3))
            variant = 'Add' if var_type == 'A' else 'Corr'
            return FileInfo(
                original_filename=filename,
                folder_number=folder_name,
                file_case_number=folder_name,
                doc_number=1,
                doc_class='D_FILE',
                variant=variant,
                variant_number=var_num,
                part_number=None,
                is_d_file=True,
                d_reference=f'D{d_num}',
                sub_number=None,
                sort_key=(-1, 1, 1 if var_type == 'A' else 2, var_num, 0),
            )

        # --- W-files (WT/DSB/W/ working documents) ---
        # Patterns: W8.pdf, W8A1.pdf, W8C1.pdf, W27A4.pdf, W27A1R1.pdf
        # W-files always belong to the folder's case, not the number in their filename
        w_match = re.match(r'^W(\d+)(A(\d+))?(C(\d+))?(R(\d+))?$', stem)
        if w_match:
            w_num = int(w_match.group(1))
            add_num = int(w_match.group(3)) if w_match.group(3) else None
            corr_num = int(w_match.group(5)) if w_match.group(5) else None
            rev_num = int(w_match.group(7)) if w_match.group(7) else None
            # Determine variant
            variant = None
            variant_number = None
            if rev_num:
                variant = 'Rev'
                variant_number = rev_num
            elif corr_num:
                variant = 'Corr'
                variant_number = corr_num
            elif add_num:
                variant = 'Add'
                variant_number = add_num
            return FileInfo(
                original_filename=filename,
                folder_number=folder_name,
                file_case_number=folder_name,  # W-files belong to folder's case
                doc_number=w_num,
                doc_class='W_FILE',
                variant=variant,
                variant_number=variant_number,
                part_number=None,
                is_d_file=False,
                d_reference=f"W{w_num}",
                sub_number=None,
                sort_key=(-2, w_num, 0 if not variant else (1 if variant == 'Add' else 2 if variant == 'Corr' else 3), variant_number or 0, 0),
            )

        # --- Try to extract case number prefix ---
        case_match = re.match(r'^(\d+)', stem)
        if not case_match:
            return FileInfo(
                original_filename=filename, folder_number=folder_name,
                file_case_number=folder_name, doc_number=None,
                doc_class='UNKNOWN', variant=None, variant_number=None,
                part_number=None, is_d_file=False, d_reference=None,
                sub_number=None, sort_key=(999, 0, 0, 0, 0),
            )

        case_num = case_match.group(1)

        # Validate case number (max is 626)
        if int(case_num) > 626:
            # Use folder number instead (likely a variant like 986C1.pdf)
            case_num = folder_name

        suffix = stem[len(case_match.group(1)):]  # Use original parsed suffix
        return FilenameParser._parse_suffix(suffix, filename, folder_name, case_num)

    @staticmethod
    def _parse_suffix(suffix: str, filename: str, folder_name: str, case_num: str) -> FileInfo:
        base = dict(
            original_filename=filename,
            folder_number=folder_name,
            file_case_number=case_num,
            is_d_file=False,
            d_reference=None,
        )

        # ---- AB Recourse with addendum: ABRWA{n} ----
        m = re.match(r'^ABRWA(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='AB_RECOURSE_ADD',
                           variant='Add', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(11, 0, 1, int(m.group(1)), 0))

        # ---- AB Recourse: ABRW or ABRW-{nn} ----
        m = re.match(r'^ABRW(?:-(\d+))?$', suffix)
        if m:
            part = int(m.group(1)) if m.group(1) else None
            return FileInfo(**base, doc_number=None, doc_class='AB_RECOURSE',
                           variant=None, variant_number=None,
                           part_number=part, sort_key=(10, 0, 0, 0, part or 0))

        # ---- AB Report Corrigendum: ABRC{n} ----
        m = re.match(r'^ABRC(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='AB_REPORT_CORR',
                           variant='Corr', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(7, 0, 2, int(m.group(1)), 0))

        # ---- AB Report Addendum: ABRA{n} or ABRA{n}-{nn} ----
        m = re.match(r'^ABRA(\d+)(?:-(\d+))?$', suffix)
        if m:
            part = int(m.group(2)) if m.group(2) else None
            return FileInfo(**base, doc_number=None, doc_class='AB_REPORT_ADD',
                           variant='Add', variant_number=int(m.group(1)),
                           part_number=part, sort_key=(6, 0, 1, int(m.group(1)), part or 0))

        # ---- AB Report: ABR or ABR-{nn} ----
        m = re.match(r'^ABR(?:-(\d+))?$', suffix)
        if m:
            part = int(m.group(1)) if m.group(1) else None
            return FileInfo(**base, doc_number=None, doc_class='AB_REPORT',
                           variant=None, variant_number=None,
                           part_number=part, sort_key=(5, 0, 0, 0, part or 0))

        # ---- Arbitration Addendum: ARBA{n} ----
        m = re.match(r'^ARBA(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='ARBITRATION_ADD',
                           variant='Add', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(13, 0, 1, int(m.group(1)), 0))

        # ---- Arbitration: ARB or ARBN ----
        m = re.match(r'^ARB(\d*)$', suffix)
        if m:
            vn = int(m.group(1)) if m.group(1) else None
            return FileInfo(**base, doc_number=None, doc_class='ARBITRATION',
                           variant=None, variant_number=vn,
                           part_number=None, sort_key=(12, vn or 0, 0, 0, 0))

        # ---- Recourse Addendum: RWA{n} or RW{n}A{n} ----
        m = re.match(r'^RW(\d*)A(\d+)(?:-(\d+))?$', suffix)
        if m:
            rw_num = int(m.group(1)) if m.group(1) else 0
            part = int(m.group(3)) if m.group(3) else None
            return FileInfo(**base, doc_number=None, doc_class='RECOURSE_ADD',
                           variant='Add', variant_number=int(m.group(2)),
                           part_number=part, sort_key=(9, rw_num, 1, int(m.group(2)), part or 0))

        # ---- Recourse Corrigendum: RWC{n} or RW{n}C{n} ----
        m = re.match(r'^RW(\d*)C(\d+)$', suffix)
        if m:
            rw_num = int(m.group(1)) if m.group(1) else 0
            return FileInfo(**base, doc_number=None, doc_class='RECOURSE',
                           variant='Corr', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(8, rw_num, 2, int(m.group(2)), 0))

        # ---- Recourse: RW or RW-{nn} or RW{n} or RW{n}-{nn} ----
        m = re.match(r'^RW(\d*)(?:-(\d+))?$', suffix)
        if m:
            rw_num = int(m.group(1)) if m.group(1) else 0
            part = int(m.group(2)) if m.group(2) else None
            return FileInfo(**base, doc_number=None, doc_class='RECOURSE',
                           variant=None, variant_number=None,
                           part_number=part, sort_key=(8, rw_num, 0, 0, part or 0))

        # ---- Report Supplement: RS{n} ----
        m = re.match(r'^RS(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='PANEL_REPORT_SUP',
                           variant='Sup', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(4, 0, 3, int(m.group(1)), 0))

        # ---- Report Corrigendum: RC{n} ----
        m = re.match(r'^RC(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='PANEL_REPORT_CORR',
                           variant='Corr', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(3, 0, 2, int(m.group(1)), 0))

        # ---- Report Addendum: RA{n} or RA{n}-{nn} ----
        m = re.match(r'^RA(\d+)(?:-(\d+))?$', suffix)
        if m:
            part = int(m.group(2)) if m.group(2) else None
            return FileInfo(**base, doc_number=None, doc_class='PANEL_REPORT_ADD',
                           variant='Add', variant_number=int(m.group(1)),
                           part_number=part, sort_key=(2, 0, 1, int(m.group(1)), part or 0))

        # ---- Panel Report: R, R-{nn}, or R{nn} ----
        m = re.match(r'^R(?:-?(\d+))?$', suffix)
        if m:
            part = int(m.group(1)) if m.group(1) else None
            return FileInfo(**base, doc_number=None, doc_class='PANEL_REPORT',
                           variant=None, variant_number=None,
                           part_number=part, sort_key=(1, 0, 0, 0, part or 0))

        # ---- Numbered doc with part number: -{n}-{m} (e.g., 8-11-00.pdf) ----
        # Treat the second number as part_number for multi-part documents
        m = re.match(r'^-(\d+)-(\d+)$', suffix)
        if m:
            doc_n = int(m.group(1))
            part_n = int(m.group(2))
            return FileInfo(**base, doc_number=doc_n, doc_class='NUMBERED',
                           variant=None, variant_number=None,
                           part_number=part_n, sub_number=None,
                           sort_key=(0, doc_n, 0, 0, part_n))

        # ---- Numbered doc with revision: -{n}R{m} ----
        m = re.match(r'^-(\d+)R(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Rev', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(0, int(m.group(1)), 3, int(m.group(2)), 0))

        # ---- Numbered doc with addendum: -{n}A{m} or -{n}A (bare A = addendum 1) ----
        m = re.match(r'^-(\d+)[Aa](\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Add', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(0, int(m.group(1)), 1, int(m.group(2)), 0))
        m = re.match(r'^-(\d+)[Aa]$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Add', variant_number=1,
                           part_number=None, sort_key=(0, int(m.group(1)), 1, 1, 0))

        # ---- Numbered doc with corrigendum: -{n}C{m} or -{n}C (bare C = corrigendum 1) ----
        m = re.match(r'^-(\d+)C(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Corr', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(0, int(m.group(1)), 2, int(m.group(2)), 0))
        m = re.match(r'^-(\d+)C$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Corr', variant_number=1,
                           part_number=None, sort_key=(0, int(m.group(1)), 2, 1, 0))

        # ---- Numbered doc with addendum then corrigendum: -{n}A{m}C{k} ----
        m = re.match(r'^-(\d+)A(\d+)C(\d+)$', suffix)
        if m:
            # Treat as corrigendum of the addendum
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Corr', variant_number=int(m.group(3)),
                           part_number=None, sort_key=(0, int(m.group(1)), 2, int(m.group(2)) * 100 + int(m.group(3)), 0))

        # ---- Numbered doc with addendum: -{n}A{m} ----
        m = re.match(r'^-(\d+)A(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant='Add', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(0, int(m.group(1)), 1, int(m.group(2)), 0))

        # ---- Plain numbered doc: -{n} ----
        m = re.match(r'^-(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=int(m.group(1)), doc_class='NUMBERED',
                           variant=None, variant_number=None,
                           part_number=None, sort_key=(0, int(m.group(1)), 0, 0, 0))

        # ---- Base addendum with corrigendum: A{n}C{m} (no dash) ----
        m = re.match(r'^A(\d+)C(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='NUMBERED',
                           variant='Corr', variant_number=int(m.group(2)),
                           part_number=None, sort_key=(0, 0, 2, int(m.group(1)) * 100 + int(m.group(2)), 0))

        # ---- Base addendum: A{n} (no dash) ----
        m = re.match(r'^A(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='NUMBERED',
                           variant='Add', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(0, 0, 1, int(m.group(1)), 0))

        # ---- Base corrigendum: C{n} (no dash) ----
        m = re.match(r'^C(\d+)$', suffix)
        if m:
            return FileInfo(**base, doc_number=None, doc_class='NUMBERED',
                           variant='Corr', variant_number=int(m.group(1)),
                           part_number=None, sort_key=(0, 0, 2, int(m.group(1)), 0))

        # ---- No suffix (just case number) ----
        if suffix == '':
            # If the number doesn't match the folder, it's a cross-reference
            if case_num != folder_name:
                return FileInfo(
                    original_filename=filename, folder_number=folder_name,
                    file_case_number=folder_name,
                    doc_number=1, doc_class='D_FILE',
                    variant=None, variant_number=None,
                    part_number=None, is_d_file=True,
                    d_reference=case_num,
                    sort_key=(-1, 1, 0, 0, 0),
                )
            return FileInfo(**base, doc_number=None, doc_class='PANEL_REPORT',
                           variant=None, variant_number=None,
                           part_number=None, sort_key=(1, 0, 0, 0, 0))

        # ---- Unrecognized ----
        return FileInfo(**base, doc_number=None, doc_class='UNKNOWN',
                       variant=None, variant_number=None,
                       part_number=None, sort_key=(999, 0, 0, 0, 0))
