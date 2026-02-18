#!/usr/bin/env python3
"""
Clean the knowledge.jsonl file to remove navigation and other fluff
Keep only medical information, services, prices, doctor info, and appointment info
"""

import json
import re
from pathlib import Path

def clean_content(text):
    """Remove navigation menus, footers, and other non-essential content"""

    # Remove common navigation patterns
    patterns_to_remove = [
        r'Meni E-naročanje Kontakt Lokacija Cenik Dermatologija Ortopedija Urologija Oftalmologija Fizioterapija Kozmetika Optika',
        r'Ljubljanska ulica 89, Maribor E-naročanje info@BETNAVA\.si',
        r'Naše storitve Dermatologija Ortopedija Fizioterapija Oftalmologija Optika Kozmetika Naročanje Kontakt in lokacija Cenik',
        r'Medicinski center Betnava © \d{4} - \d{4} \| Vse pravice pridržane\.',
        r'Partnerji: Medicinski center Betnava d\.o\.o\. Ljubljanska ulica 89, Maribor',
        r'Izkaznica podjetja Splošni pogoji poslovanja Politika zasebnosti Zasebnost in piškotki Videonadzor',
        r'O nas Naši zdravniki Cenik storitev Novice',
        r'E-pošta: Ta e-poštni naslov je zaščiten proti smetenju\. Za ogled potrebujete Javascript, da si jo ogledate\.',
        r'Dermatolog: \d{2} \d{3} \d{2} \d{2} Ortoped: \d{2} \d{3} \d{2} \d{2} Fizioterapija: \d{3} \d{3} \d{3} Okulist: \d{2} \d{3} \d{2} \d{2} Optika Auer: \d{3} \d{3} \d{3} Kozmetični salon Dermavita: \d{3} \d{3} \d{3}',
        r'Zunanje povezave: Športna očala Študenti medicine',
        r'Meni E-naročanje Kontakt Lokacija Cenik',
    ]

    cleaned = text
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Remove repeated navigation sections
    cleaned = re.sub(r'(Dermatologija Ortopedija Fizioterapija Oftalmologija Optika Kozmetika)+', '', cleaned)

    # Remove multiple spaces and newlines
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()

    # Keep contact numbers in a cleaner format
    # Extract important phone numbers
    phone_match = re.search(r'(Dermatolog|Ortoped|Okulist|Fizioterapija):\s*(\d{2,3}\s*\d{3}\s*\d{2,3}\s*\d{2,3})', text)

    return cleaned

def main():
    root = Path(__file__).resolve().parent
    input_file = root / "knowledge.jsonl"
    output_file = root / "knowledge_cleaned.jsonl"

    entries = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            entry = json.loads(line)

            # Clean the content
            original_length = len(entry['text'])
            entry['text'] = clean_content(entry['text'])
            cleaned_length = len(entry['text'])

            # Only keep entries with substantial content
            if cleaned_length > 100:
                entries.append(entry)
                print(f"Cleaned: {entry['metadata']['title']}")
                print(f"  Length: {original_length} -> {cleaned_length} chars")
            else:
                print(f"Skipped (too short): {entry['metadata']['title']}")

    # Write cleaned version
    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in entries:
            json_line = json.dumps(entry, ensure_ascii=False)
            f.write(json_line + '\n')

    print(f"\n✓ Cleaned knowledge base saved to: {output_file}")
    print(f"  Total entries: {len(entries)}")

    total_chars = sum(len(e['text']) for e in entries)
    print(f"  Total characters: {total_chars:,}")
    print(f"  Average entry size: {total_chars // len(entries):,} characters")

if __name__ == "__main__":
    main()
