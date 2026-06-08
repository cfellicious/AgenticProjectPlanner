from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List


DEFAULT_MOCK_REVIEWERS = (
    "Software Architect,Security Analyst,Delivery Manager,UI/UX Analyst,DevOps Engineer,Full Stack Engineer,Team Lead"
)
DEFAULT_CONFIG_FILE = "inspector.config.json"
SHARED_PROMPT_FIELDS = (
    "document_goal",
    "global_instruction",
    "input_expectation",
    "severity_scale",
    "reviewer_output_contract",
    "final_output_contract",
)
RUNTIME_PROMPT_COMPOSITION_FIELD = "runtime_prompt_composition"
WORKFLOW_CONFIG_FILES = {
    "new-idea": "inspector.new-idea.config.json",
    "existing-plan": "inspector.existing-plan.config.json",
    "research": "inspector.research.config.json",
    "problem": "inspector.problem.config.json",
}


def default_config_path(workflow: str | None = None) -> Path:
    explicit = os.getenv("INSPECTOR_CONFIG_FILE")
    if explicit:
        return Path(explicit)

    workflow_filename = WORKFLOW_CONFIG_FILES.get(workflow or "")
    if workflow_filename and Path(workflow_filename).exists():
        return Path(workflow_filename)

    return Path(DEFAULT_CONFIG_FILE)


def _read_json_config(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return parsed


def _string_config_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return ""
    return str(value)


def _normalize_provider(provider: str) -> str:
    aliases = {
        "claude": "anthropic",
        "xai": "grok",
        "x.ai": "grok",
        "openai-responses": "openai",
        "chat": "chat_completions",
    }
    normalized = provider.strip().lower()
    return aliases.get(normalized, normalized)


def _is_active_config_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


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


def env_config(workflow: str | None = None, config_file: str | Path | None = None) -> Dict[str, str]:
    config_path = Path(config_file) if config_file is not None else default_config_path(workflow)
    file_config = _read_json_config(config_path)
    config = {
        "agent_mode": _string_config_value(file_config.get("agent_mode", "auto")),
        "allow_mock_fallback": _string_config_value(file_config.get("allow_mock_fallback", "true")),
        "output_dir": _string_config_value(file_config.get("output_dir", "output")),
        "default_iterations": _string_config_value(file_config.get("default_iterations", "2")),
        "reviewers": _string_config_value(file_config.get("reviewers", "")),
        "arbitrator": _string_config_value(file_config.get("arbitrator", "")),
        "research_question_planner": _string_config_value(file_config.get("research_question_planner", "")),
        "dynamic_reviewer_selection": _string_config_value(file_config.get("dynamic_reviewer_selection", "false")),
        "obsidian_idea_file": _string_config_value(file_config.get("obsidian_idea_file", "")),
        "obsidian_max_depth": _string_config_value(file_config.get("obsidian_max_depth", "1")),
        "obsidian_max_notes": _string_config_value(file_config.get("obsidian_max_notes", "12")),
        "mock_reviewers": _string_config_value(file_config.get("mock_reviewers", DEFAULT_MOCK_REVIEWERS)),
        "openai_api_key": _string_config_value(file_config.get("openai_api_key", "")),
        "openai_base_url": _string_config_value(file_config.get("openai_base_url", "https://api.openai.com/v1")),
        "openai_model": _string_config_value(file_config.get("openai_model", "gpt-5.4")),
        "anthropic_api_key": _string_config_value(file_config.get("anthropic_api_key", "")),
        "anthropic_base_url": _string_config_value(file_config.get("anthropic_base_url", "https://api.anthropic.com/v1")),
        "anthropic_model": _string_config_value(file_config.get("anthropic_model", "claude-3-5-haiku-20241022")),
        "grok_api_key": _string_config_value(file_config.get("grok_api_key", "")),
        "grok_model": _string_config_value(file_config.get("grok_model", "grok-3")),
        "grok_base_url": _string_config_value(file_config.get("grok_base_url", "https://api.x.ai/v1")),
        "http_timeout_seconds": _string_config_value(file_config.get("http_timeout_seconds", "30")),
        "http_max_retries": _string_config_value(file_config.get("http_max_retries", "2")),
        "http_backoff_seconds": _string_config_value(file_config.get("http_backoff_seconds", "1")),
    }
    for field in SHARED_PROMPT_FIELDS:
        config[field] = _string_config_value(file_config.get(field, ""))
    config[RUNTIME_PROMPT_COMPOSITION_FIELD] = _string_config_value(file_config.get(RUNTIME_PROMPT_COMPOSITION_FIELD, ""))
    env_overrides = {
        "agent_mode": os.getenv("INSPECTOR_AGENT_MODE"),
        "allow_mock_fallback": os.getenv("INSPECTOR_ALLOW_MOCK_FALLBACK"),
        "output_dir": os.getenv("INSPECTOR_OUTPUT_DIR"),
        "default_iterations": os.getenv("INSPECTOR_DEFAULT_ITERATIONS"),
        "reviewers": os.getenv("INSPECTOR_REVIEWERS"),
        "arbitrator": os.getenv("INSPECTOR_ARBITRATOR"),
        "research_question_planner": os.getenv("INSPECTOR_RESEARCH_QUESTION_PLANNER"),
        "dynamic_reviewer_selection": os.getenv("INSPECTOR_DYNAMIC_REVIEWER_SELECTION"),
        "obsidian_idea_file": os.getenv("INSPECTOR_OBSIDIAN_IDEA_FILE"),
        "obsidian_max_depth": os.getenv("INSPECTOR_OBSIDIAN_MAX_DEPTH"),
        "obsidian_max_notes": os.getenv("INSPECTOR_OBSIDIAN_MAX_NOTES"),
        "mock_reviewers": os.getenv("INSPECTOR_MOCK_REVIEWERS"),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "openai_base_url": os.getenv("OPENAI_BASE_URL"),
        "openai_model": os.getenv("OPENAI_MODEL"),
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"),
        "anthropic_base_url": os.getenv("ANTHROPIC_BASE_URL"),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL"),
        "grok_api_key": os.getenv("GROK_API_KEY"),
        "grok_model": os.getenv("GROK_MODEL"),
        "grok_base_url": os.getenv("GROK_BASE_URL"),
        "http_timeout_seconds": os.getenv("INSPECTOR_HTTP_TIMEOUT_SECONDS"),
        "http_max_retries": os.getenv("INSPECTOR_HTTP_MAX_RETRIES"),
        "http_backoff_seconds": os.getenv("INSPECTOR_HTTP_BACKOFF_SECONDS"),
    }
    for key, value in env_overrides.items():
        if value is not None:
            config[key] = value
    return config


def mock_reviewer_names(config: Dict[str, str]) -> List[str]:
    names = [name.strip() for name in config.get("mock_reviewers", DEFAULT_MOCK_REVIEWERS).split(",")]
    return [name for name in names if name]


def configured_reviewer_catalog_specs(config: Dict[str, str]) -> List[Dict[str, str]]:
    raw = config.get("reviewers", "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"INSPECTOR_REVIEWERS must be valid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError("INSPECTOR_REVIEWERS must be a JSON array.")

    specs: List[Dict[str, str]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"INSPECTOR_REVIEWERS item {index} must be an object.")
        spec = {str(key): str(value) for key, value in item.items() if value is not None}
        provider = _normalize_provider(spec.get("provider", ""))
        if not provider:
            raise ValueError(f"INSPECTOR_REVIEWERS item {index} is missing provider.")
        spec["provider"] = provider
        spec.setdefault("name", f"{provider}-{index}")
        specs.append(spec)
    return specs


def configured_reviewer_specs(config: Dict[str, str]) -> List[Dict[str, str]]:
    if not config.get("reviewers", "").strip():
        return []
    specs = [
        spec
        for spec in configured_reviewer_catalog_specs(config)
        if _is_active_config_value(spec.get("active", True))
    ]
    if not specs:
        raise ValueError("at least one reviewer must be configured.")
    return specs


def configured_arbitrator_spec(config: Dict[str, str]) -> Dict[str, str]:
    raw = config.get("arbitrator", "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arbitrator config must be valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("arbitrator config must be a JSON object.")

    spec = {str(key): str(value) for key, value in parsed.items() if value is not None}
    provider = _normalize_provider(spec.get("provider", ""))
    if not provider:
        raise ValueError("arbitrator config is missing provider.")
    spec["provider"] = provider
    spec.setdefault("name", "Arbitrator")
    return spec
