from app.services.triage_service import TriageService


def test_bula_maps_to_dermatolog_not_okulist() -> None:
    triage = TriageService()
    result = triage.analyze_symptoms("neko bulo mam... kaki pregled priporočate")

    assert result["recommended_specialist"] == "dermatolog"
    assert "očesne težave" not in result["message"].lower()


def test_generic_priporocate_does_not_trigger_okulist() -> None:
    triage = TriageService()
    result = triage.analyze_symptoms("kaki pregled priporočate")

    assert result["recommended_specialist"] is None


def test_eye_symptoms_still_map_to_okulist() -> None:
    triage = TriageService()
    result = triage.analyze_symptoms("slabo vidim na eno oko")

    assert result["recommended_specialist"] == "okulist"
