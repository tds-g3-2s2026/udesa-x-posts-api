import pytest

from posts_api.app.repositories.language_detector import PostLanguage
from posts_api.infrastructure.language.lingua_detector import LinguaLanguageDetector


@pytest.fixture(scope="module")
def detector():
    return LinguaLanguageDetector()


@pytest.mark.parametrize(
    "text",
    [
        "Hoy fui a la universidad y la clase de ingeniería estuvo muy buena",
        "mañana hay parcial de análisis y no estudié nada",
    ],
)
def test_spanish_is_detected(detector, text):
    assert detector.detect(text) is PostLanguage.SPANISH


@pytest.mark.parametrize(
    "text",
    [
        "I went to the university today and the engineering class was really good",
        "midterm tomorrow and I haven't studied at all",
    ],
)
def test_english_is_detected(detector, text):
    assert detector.detect(text) is PostLanguage.ENGLISH


@pytest.mark.parametrize("text", ["ok", "hola", "hello", "LOL", "😂😂😂", ""])
def test_a_short_or_empty_text_stays_unclassified(detector, text):
    assert detector.detect(text) is PostLanguage.OTHER


@pytest.mark.parametrize(
    "text",
    [
        "Bonjour tout le monde, comment allez-vous aujourd'hui",
        "Guten Morgen, wie geht es dir heute",
        "Bom dia, como você está hoje",
    ],
)
def test_another_language_is_not_forced_into_spanish_or_english(detector, text):
    assert detector.detect(text) is PostLanguage.OTHER
