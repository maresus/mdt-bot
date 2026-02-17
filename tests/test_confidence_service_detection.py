from app.services.routing.confidence import detect_service_type


def test_detect_service_type_bula_is_not_okulist() -> None:
    service = detect_service_type("neko bulo mam na hrbtu")
    assert service != "OKULIST"
    assert service is None


def test_detect_service_type_generic_priporocate_is_none() -> None:
    service = detect_service_type("kaki pregled priporočate")
    assert service is None
