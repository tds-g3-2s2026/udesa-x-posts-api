"""What tells the language of a text, without naming the library that does it."""

from abc import ABC, abstractmethod
from enum import StrEnum


class PostLanguage(StrEnum):
    SPANISH = "es"
    ENGLISH = "en"
    # Another language, or a text too short or too ambiguous to tell. The feed
    # shows these to everybody: hiding what could not be classified is worse
    # than showing it.
    OTHER = "other"


class LanguageDetector(ABC):
    @abstractmethod
    def detect(self, text: str) -> PostLanguage:
        """The language of the text, `OTHER` when it cannot be told with confidence."""
