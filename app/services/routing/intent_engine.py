import json

from app.core.llm_client import get_llm_client


INTENT_CLASSIFIER_PROMPT = """Si Intent Classifier za MDT&T — medicinsko diagnostičen center v Mariboru. Analiziraj SAMO trenutno sporočilo.

STORITVE:
- mr: magnetnoresonančna tomografija, MR glave, hrbtenice, kolena, sklepov, dojk, prostate
- rtg: rentgen, rentgensko slikanje
- uz: ultrazvok, ultrazvočna diagnostika (izključno samoplačniška)
- uz_posegi: kalcifikacija, kortikosteroid, blokada, ganglionska cista
- scitnica: ščitnica, ščitnična ambulanta

VRNI SAMO JSON (brez markdown):
{"intent": "...", "service": "...", "reason": "..."}

INTENTI:
- "health_advice": uporabnik opisuje simptome/bolečine in potrebuje nasvet
- "booking": uporabnik želi naročiti pregled/termin/naročilo
- "info_narocanje": sprašuje KAJ JE/KAKO POTEKA proces naročanja ("kako se naročim?", "kako poteka naročanje?", "kako rezerviram?")
- "info_services": SAMO splošna vprašanja "kaj nudite" ali "katere storitve imate"
- "info_prices": sprašuje o cenah/ceniku
- "info_contact": sprašuje o lokaciji/kontaktu/naslovu/telefonu
- "info_hours": sprašuje o delovnem času/kdaj ste odprti
- "greeting": pozdrav (zdravo, dober dan, hej)
- "question": SPECIFIČNA vprašanja o storitvah (kdo dela, kakšne izkušnje, kaj vključuje pregled, kakšna je oprema, itd.)

KRITIČNO - RAZLIKUJ MED:
- "info_services" → SAMO "kaj nudite?", "katere storitve imate?", "seznam storitev"
- "info_narocanje" → "kako poteka naročanje?", "kako se naročim?", "kako rezerviram termin?"
- "question" → Specifična vprašanja o storitvah: "kdo dela kot ortoped?", "kaj vključuje pregled?", "kakšna je oprema?", itd.

KRITIČNO - PRAVILA ZA SERVICE:
1. Service vrni SAMO če je storitev EKSPLICITNO omenjena v TRENUTNEM sporočilu
2. Če user reče samo "rad bi se naročil" ali "želim termin" BREZ omembe storitve → service: null
3. NE inferirati storitve iz prejšnjih sporočil ali konteksta!
4. Primeri:
   - "rad bi se naročil na ortopedski pregled" → intent: "booking", service: "ortoped"
   - "rad bi se naročil" → intent: "booking", service: null
   - "kdo dela kot ortoped?" → intent: "question", service: null
   - "kako poteka ortopedski pregled?" → intent: "question", service: null
   - "katere storitve nudite?" → intent: "info_services", service: null
"""


def classify_intent_llm(message: str, history: list = None) -> dict:
    """Use LLM to classify intent - focuses on current message only."""
    prompt = f"""{INTENT_CLASSIFIER_PROMPT}

TRENUTNO SPOROČILO: {message}

JSON:"""

    try:
        client = get_llm_client()
        response = client.responses.create(
            model="gpt-5-mini",
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=100,
            temperature=0.1,
        )

        # Extract response text
        answer = getattr(response, "output_text", None)
        if not answer:
            for block in getattr(response, "output", []) or []:
                for content in getattr(block, "content", []) or []:
                    text = getattr(content, "text", None)
                    if text:
                        answer = text
                        break

        # Parse JSON
        if answer:
            answer = answer.strip()
            if answer.startswith("```"):
                answer = answer.split("```")[1]
                if answer.startswith("json"):
                    answer = answer[4:]
            result = json.loads(answer)
            return result

    except Exception as e:
        print(f"[INTENT_LLM] Error: {e}")

    return {"intent": "other", "service": None, "reason": None}
