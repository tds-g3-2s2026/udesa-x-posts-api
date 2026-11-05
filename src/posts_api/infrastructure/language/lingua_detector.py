"""The language of a text, told locally by `lingua` (ADR-024)."""

from lingua import Language, LanguageDetectorBuilder

from posts_api.app.repositories.language_detector import LanguageDetector, PostLanguage

# More than the two the feed filters by: asked to choose only between Spanish
# and English, it calls a French text English with full confidence.
_LANGUAGES = (
    Language.SPANISH,
    Language.ENGLISH,
    Language.PORTUGUESE,
    Language.FRENCH,
    Language.ITALIAN,
    Language.GERMAN,
)

# Below this, the text stays unclassified: a wrong language hides the post from
# whoever reads the other one, and an unclassified one is shown to everybody.
_MINIMUM_CONFIDENCE = 0.6

_FILTERED = {Language.SPANISH: PostLanguage.SPANISH, Language.ENGLISH: PostLanguage.ENGLISH}


class LinguaLanguageDetector(LanguageDetector):
    def __init__(self) -> None:
        # Loaded here and not on the first post, which would pay for it. The
        # low accuracy models are the small ones, and enough for a post's length.
        self._detector = (
            LanguageDetectorBuilder.from_languages(*_LANGUAGES)
            .with_low_accuracy_mode()
            .with_preloaded_language_models()
            .build()
        )

    def detect(self, text: str) -> PostLanguage:
        confidences = self._detector.compute_language_confidence_values(text)
        if not confidences or confidences[0].value < _MINIMUM_CONFIDENCE:
            return PostLanguage.OTHER
        return _FILTERED.get(confidences[0].language, PostLanguage.OTHER)
