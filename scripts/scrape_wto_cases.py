"""Scrape WTO Dispute Settlement case data.

Two-stage scraper:
  1. Scrape the status page to get all case titles (DS1–DS600+)
  2. Scrape each individual case page for: current status, key facts table, summary

Output: Data/wto_cases_v2.csv (comprehensive, UTF-8)

Usage:
    # Full scrape (all cases)
    python scripts/scrape_wto_cases.py

    # Scrape specific range
    python scripts/scrape_wto_cases.py --start 1 --end 626

    # Resume from checkpoint
    python scripts/scrape_wto_cases.py --resume

    # Only scrape the status page for titles
    python scripts/scrape_wto_cases.py --titles-only

    # Skip titles page, only scrape case details (requires existing checkpoint/output)
    python scripts/scrape_wto_cases.py --details-only
"""

import argparse
import json
import logging
import os
import platform
import re
import sys
import tempfile
import time

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "Data")
OUTPUT_PATH = os.path.join(DATA_DIR, "wto_cases_v2.csv")
CHECKPOINT_PATH = os.path.join(DATA_DIR, "wto_cases_v2_checkpoint.csv")
TITLES_PATH = os.path.join(DATA_DIR, "wto_case_titles.json")

SELENIUM_DIR = os.path.dirname(PROJECT_ROOT)  # /Users/deankuo/Desktop/python/selenium

STATUS_PAGE_URL = "https://www.wto.org/english/tratop_e/dispu_e/dispu_status_e.htm"
CASE_PAGE_TEMPLATE = "https://www.wto.org/english/tratop_e/dispu_e/cases_e/ds{case_num}_e.htm"

CHECKPOINT_EVERY = 10
PAGE_LOAD_WAIT = 3       # seconds between page loads
RESTART_EVERY = 50       # restart browser every N cases


# ── Driver Setup ─────────────────────────────────────────────

def setup_driver(headless: bool = False):
    """Create a Selenium Chrome driver using Chrome for Testing."""
    system = platform.system()
    if system == "Darwin":
        chrome_binary = os.path.join(
            SELENIUM_DIR,
            "chrome-mac-arm64/Google Chrome for Testing.app",
            "Contents", "MacOS", "Google Chrome for Testing",
        )
    elif system == "Windows":
        chrome_binary = os.path.join(SELENIUM_DIR, "chrome-win", "chrome.exe")
    elif system == "Linux":
        chrome_binary = os.path.join(SELENIUM_DIR, "chrome-linux", "chrome")
    else:
        raise RuntimeError(f"Unsupported OS: {system}")

    chromedriver_name = "chromedriver.exe" if system == "Windows" else "chromedriver"
    chromedriver_path = os.path.join(SELENIUM_DIR, chromedriver_name)

    options = Options()
    temp_dir = tempfile.mkdtemp(prefix="chrome_wto_scrape_")
    options.add_argument(f"--user-data-dir={temp_dir}")
    options.binary_location = chrome_binary

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if headless:
        options.add_argument("--headless=new")

    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver._temp_dir = temp_dir
    return driver


# ── Stage 1: Scrape titles from status page ──────────────────

def scrape_titles(driver) -> dict[int, str]:
    """Scrape case titles from the WTO dispute status page.

    Returns:
        Dict mapping case number (int) to full title string.
        e.g. {1: "Malaysia — Prohibition of Imports of Polyethylene and Polypropylene", ...}
    """
    logger.info("Loading status page: %s", STATUS_PAGE_URL)
    driver.get(STATUS_PAGE_URL)

    # Wait for page content to load
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(5)  # Extra wait for JS rendering

    soup = BeautifulSoup(driver.page_source, "html.parser")

    titles = {}

    # Case titles are in <a class="clean-link"> tags with text like "DS626European Union — ..."
    # The href pattern is /english/tratop_e/dispu_e/cases_e/ds{N}_e.htm
    ds_pattern = re.compile(r"^DS(\d+)\s*(.+)$")

    for link in soup.find_all("a", class_="clean-link"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        m = ds_pattern.match(text)
        if m:
            case_num = int(m.group(1))
            title = m.group(2).strip()
            titles[case_num] = title

    # Fallback: try all <a> tags with DS-pattern hrefs
    if not titles:
        logger.info("clean-link extraction found 0, trying href-based extraction...")
        href_pattern = re.compile(r"/cases_e/ds(\d+)_e\.htm")
        for link in soup.find_all("a", href=href_pattern):
            href_m = href_pattern.search(link["href"])
            text = link.get_text(strip=True)
            text_m = ds_pattern.match(text)
            if href_m and text_m:
                case_num = int(href_m.group(1))
                title = text_m.group(2).strip()
                titles[case_num] = title

    logger.info("Scraped %d case titles from status page", len(titles))

    # Save titles
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TITLES_PATH, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(titles.items())}, f, indent=2, ensure_ascii=False)
    logger.info("Saved titles to %s", TITLES_PATH)

    return titles


# ── Stage 2: Scrape individual case pages ────────────────────

def parse_case_page(driver, case_num: int) -> dict:
    """Scrape a single case page for status, key facts, and summary.

    Returns a dict with all extracted fields.
    """
    url = CASE_PAGE_TEMPLATE.format(case_num=case_num)
    driver.get(url)

    case_data = {"case": f"DS{case_num}"}

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "keyFactsTbl"))
        )
    except TimeoutException:
        # Some cases (like DS11) may not have the key facts table
        logger.warning("DS%d: keyFactsTbl not found (timeout), parsing what's available", case_num)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # ── Current status ──
    # Status is in div.well after h2#status; label in span.paraboldcolourtext
    status_h2 = soup.find("h2", id="status")
    if status_h2:
        well_div = status_h2.find_next("div", class_="well")
        if well_div:
            # Get the full text (e.g. "In consultations on 26 July 2024")
            case_data["current_status"] = _clean_spacing(well_div.get_text(separator=" ", strip=True))

    # ── Key facts table ──
    key_facts_table = soup.find("table", id="keyFactsTbl")
    if key_facts_table:
        for row in key_facts_table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) == 2:
                raw_key = cols[0].get_text(strip=True)
                # Use separator to preserve spacing between inline elements
                value = _clean_spacing(cols[1].get_text(separator=" ", strip=True))

                # Normalize key names to clean column names
                key = _normalize_key(raw_key)
                if key:
                    case_data[key] = value

    # ── Case number from page ──
    case_number_span = soup.find("span", class_="dsnumber")
    if case_number_span:
        case_data["case_number_raw"] = case_number_span.get_text(strip=True)

    # ── Summary ──
    summary_section = soup.find("h2", id="summary")
    if summary_section:
        summary_parts = []
        for element in summary_section.find_next_siblings():
            if element.name == "h2":
                break  # Stop at next h2 section
            if element.name == "h3":
                summary_parts.append(f"\n{element.get_text(strip=True)}\n")
            elif element.name == "p":
                classes = element.get("class", [])
                if "paranormaltext" in classes:
                    text = _clean_spacing(element.get_text(separator=" ", strip=True))
                    summary_parts.append(text)
                elif not classes:
                    text = _clean_spacing(element.get_text(separator=" ", strip=True))
                    if text:
                        summary_parts.append(text)
                else:
                    break
            elif element.name == "ul":
                for li in element.find_all("li"):
                    summary_parts.append(f"- {_clean_spacing(li.get_text(separator=' ', strip=True))}")

        case_data["summary"] = "\n".join(summary_parts).strip()

    return case_data


def _clean_spacing(text: str) -> str:
    """Fix common spacing issues from HTML text extraction."""
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    # Fix word immediately followed by digit: "on26" → "on 26", "at8" → "at 8"
    # But NOT "DS493" or "Art.2" (letter+digit in identifiers)
    text = re.sub(r"(?<=[a-z])(?=\d)", " ", text)
    # Fix "Art.XVII" → "Art. XVII" (but not "Art.2.1")
    text = re.sub(r"Art\.([A-Z])", r"Art. \1", text)
    return text


def _normalize_key(raw_key: str) -> str:
    """Normalize a key facts table key to a clean column name."""
    # Remove trailing colon
    key = raw_key.rstrip(":")

    # Handle parenthetical qualifiers — extract the base key
    # e.g. "Agreements cited\n(as cited in request for consultations)" → "agreements_cited_consultations"
    # e.g. "Agreements cited\n(as cited in panel request)" → "agreements_cited_panel"
    if "Agreements cited" in key:
        lower = key.lower()
        if "panel request" in lower:
            return "agreements_cited_panel"
        elif "request for consultations" in lower:
            return "agreements_cited_consultations"
        else:
            return "agreements_cited"

    # Handle "Third Parties (original proceedings)" etc.
    if "Third Part" in key:
        lower = key.lower()
        if "original" in lower:
            return "third_parties"
        elif "art 21.5" in lower or "compliance" in lower:
            return "third_parties_compliance"
        else:
            return "third_parties"

    # Keep Art 21.3(c), Art 21.5, Art 22.6, Art 25 keys intact
    if key.startswith("Art "):
        return key

    # Standard key normalization
    # Strip parenthetical at end for simple keys
    if "(" in key:
        key = key.split("(")[0].strip().rstrip(":")

    # Convert to snake_case
    key = key.strip()
    key = re.sub(r"[^a-zA-Z0-9\s]", "", key)
    key = re.sub(r"\s+", "_", key).lower().strip("_")

    return key


# ── Main scraping logic ──────────────────────────────────────

def scrape_all_cases(
    start: int = 1,
    end: int = 640,
    resume: bool = False,
    titles_only: bool = False,
    details_only: bool = False,
    headless: bool = False,
):
    """Scrape WTO case data and save to CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)

    driver = setup_driver(headless=headless)

    try:
        # ── Stage 1: Titles ──
        if not details_only:
            titles = scrape_titles(driver)
            if titles_only:
                driver.quit()
                return
        else:
            # Load existing titles
            if os.path.exists(TITLES_PATH):
                with open(TITLES_PATH, encoding="utf-8") as f:
                    titles = {int(k): v for k, v in json.load(f).items()}
                logger.info("Loaded %d titles from %s", len(titles), TITLES_PATH)
            else:
                titles = {}

        # ── Stage 2: Case details ──
        # Determine case range
        if titles:
            max_case = max(titles.keys())
            end = max(end, max_case)
            logger.info("Max case from titles: DS%d, scraping up to DS%d", max_case, end)

        # Resume support
        completed = set()
        results = []
        if resume and os.path.exists(CHECKPOINT_PATH):
            existing = pd.read_csv(CHECKPOINT_PATH, dtype={"case": str}, encoding="utf-8")
            completed = set(existing["case"].tolist())
            results = existing.to_dict("records")
            logger.info("Resuming: %d cases already scraped", len(completed))

        cases_since_restart = 0

        for case_num in range(start, end + 1):
            case_key = f"DS{case_num}"

            if case_key in completed:
                continue

            logger.info("Scraping DS%d ...", case_num)

            try:
                case_data = parse_case_page(driver, case_num)

                # Add title from status page if available
                if case_num in titles:
                    case_data["title"] = titles[case_num]

                results.append(case_data)
                completed.add(case_key)

            except Exception as e:
                logger.error("Failed DS%d: %s", case_num, e)
                results.append({
                    "case": f"DS{case_num}",
                    "title": titles.get(case_num, ""),
                    "error": str(e),
                })
                completed.add(case_key)

            cases_since_restart += 1
            time.sleep(PAGE_LOAD_WAIT)

            # Checkpoint
            if len(results) % CHECKPOINT_EVERY == 0:
                _save_checkpoint(results)

            # Restart browser periodically to avoid memory leaks
            if cases_since_restart >= RESTART_EVERY:
                logger.info("Restarting browser after %d cases...", RESTART_EVERY)
                driver.quit()
                driver = setup_driver(headless=headless)
                cases_since_restart = 0

        # Final save
        _save_checkpoint(results)
        _save_final(results)

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _save_checkpoint(results: list[dict]):
    """Save intermediate results."""
    if not results:
        return
    df = pd.DataFrame(results)
    df.to_csv(CHECKPOINT_PATH, index=False, encoding="utf-8")
    logger.info("Checkpoint: %d cases saved", len(df))


def _save_final(results: list[dict]):
    """Save final output with cleaned columns."""
    if not results:
        logger.warning("No results to save")
        return

    df = pd.DataFrame(results)

    # Sort by case number
    df["_sort"] = df["case"].str.extract(r"DS(\d+)").astype(int)
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

    # Reorder columns: case, title, core fields first
    priority_cols = [
        "case", "title", "current_status",
        "short_title", "complainant", "respondent",
        "third_parties", "third_parties_compliance",
        "agreements_cited_consultations", "agreements_cited_panel", "agreements_cited",
        "consultations_requested", "panel_requested",
        "mutually_agreed_solution_notified",
        "panel_established", "panel_composed",
        "panel_report_circulated",
        "appellate_body_report_circulated",
        "summary",
    ]
    existing_priority = [c for c in priority_cols if c in df.columns]
    remaining = [c for c in df.columns if c not in existing_priority]
    df = df[existing_priority + remaining]

    # Remove helper columns
    for col in ["case_number_raw", "error"]:
        if col in df.columns and df[col].isna().all():
            df = df.drop(columns=[col])

    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    logger.info("Saved %d cases to %s", len(df), OUTPUT_PATH)
    logger.info("Columns: %s", list(df.columns))

    # Print summary
    has_title = df["title"].notna().sum() if "title" in df.columns else 0
    has_status = df["current_status"].notna().sum() if "current_status" in df.columns else 0
    has_summary = df["summary"].notna().sum() if "summary" in df.columns else 0
    has_complainant = df["complainant"].notna().sum() if "complainant" in df.columns else 0
    logger.info(
        "Coverage — titles: %d, status: %d, complainant: %d, summary: %d",
        has_title, has_status, has_complainant, has_summary,
    )


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape WTO DSB case data")
    parser.add_argument("--start", type=int, default=1, help="First case number (default: 1)")
    parser.add_argument("--end", type=int, default=640, help="Last case number (default: 640)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--titles-only", action="store_true", help="Only scrape status page for titles")
    parser.add_argument("--details-only", action="store_true", help="Skip titles page, scrape case details only")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    args = parser.parse_args()

    scrape_all_cases(
        start=args.start,
        end=args.end,
        resume=args.resume,
        titles_only=args.titles_only,
        details_only=args.details_only,
        headless=args.headless,
    )
