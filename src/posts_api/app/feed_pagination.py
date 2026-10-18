"""An activity cursor distinguishes repeated appearances of the same post."""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from posts_api.app.errors import ProblemError


@dataclass(frozen=True)
class FeedCursor:
    at: datetime
    post_id: uuid.UUID
    kind: int
    actor_id: uuid.UUID

    def encode(self) -> str:
        raw = f"{self.at.isoformat()}|{self.post_id}|{self.kind}|{self.actor_id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @classmethod
    def decode(cls, value: str) -> "FeedCursor":
        try:
            at, post_id, kind, actor_id = (
                base64.b64decode(value, altchars=b"-_", validate=True).decode().split("|")
            )
            result = cls(
                datetime.fromisoformat(at), uuid.UUID(post_id), int(kind), uuid.UUID(actor_id)
            )
            if result.kind not in (0, 1) or result.at.utcoffset() is None:
                raise ValueError("Invalid activity position")
            return result
        except (ValueError, binascii.Error, UnicodeError) as error:
            raise ProblemError(
                status=400,
                code="invalid-cursor",
                title="Cursor inválido",
                detail="El cursor no tiene un formato reconocible",
            ) from error
