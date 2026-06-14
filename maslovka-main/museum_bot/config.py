from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(ROOT_DIR / ".env")


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None

    parsed = int(value)
    return parsed if parsed != 0 else None


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default

    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _path_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    path = Path(raw) if raw else default
    return path if path.is_absolute() else ROOT_DIR / path


@dataclass(frozen=True)
class Settings:
    bot_token: str
    coordinator_chat_id: int | None
    database_path: Path
    faq_seed_path: Path
    match_threshold: float
    local_direct_match_threshold: float
    history_limit: int | None
    auto_close_after_reply: bool
    gemini_api_key: str | None
    gemini_enabled: bool
    gemini_model: str
    gemini_min_confidence: float
    gemini_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()

        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is not set. Create .env from .env.example.")

        history_limit_raw = os.getenv("HISTORY_LIMIT", "0").strip()
        history_limit = int(history_limit_raw) if history_limit_raw else 0
        gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip() or None

        return cls(
            bot_token=token,
            coordinator_chat_id=_optional_int(os.getenv("COORDINATOR_CHAT_ID")),
            database_path=_path_env("DATABASE_PATH", ROOT_DIR / "bot.sqlite3"),
            faq_seed_path=_path_env("FAQ_SEED_PATH", ROOT_DIR / "data" / "faq_seed.json"),
            match_threshold=float(os.getenv("FAQ_MATCH_THRESHOLD", "0.57")),
            local_direct_match_threshold=float(os.getenv("LOCAL_DIRECT_MATCH_THRESHOLD", "0.86")),
            history_limit=history_limit if history_limit > 0 else None,
            auto_close_after_reply=_bool_env("AUTO_CLOSE_AFTER_COORDINATOR_REPLY", True),
            gemini_api_key=gemini_api_key,
            gemini_enabled=_bool_env("GEMINI_ENABLED", gemini_api_key is not None),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip(),
            gemini_min_confidence=float(os.getenv("GEMINI_MIN_CONFIDENCE", "0.70")),
            gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "8")),
        )
