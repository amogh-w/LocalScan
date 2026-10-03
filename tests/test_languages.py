"""The scan languages (one or more) and the translation language are chosen in Settings and applied everywhere."""
import pytest
from fastapi import HTTPException

from app import jobs, languages
from app.api import settings as settings_api
from app.config import settings
from app.ocr.registry import get_ocr


@pytest.fixture(autouse=True)
def restore_settings(monkeypatch):
    before = dict(settings._overrides)
    settings._overrides = {}  # not the languages saved on this machine
    monkeypatch.setattr(settings, "update", lambda patch: settings._overrides.update(patch))
    yield
    settings._overrides = before


def save(**fields):
    return settings_api.put_settings(settings_api.SettingsPatch(**fields))


def test_defaults_are_german_to_english():
    assert languages.scan_names() == "German" and languages.target_language().name == "English"


def test_several_scan_languages_become_one_phrase_for_the_prompts():
    out = save(scan_languages=["de", "en"], translate_to="en")
    assert out["scan_languages"] == ["de", "en"] and languages.scan_names() == "German and English"
    assert save(scan_languages=["en"], translate_to="de")["scan_languages"] == ["en"]


def test_invalid_choices_are_rejected():
    for bad in (dict(scan_languages=[]), dict(scan_languages=["xx"]), dict(scan_languages=["en"], translate_to="en")):
        with pytest.raises(HTTPException) as e:
            save(**bad)
        assert e.value.status_code == 400


def test_the_older_single_code_setting_still_works():
    settings._overrides["languages"] = {"scan": "en", "translate_to": "de"}
    assert languages.scan_names() == "English"


def test_a_new_language_is_one_registry_entry(monkeypatch):
    monkeypatch.setitem(languages.LANGUAGES, "fr", languages.Language("fr", "French", "Français", ocr="fr"))
    page = {"original": "x", "corners": [], "rotation": 0, "filter": "enhanced"}
    settings._overrides["languages"] = {"scan": ["fr"], "translate_to": "en"}
    assert get_ocr().lang == "fr"  # one scan language with its own model selects it
    french = jobs.clean_key(page)
    settings._overrides["languages"] = {"scan": ["fr", "de"], "translate_to": "en"}
    assert get_ocr().lang == ""  # several languages use the default model
    settings._overrides["languages"] = {"scan": ["de"], "translate_to": "en"}
    assert jobs.clean_key(page) != french  # a different OCR model must not reuse cached text
