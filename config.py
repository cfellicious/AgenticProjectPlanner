from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_config() -> Dict[str, str]:
    return {
        "agent_mode": os.getenv("INSPECTOR_AGENT_MODE", "auto"),
        "allow_mock_fallback": os.getenv("INSPECTOR_ALLOW_MOCK_FALLBACK", "true"),
        "output_dir": os.getenv("INSPECTOR_OUTPUT_DIR", "output"),
        "default_iterations": os.getenv("INSPECTOR_DEFAULT_ITERATIONS", "2"),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-5.4"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"),
        "grok_api_key": os.getenv("GROK_API_KEY", ""),
        "grok_model": os.getenv("GROK_MODEL", "grok-3"),
        "grok_base_url": os.getenv("GROK_BASE_URL", "https://api.x.ai/v1"),
        "http_timeout_seconds": os.getenv("INSPECTOR_HTTP_TIMEOUT_SECONDS", "30"),
        "http_max_retries": os.getenv("INSPECTOR_HTTP_MAX_RETRIES", "2"),
        "http_backoff_seconds": os.getenv("INSPECTOR_HTTP_BACKOFF_SECONDS", "1"),
    }
