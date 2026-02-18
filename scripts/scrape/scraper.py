#!/usr/bin/env python3
"""Unified knowledge scraper."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests import RequestException


ROOT = Path(__file__).resolve().parents[2]
URLS_FILE = Path(__file__).resolve().parent / "urls.txt"


def load_urls(path: Path) -> list[str]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def replace_center_name(text: str) -> str:
    patterns = [
        r"Zdravstveni\s+center\s+Betnava",
        r"Zdravstvenega\s+centra\s+Betnava",
        r"Zdravstvenemu\s+centru\s+Betnava",
        r"MC\s+Betnava",
        r"mc-betnava",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, "BETNAVA", out, flags=re.IGNORECASE)
    return out


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_page_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text().strip()
        title = re.sub(r"\s*[-|]\s*(MC\s*)?Betnava.*$", "", title, flags=re.IGNORECASE)
        return title.strip() or "Untitled"
    h1 = soup.find("h1")
    if h1:
        return h1.get_text().strip()
    return "Untitled"


def extract_main_content(soup: BeautifulSoup) -> str:
    for element in soup.find_all(["nav", "header", "footer", "script", "style", "iframe", "noscript"]):
        element.decompose()
    for class_name in ["navigation", "menu", "sidebar", "footer", "header", "navbar", "breadcrumb"]:
        for element in soup.find_all(class_=re.compile(class_name, re.I)):
            element.decompose()

    main_content = None
    for selector in ["main", "article", '[role="main"]', ".content", ".main-content", "#content", "#main"]:
        main_content = soup.select_one(selector)
        if main_content:
            break
    if not main_content:
        main_content = soup.find("body")
    if not main_content:
        return ""
    return clean_text(main_content.get_text(separator=" ", strip=True))


def fetch_with_retry(url: str, timeout: int, retries: int, delay: float) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return resp.text
        except RequestException as exc:
            wait = delay * (2 ** (attempt - 1))
            print(f"  [warn] attempt {attempt}/{retries} failed for {url}: {exc}")
            if attempt < retries:
                time.sleep(wait)
    return None


def scrape_url(url: str, timeout: int, retries: int, delay: float) -> dict | None:
    html = fetch_with_retry(url=url, timeout=timeout, retries=retries, delay=delay)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    title = replace_center_name(get_page_title(soup))
    content = replace_center_name(extract_main_content(soup))
    if len(content) < 50:
        return None
    return {"text": content, "metadata": {"source": url, "title": title}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", default=str(URLS_FILE))
    parser.add_argument("--out", default=str(ROOT / "knowledge.jsonl"))
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--mode", choices=["full", "simple", "v2"], default="full")
    args = parser.parse_args()

    urls = sorted(set(load_urls(Path(args.urls))))
    print(f"Scraping {len(urls)} URLs (mode={args.mode})")

    entries: list[dict] = []
    for idx, url in enumerate(urls, start=1):
        print(f"[{idx}/{len(urls)}] {url}")
        item = scrape_url(url, timeout=args.timeout, retries=args.retries, delay=args.sleep)
        if item:
            entries.append(item)
            print(f"  [ok] {item['metadata']['title'][:80]}")
        else:
            print("  [skip] no content")
        time.sleep(args.sleep)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Saved: {out_path} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

