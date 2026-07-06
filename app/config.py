"""Settings loaded from environment variables. Everything has a safe default
so the service runs (and CI passes) with zero external configuration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Optional API-key auth: when set, write endpoints require a matching
    # X-API-Key header. Empty (the default) leaves the service open.
    api_key: str = os.environ.get("API_KEY", "")
    # Request-size guards to keep a single caller from exhausting memory.
    max_text_chars: int = int(os.environ.get("MAX_TEXT_CHARS", "1000000"))
    max_question_chars: int = int(os.environ.get("MAX_QUESTION_CHARS", "2000"))
    max_pdf_bytes: int = int(os.environ.get("MAX_PDF_BYTES", str(20 * 1024 * 1024)))

    @property
    def max_pdf_b64_chars(self) -> int:
        # base64 expands bytes by ~4/3; add slack for padding/newlines.
        return self.max_pdf_bytes * 4 // 3 + 16


settings = Settings()
