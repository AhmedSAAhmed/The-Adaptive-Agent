"""Runtime settings, read once from the environment (and a local .env when present)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_QUOTES = "\"'“”‘’ "


def _clean(value: str | None) -> str:
    """Strip whitespace and straight/curly quotes that sneak in when keys are pasted."""
    return (value or "").strip().strip(_QUOTES)


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: never overrides variables already set (Render sets them)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), _clean(value))


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


def _database_url() -> str:
    url = _clean(os.getenv("DATABASE_URL"))
    if not url:
        (ROOT / "data").mkdir(exist_ok=True)
        return f"sqlite:///{(ROOT / 'data' / 'adaptive.db').as_posix()}"
    # Render/Heroku style URLs -> SQLAlchemy + psycopg3 driver
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _providers() -> list[Provider]:
    """Ordered failover chain. A provider without a key is skipped."""
    catalog = {
        "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "anthropic/claude-sonnet-5.5"),
        "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-3.5-flash"),
    }
    order = [p.strip() for p in _clean(os.getenv("LLM_CHAIN", "groq,openrouter,gemini")).split(",") if p.strip()]
    chain: list[Provider] = []
    for name in order:
        if name not in catalog:
            continue
        base, key_var, model_var, default_model = catalog[name]
        key = _clean(os.getenv(key_var))
        if key:
            chain.append(Provider(name, base, key, _clean(os.getenv(model_var)) or default_model))
    return chain


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    providers: list[Provider] = field(default_factory=_providers)
    llm_enabled: bool = field(default_factory=lambda: _clean(os.getenv("LLM_ENABLED", "true")).lower() != "false")
    llm_timeout_s: float = field(default_factory=lambda: float(_clean(os.getenv("LLM_TIMEOUT_S", "30")) or 30))
    llm_max_tokens: int = field(default_factory=lambda: int(_clean(os.getenv("LLM_MAX_TOKENS", "1600")) or 1600))
    step_seconds: float = field(default_factory=lambda: float(_clean(os.getenv("STEP_SECONDS", "1.6")) or 1.6))
    webhook_token: str = field(default_factory=lambda: _clean(os.getenv("WEBHOOK_TOKEN")))


load_dotenv()
settings = Settings()
