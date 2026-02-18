#!/usr/bin/env python3
"""
Clean the knowledge.jsonl file to remove only the most common navigation elements
Keep medical information, services, prices, doctor info, and appointment info
"""

import json
import re
from pathlib import Path

def clean_content(text, title):
    """Remove only the most repetitive navigation menus and footers"""

    # Remove only the most common repeated navigation at the start
    # This appears at the beginning of most pages
    text = re.sub(r'^Meni E-naročanje Kontakt Lokacija Cenik Dermatologija Ortopedija Urologija Oftalmologija Fizioterapija Kozmetika Optika\s+', '', text)
    text = re.sub(r'^Ljubljanska ulica 89, Maribor E-naročanje info@BETNAVA\.si\s+', '', text)
    text = re.sub(r'^Naše storitve Dermatologija Ortopedija Fizioterapija Oftalmologija Optika Kozmetika Naročanje Kontakt in lokacija Cenik\s+', '', text)

    # Remove footer copyright and links at the end
    text = re.sub(r'Medicinski center Betnava © \d{4} - \d{4} \| Vse pravice pridržane\..*?$', '', text, flags=re.DOTALL)
    text = re.sub(r'Partnerji: Medicinski center Betnava d\.o\.o\..*?$', '', text, flags=re.DOTALL)

    # Remove the external links section at the end
    text = re.sub(r'Zunanje povezave: Športna očala Študenti medicine.*?$', '', text)

    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()

    return text

def main():
    root = Path(__file__).resolve().parent
    input_file = root / "knowledge.jsonl"
    output_file = root / "knowledge_final.jsonl"

    entries = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)

            # Clean the content
            original_length = len(entry['text'])
            entry['text'] = clean_content(entry['text'], entry['metadata']['title'])
            cleaned_length = len(entry['text'])

            entries.append(entry)
            reduction = original_length - cleaned_length
            print(f"✓ {entry['metadata']['title'][:60]}")
            print(f"  {original_length} -> {cleaned_length} chars (removed {reduction})")

    # Write cleaned version
    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in entries:
            json_line = json.dumps(entry, ensure_ascii=False)
            f.write(json_line + '\n')

    print(f"\n{'='*80}")
    print(f"✓ Knowledge base saved to: {output_file}")
    print(f"  Total entries: {len(entries)}")

    total_chars = sum(len(e['text']) for e in entries)
    print(f"  Total characters: {total_chars:,}")
    print(f"  Average entry size: {total_chars // len(entries):,} characters")

if __name__ == "__main__":
    main()
