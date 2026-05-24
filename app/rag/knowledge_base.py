from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

from app.core.llm_client import get_llm_client

BASE_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_PATH = BASE_DIR / "knowledge.jsonl"


@dataclass
class KnowledgeChunk:
    url: str
    title: str
    paragraph: str


IMPORTANT_TERMS = (
    "pregled",
    "poseg",
    "termin",
    "ambulanta",
    "dermatolog",
    "ortoped",
    "okulist",
    "fizioterap",
    "kozmetik",
    "laser",
    "estets",
)


def _split_into_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    for raw in normalized.split("\n"):
        chunk = raw.strip()
        if not chunk:
            continue
        lowered = chunk.lower()
        # kratke vrstice obdržimo, če imajo pomembne izraze (jahanje, bunka, salama …)
        if len(chunk) < 40 and not any(term in lowered for term in IMPORTANT_TERMS):
            continue
        paragraphs.append(chunk)
    return paragraphs


def load_knowledge_chunks() -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    if not KNOWLEDGE_PATH.exists():
        print(f"[knowledge_base] Datoteka {KNOWLEDGE_PATH} ne obstaja. Vračam prazen seznam.")
        return chunks

    with KNOWLEDGE_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = record.get("url", "") or record.get("source", "") or ""
            title = record.get("title", "") or ""
            content = record.get("content", "") or record.get("text", "") or ""
            if not (url or title or content):
                continue
            for paragraph in _split_into_paragraphs(content):
                chunks.append(KnowledgeChunk(url=url, title=title, paragraph=paragraph))

    print(f"[knowledge_base] Naloženih {len(chunks)} odstavkov")
    return chunks


KNOWLEDGE_CHUNKS: List[KnowledgeChunk] = load_knowledge_chunks()

CONTACT = {
    "phone": "",
    "email": "",
}


def _tokenize(text: str) -> Set[str]:
    lowered = text.lower()
    cleaned = re.sub(r"[^\w]+", " ", lowered)
    return {token for token in cleaned.split() if len(token) >= 3}


def _score_chunk(tokens: Set[str], chunk: KnowledgeChunk) -> float:
    paragraph_tokens = _tokenize(chunk.paragraph)
    if not paragraph_tokens:
        return 0.0
    title_tokens = _tokenize(chunk.title)
    overlap_para = len(tokens & paragraph_tokens)
    overlap_title = len(tokens & title_tokens)
    return overlap_para + 0.5 * overlap_title


def _score_chunk_ratio(tokens: Set[str], chunk: KnowledgeChunk, base_len: int) -> float:
    if not tokens or base_len <= 0:
        return 0.0
    paragraph_tokens = _tokenize(chunk.paragraph)
    if not paragraph_tokens:
        return 0.0
    title_tokens = _tokenize(chunk.title)
    overlap_para = len(tokens & paragraph_tokens)
    overlap_title = len(tokens & title_tokens)
    raw = overlap_para + 0.5 * overlap_title
    return raw / max(1.0, float(base_len))


def _expand_query_tokens(query: str, tokens: Set[str]) -> Set[str]:
    lowered = query.lower()
    expanded = set(tokens)
    if "konj" in lowered or "konja" in lowered:
        expanded.update({"poni", "ponij", "ponija", "jahanje"})
    if "jah" in lowered:
        expanded.update({"jahanje", "poni", "ponij", "ponija"})
    return expanded


def search_knowledge_scored(query: str, top_k: int = 3) -> list[tuple[float, KnowledgeChunk]]:
    base_tokens = _tokenize(query)
    tokens = _expand_query_tokens(query, base_tokens)
    base_len = len(base_tokens)
    if not tokens:
        return []
    lowered = query.lower()
    candidates = None
    for patterns in KEYWORD_RULES.values():
        if any(term in lowered for term in patterns):
            candidates = []
            for chunk in KNOWLEDGE_CHUNKS:
                chunk_text = f"{chunk.title.lower()} {chunk.paragraph.lower()} {chunk.url.lower()}"
                if any(term in chunk_text for term in patterns):
                    candidates.append(chunk)
            break
    # Če je vprašanje o jahanju/poniju, preferiraj specifične odstavke
    if any(term in lowered for term in ["jahanje", "jahati", "jahamo", "poni", "ponij", "konj", "konja"]):
        filtered = []
        source = candidates if candidates is not None else KNOWLEDGE_CHUNKS
        for chunk in source:
            chunk_text = f"{chunk.title.lower()} {chunk.paragraph.lower()} {chunk.url.lower()}"
            if "ponij" in chunk_text or "jahanje" in chunk_text:
                filtered.append(chunk)
        if filtered:
            candidates = filtered
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in (candidates if candidates is not None else KNOWLEDGE_CHUNKS):
        score = _score_chunk_ratio(tokens, chunk, base_len)
        if score > 0:
            scored.append((score, chunk))
    if any(term in lowered for term in ["jahanje", "jahati", "jahamo", "poni", "ponij", "konj", "konja"]):
        boosted: list[tuple[float, KnowledgeChunk]] = []
        for score, chunk in scored:
            chunk_text = f"{chunk.title.lower()} {chunk.url.lower()}"
            if "ponij" in chunk_text or "jahanje" in chunk_text:
                score += 1.0
            boosted.append((score, chunk))
        scored = boosted
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:top_k]


def search_knowledge(query: str, top_k: int = 5) -> list[KnowledgeChunk]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    scored: list[tuple[float, KnowledgeChunk]] = []
    for chunk in KNOWLEDGE_CHUNKS:
        score = _score_chunk(tokens, chunk)
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]


KEYWORD_RULES = {
    "salama": ["salama", "salamo", "salame", "klobasa", "klobaso", "mesni izdelki", "klobase"],
    "bunka": ["bunka", "bunko", "bunke", "pohorska bunka"],
    "marmelada": ["marmelada", "marmelado", "marmelade", "marmeldo", "džem", "namaz", "marmelad"],
    "liker": ["liker", "likerje", "žganje", "žganja", "tepkovec"],
    "jahanje": ["jahanje", "jahati", "jahamo", "poni", "ponij", "ponija", "ponijem"],
    "nočitev": ["nočitev", "nočitve", "noči"],
    "kosilo": ["vikend kosilo", "degustacijski", "degustacijo", "kosilo"],
}


def _collect_focus_terms(question: str) -> list[str]:
    lowered = question.lower()
    focus: list[str] = []
    for patterns in KEYWORD_RULES.values():
        if any(term in lowered for term in patterns):
            focus.extend(patterns)
    if not focus:
        focus.extend(IMPORTANT_TERMS)
    return list({term for term in focus if len(term) >= 3})


def _trim_content(content: str, focus_terms: list[str]) -> str:
    if len(content) <= 700:
        return content
    content_lower = content.lower()
    for term in focus_terms:
        idx = content_lower.find(term)
        if idx != -1:
            start = max(0, idx - 200)
            end = min(len(content), idx + 500)
            snippet = content[start:end]
            start_dot = snippet.find(". ")
            if start > 0 and start_dot != -1:
                snippet = snippet[start_dot + 1 :]
            return snippet.strip()
    snippet = content[:700]
    last_dot = snippet.rfind(".")
    if last_dot > 200:
        snippet = snippet[: last_dot + 1]
    return snippet


def _build_context_snippet(question: str, paragraphs: List[KnowledgeChunk]) -> str:
    focus_terms = _collect_focus_terms(question)
    parts: list[str] = []
    for chunk in paragraphs:
        lines: list[str] = []
        if chunk.title:
            lines.append(f"Naslov: {chunk.title}")
        if chunk.url:
            lines.append(f"URL: {chunk.url}")
        content = _trim_content(chunk.paragraph.strip(), focus_terms)
        lines.append(f"Vsebina: {content}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


def _keyword_chunks(question: str, limit: int = 6) -> list[KnowledgeChunk]:
    lowered = question.lower()
    selected: list[KnowledgeChunk] = []
    seen = set()
    for keyword, patterns in KEYWORD_RULES.items():
        if any(term in lowered for term in patterns):
            for chunk in KNOWLEDGE_CHUNKS:
                chunk_text = f"{chunk.title.lower()} {chunk.paragraph.lower()} {chunk.url.lower()}"
                if any(term in chunk_text for term in patterns):
                    key = (chunk.url, chunk.paragraph[:80])
                    if key not in seen:
                        selected.append(chunk)
                        seen.add(key)
                        if len(selected) >= limit:
                            return selected
            if len(selected) >= limit:
                break
    return selected


def _gather_relevant_chunks(question: str, base_top_k: int = 6) -> list[KnowledgeChunk]:
    keyword_chunks = _keyword_chunks(question, limit=4)
    base_chunks = search_knowledge(question, top_k=base_top_k)

    combined: list[KnowledgeChunk] = []
    seen = set()
    for chunk in keyword_chunks + base_chunks:
        key = (chunk.url, chunk.paragraph[:80])
        if key in seen:
            continue
        combined.append(chunk)
        seen.add(key)
        if len(combined) >= base_top_k + len(keyword_chunks):
            break
    return combined


def _filter_chunks_by_category(question: str, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    lowered = question.lower()

    # MR preiskave — prioritiziramo MR vsebino
    if any(word in lowered for word in ["mr ", "mri", "magnetna", "resonanca", "magnetnoresonančna"]):
        filtered = [c for c in chunks if "mr" in c.url.lower() or "magnetnoresonančna" in c.paragraph.lower()]
        if filtered:
            return filtered[:4]

    # UZ preiskave
    if any(word in lowered for word in ["ultrazvok", "ultrazvočn", " uz ", "echografija"]):
        filtered = [c for c in chunks if "ultrazvok" in c.url.lower() or "ultrazvočna" in c.paragraph.lower()]
        if filtered:
            return filtered[:4]

    # ščitnica
    if any(word in lowered for word in ["ščitnica", "ščitnič", "thyroid"]):
        filtered = [c for c in chunks if "scitnica" in c.url.lower() or "ščitnic" in c.paragraph.lower()]
        if filtered:
            return filtered[:4]

    # cenik / cena
    if any(word in lowered for word in ["cen", "cenik", "koliko", "plačam", "stroški"]):
        filtered = [c for c in chunks if "cenik" in c.url.lower() or "cen" in c.paragraph.lower()]
        if filtered:
            return filtered[:4]

    return chunks


SYSTEM_PROMPT = """
Ti si digitalni pomočnik MDT&T d.o.o. — medicinska diagnostika in terapija v Mariboru.
Naslov: Lavričeva ul. 1, 2000 Maribor
Tel (radiološka amb.): 02 23 53 552 / 02 23 53 553 | Email: mr@mdt.si
Tel (ambulanta ščitnica): 02 23 53 555 | Email: scitnica@mdt.si
Delovni čas: vsak dan 08:00–20:00
Storitve: MR (magnetnoresonančna tomografija), RTG (rentgensko slikanje), UZ (ultrazvočna diagnostika — izključno samoplačniško), UZ vodeni posegi, Ambulanta za bolezni ščitnice

PRAVILA:
- Vikaš (vi, vam, vaš)
- Odgovori so kratki, jasni, profesionalni
- Formatiraj v kratke odstavke za lažje branje
- Emoji zmerno (🩻 📋 📞 ✉️ ✅ ⚠️)

⚠️ KRITIČNO — SOURCE VALIDATION:
- Odgovarjaj SAMO na podlagi podanega "Kontekst iz baze znanja"
- Če informacije NI v kontekstu: "Te informacije trenutno nimam. Pokličite nas na 02 23 53 552 ali pišite na mr@mdt.si."
- NE izmišljaj si cen, terminov ali medicinskih informacij

ABSOLUTNA PREPOVED — ZDRAVSTVENI NASVETI:
❌ Bot NE daje zdravstvenih nasvetov, NE interpretira simptomov, NE postavlja diagnoz
❌ Bot NE razlaga izvidov ali rezultatov preiskav
❌ Če nekdo prosi za zdravstveni nasvet ali razlago simptomov, odgovori VEDNO:
"Za zdravstvene nasvete in razlago simptomov se prosimo obrnite na svojega lečečega zdravnika. Jaz vam lahko pomagam z informacijami o naših diagnostičnih preiskavah in z naročanjem."

KLJUČNA PRAVILA MDT&T:
1. Jasno loči dve vrsti naročanja:
   - SAMOPLAČNIŠKO: hitro, brez čakalne dobe, naroči se prek bota (gumb) ali tel. 02 23 53 552
   - NAPOTNICA: prek eZdravje sistema, čakalne dobe 6+ mesecev za MR, napotnico izda lečeči zdravnik.
     Ko omeniš napotnico, VEDNO dodaj oba linka:
     • Čakalne dobe: https://cakalnedobe.ezdrav.si/
     • ZVEM (naročanje z napotnico): https://zvem.ezdrav.si/
2. UZ (ultrazvočna diagnostika) je IZKLJUČNO samoplačniška
3. Ko nekdo omeni srčni spodbujevalnik: "Osebe s srčnim spodbujevalnikom ali defibrilatorjem MR preiskav žal ne morejo opraviti. Prosimo, posvetujte se z vašim zdravnikom."

PRETEKLI DATUMI: Poznaš današnji datum. Če nekdo omeni datum ki je že minil, ga opozori:
"⚠️ Ta datum je že minil. Ste morda mislili drug termin?"
"""


def generate_llm_answer(question: str, top_k: int = 6, history: list[dict[str, str]] | None = None) -> str:
    try:
        paragraphs = _gather_relevant_chunks(question, base_top_k=top_k)
        paragraphs = _filter_chunks_by_category(question, paragraphs)
    except Exception:
        paragraphs = []

    if not paragraphs:
        context_text = (
            "Nimam specifičnih podatkov o tem vprašanju, ampak lahko pomagam z drugimi informacijami o zdravstvenem centru."
        )
    else:
        context_text = _build_context_snippet(question, paragraphs)

    from datetime import datetime
    _DAYS_SL = ["ponedeljek", "torek", "sreda", "četrtek", "petek", "sobota", "nedelja"]
    _now = datetime.now()
    _system = SYSTEM_PROMPT + (
        f"\n\nDanes je {_DAYS_SL[_now.weekday()]}, {_now.strftime('%-d. %-m. %Y')}. "
        f"Jutri je {_DAYS_SL[(_now.weekday()+1)%7]}."
    )
    client = get_llm_client()
    convo: list[dict[str, str]] = [
        {"role": "system", "content": _system},
        {"role": "developer", "content": f"Kontekst iz baze znanja MDT&T:\n{context_text}"},
    ]
    if history:
        convo.extend(history[-6:])
    convo.append({"role": "user", "content": f"Vprašanje pacienta: {question}"})

    response = client.responses.create(
        model="gpt-5-mini",
        input=convo,
        max_output_tokens=400,
        temperature=0.7,
        top_p=0.9,
    )

    answer = getattr(response, "output_text", None)
    if not answer:
        outputs = []
        for block in getattr(response, "output", []) or []:
            for content in getattr(block, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    outputs.append(text)
        answer = "\n".join(outputs).strip()

    return answer or (
        "Te informacije trenutno nimam. Pokličite nas na 02 23 53 552 ali pišite na mr@mdt.si."
    )
