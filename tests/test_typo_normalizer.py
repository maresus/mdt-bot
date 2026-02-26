from app.services.routing.message_normalizer import normalize_user_message


def test_normalizer_maps_greeting_typo():
    assert normalize_user_message("zdwavo") == "zdravo"


def test_normalizer_maps_service_typos_and_slang():
    msg = "mate dermatologo pa kolk stane botoc"
    out = normalize_user_message(msg)
    assert "imate" in out
    assert "dermatolog" in out
    assert "koliko" in out
    assert "botox" in out

