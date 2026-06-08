#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from agents import (
    AgentResult,
    AnthropicConsolidator,
    AnthropicReviewer,
    DEFAULT_REVIEWER_PERSONAS,
    GrokConsolidator,
    GrokReviewer,
    MockAgent,
    MockConsolidator,
    OpenAIConsolidator,
    OpenAIReviewer,
    RetryConfig,
    _post_json,
)
from config import (
    RUNTIME_PROMPT_COMPOSITION_FIELD,
    SHARED_PROMPT_FIELDS,
    configured_arbitrator_spec,
    configured_reviewer_catalog_specs,
    configured_reviewer_specs,
    default_config_path,
    env_config,
    load_dotenv,
    mock_reviewer_names,
)
from obsidian import collect_obsidian_context, render_obsidian_context
from planner import (
    DynamicQuestion,
    append_review_clarifications,
    build_initial_plan,
    build_initial_problem_plan,
    build_initial_research_plan,
    detail_follow_up_for,
    display_question_for_user,
    follow_up_for,
    generate_review_follow_up_questions,
    generate_questions,
    generate_problem_questions,
    generate_research_questions,
    guidance_for,
    merge_research_questions,
    needs_detail_for_question,
    normalize_dynamic_research_questions,
    product_name_from_answers,
    problem_name_from_answers,
    research_project_name_from_answers,
    should_ask_follow_up,
    slugify,
    user_knowledge_level,
    wants_agent_guidance,
)


def prompt_user(question: str) -> str:
    print(f"\n{question}")
    answer = input("> ").strip()
    return answer or "Not specified"


FINAL_DISCOVERY_CONTEXT_QUESTION = (
    "Before I generate the initial plan, is there any extra context, correction, constraint, "
    "pain point, or decision you want the reviewers and arbitrator to know?"
)


def resolve_answer(idea: str, question: str, answer: str) -> str:
    if not wants_agent_guidance(answer):
        return answer

    guidance = guidance_for(question, idea)
    if guidance is None:
        return answer

    print(f"\n{guidance}")
    confirmation = input("Use this recommendation? Press Enter for yes, or type your override.\n> ").strip()
    if confirmation:
        return confirmation
    return guidance


def collect_final_discovery_context(subject: str, answers: Dict[str, str]) -> None:
    answer = prompt_user(FINAL_DISCOVERY_CONTEXT_QUESTION)
    resolved = resolve_answer(subject, FINAL_DISCOVERY_CONTEXT_QUESTION, answer)
    if should_ask_follow_up(resolved):
        return
    answers[FINAL_DISCOVERY_CONTEXT_QUESTION] = resolved


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return default
    return max(parsed, minimum)


@dataclass(frozen=True)
class RelatedPlanContext:
    path: Path
    versions: List[str]
    headings: List[str]
    notable_lines: List[str]


VERSION_PATTERNS = (
    re.compile(r"(?i)\bversion\s*[:#-]?\s*(\d+(?:\.\d+){1,3})"),
    re.compile(r"(?i)v\.?(\d+(?:\.\d+){1,3})"),
)
NOTEWORTHY_CONTEXT_MARKERS = (
    "risk",
    "concern",
    "flaw",
    "security",
    "performance",
    "edge",
    "test",
    "decision",
    "migration",
    "rollback",
    "scope",
    "defer",
    "supersede",
    "version",
    "idor",
    "bola",
)
NEGATIVE_SECTION_MARKERS = (
    "risk",
    "risks",
    "concern",
    "concerns",
    "flaw",
    "flaws",
    "issue",
    "issues",
    "performance",
    "security",
    "edge",
    "failure",
    "failures",
    "testing required",
    "specific testing",
    "test coverage",
    "future",
    "open",
    "go/no-go",
    "launch gate",
    "blocked",
    "rollback",
    "reliability",
    "privacy",
)
NEGATIVE_LINE_MARKERS = (
    "risk",
    "concern",
    "flaw",
    "issue",
    "missing",
    "blocked",
    "reject",
    "deny",
    "fail",
    "failure",
    "revoked",
    "expired",
    "superseded",
    "capacity",
    "conflict",
    "leak",
    "idor",
    "bola",
    "security",
    "performance",
    "latency",
    "p95",
    "p99",
    "edge",
    "test",
    "future",
    "defer",
    "rollback",
    "open concern",
)


def _extract_versions(text: str, filename: str = "") -> List[str]:
    searchable = f" {filename}\n{text}"
    candidates: List[str] = []
    for pattern in VERSION_PATTERNS:
        candidates.extend(pattern.findall(searchable))
    seen: set[str] = set()
    versions: List[str] = []
    for candidate in candidates:
        normalized = candidate.strip(".")
        if normalized in seen:
            continue
        seen.add(normalized)
        versions.append(normalized)
    return versions


def _topic_tokens(plan_path: Path) -> set[str]:
    source = plan_path.stem
    generic_stems = {"final_plan", "initial_plan", "implementation_plan", "plan"}
    if plan_path.stem.lower() in generic_stems:
        source = f"{plan_path.parent.name} {plan_path.stem}"
    tokens = re.findall(r"[a-z0-9]+", source.lower())
    ignored = {
        "final",
        "initial",
        "plan",
        "implementation",
        "architect",
        "review",
        "output",
        "md",
        "v",
    }
    return {token for token in tokens if len(token) >= 4 and token not in ignored}


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _collect_related_plan_context(plan_path: Path, current_plan: str, max_files: int = 8) -> List[RelatedPlanContext]:
    versions = set(_extract_versions(current_plan, plan_path.name))
    tokens = _topic_tokens(plan_path)
    search_roots = _dedupe_paths([plan_path.parent, Path("plans"), Path("details")])
    candidates: List[tuple[int, Path, str, List[str]]] = []

    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for candidate in root.rglob("*.md"):
            if candidate.resolve() == plan_path.resolve():
                continue
            text = _read_text_safe(candidate)
            candidate_versions = _extract_versions(text, candidate.name)
            candidate_tokens = _topic_tokens(candidate)
            version_overlap = bool(versions and set(candidate_versions).intersection(versions))
            topic_overlap = len(tokens.intersection(candidate_tokens))
            required_topic_overlap = 1 if len(tokens) <= 2 else 2
            if not version_overlap and topic_overlap < required_topic_overlap:
                continue
            score = (10 if version_overlap else 0) + topic_overlap
            candidates.append((score, candidate, text, candidate_versions))

    candidates.sort(key=lambda item: (-item[0], str(item[1])))
    contexts: List[RelatedPlanContext] = []
    for _score, path, text, candidate_versions in candidates[:max_files]:
        headings = [
            line.strip()
            for line in text.splitlines()
            if line.lstrip().startswith("#")
        ][:18]
        notable_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
            and any(marker in line.lower() for marker in NOTEWORTHY_CONTEXT_MARKERS)
        ][:30]
        contexts.append(
            RelatedPlanContext(
                path=path,
                versions=candidate_versions,
                headings=headings,
                notable_lines=notable_lines,
            )
        )
    return contexts


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: set[Path] = set()
    deduped: List[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _render_version_context(plan_path: Path, current_plan: str, contexts: List[RelatedPlanContext]) -> str:
    current_versions = _extract_versions(current_plan, plan_path.name)
    lines = [
        "# Related Version Context",
        "",
        f"- Source plan: {plan_path}",
        f"- Detected source versions: {', '.join(current_versions) if current_versions else 'None detected'}",
        f"- Related files found: {len(contexts)}",
        "",
    ]
    if not contexts:
        lines.append("- No related version/topic files were found in the searched directories.")
        return "\n".join(lines).strip() + "\n"

    lines.extend(
        [
            "Use this context to understand how decisions, risks, constraints, and implementation direction progressed across related documents.",
            "Do not blindly copy older decisions; reconcile them against the source plan and preserve useful deltas as concerns or implementation guidance.",
            "",
        ]
    )
    for index, context in enumerate(contexts, start=1):
        lines.append(f"## Related File {index}: {context.path}")
        lines.append(f"- Detected versions: {', '.join(context.versions) if context.versions else 'None detected'}")
        lines.append("- Headings:")
        if context.headings:
            for heading in context.headings:
                lines.append(f"  - {heading}")
        else:
            lines.append("  - None found.")
        lines.append("- Notable risk/decision/progression lines:")
        if context.notable_lines:
            for notable in context.notable_lines:
                lines.append(f"  - {notable[:260]}")
        else:
            lines.append("  - None found.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _heading_level(line: str) -> int:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return 0
    return len(stripped) - len(stripped.lstrip("#"))


def _heading_title(line: str) -> str:
    return line.lstrip("#").strip()


def _is_negative_heading(title: str) -> bool:
    normalized = title.lower()
    return any(marker in normalized for marker in NEGATIVE_SECTION_MARKERS)


def _extract_negative_sections(plan_md: str) -> List[str]:
    lines = plan_md.splitlines()
    sections: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        level = _heading_level(line)
        if level == 0 or not _is_negative_heading(_heading_title(line)):
            index += 1
            continue

        section_lines = [line.rstrip()]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            next_level = _heading_level(next_line)
            if next_level and next_level <= level:
                break
            section_lines.append(next_line.rstrip())
            index += 1
        content = "\n".join(section_lines).strip()
        if content:
            sections.append(content)

    return sections


def _extract_negative_lines(plan_md: str, limit: int = 80) -> List[str]:
    selected: List[str] = []
    seen: set[str] = set()
    for raw_line in plan_md.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if not any(marker in lowered for marker in NEGATIVE_LINE_MARKERS):
            continue
        cleaned = line[:300]
        if cleaned in seen:
            continue
        seen.add(cleaned)
        selected.append(cleaned)
        if len(selected) >= limit:
            break
    return selected


def build_negative_reference(plan_md: str, product_name: str, source_artifact: Path) -> str:
    sections = _extract_negative_sections(plan_md)
    fallback_lines = _extract_negative_lines(plan_md)
    lines = [
        f"# Negative Reference: {product_name}",
        "",
        f"- Source artifact: {source_artifact}",
        f"- Generated at: {dt.datetime.now(dt.UTC).isoformat()}",
        "",
        "This file consolidates the plan's negative and risk-oriented material for quick reference: risks, concerns, flaws, performance issues, future concerns, edge cases, open issues, blocked states, and risk-driven tests.",
        "",
    ]

    if sections:
        lines.append("## Extracted Negative Sections")
        lines.append("")
        for section in sections:
            lines.append(section)
            lines.append("")
    else:
        lines.append("## Extracted Negative Sections")
        lines.append("")
        lines.append("- No dedicated negative/risk sections were found by heading.")
        lines.append("")

    lines.append("## Negative Signal Index")
    lines.append("")
    if fallback_lines:
        for item in fallback_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- No additional negative-signal lines were found.")
    lines.append("")

    lines.append("## Review Reminder")
    lines.append("")
    lines.append("- Treat this file as a reference index. The final implementation plan remains the source of truth.")
    lines.append("- Before launch, every item here should be resolved, accepted as an explicit launch assumption, assigned an owner, or converted into a testable gate.")
    return "\n".join(lines).strip() + "\n"


def _api_key_for_spec(spec: Dict[str, str], config: Dict[str, str]) -> str:
    if "api_key" in spec:
        return spec["api_key"]
    api_key_env = spec.get("api_key_env", "").strip()
    if api_key_env:
        return os.getenv(api_key_env, "")

    provider = spec["provider"]
    if provider == "anthropic":
        return config["anthropic_api_key"]
    if provider in {"openai", "responses"}:
        return config["openai_api_key"]
    if provider in {"grok", "openai_chat", "chat_completions"}:
        return config["grok_api_key"] or config["openai_api_key"]
    return ""


def _provider_defaults(provider: str, config: Dict[str, str]) -> tuple[str, str]:
    if provider == "anthropic":
        return config["anthropic_model"], config["anthropic_base_url"]
    if provider in {"openai", "responses"}:
        return config["openai_model"], config["openai_base_url"]
    if provider in {"grok", "openai_chat", "chat_completions"}:
        return config["grok_model"], config["grok_base_url"]
    return "", ""


def _model_for_spec(spec: Dict[str, str], default_model: str) -> str:
    model_env = spec.get("model_env", "").strip()
    if model_env:
        env_model = os.getenv(model_env, "").strip()
        if env_model:
            return env_model
    return spec.get("model", default_model)


def _configured_research_question_planner_spec(config: Dict[str, str]) -> Dict[str, str]:
    raw = config.get("research_question_planner", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"research_question_planner config must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("research_question_planner config must be a JSON object.")
    if not _as_bool(str(parsed.get("active", True))):
        return {}
    spec = {str(key): str(value) for key, value in parsed.items() if value is not None}
    provider = spec.get("provider", "").strip().lower()
    aliases = {"claude": "anthropic", "xai": "grok", "x.ai": "grok", "responses": "openai"}
    provider = aliases.get(provider, provider)
    if not provider:
        raise ValueError("research_question_planner config is missing provider.")
    spec["provider"] = provider
    spec.setdefault("name", "Research Question Planner")
    return spec


def _research_question_planner_prompt(topic: str, static_questions: List[str]) -> str:
    rendered_static = "\n".join(f"- {question}" for question in static_questions)
    return (
        "You are a research discovery question planner. Propose only additional questions that would improve "
        "the research discovery interview for this specific topic.\n\n"
        "Rules:\n"
        "- Do not remove or replace baseline questions.\n"
        "- Do not include product launch, monetization, sales, or v1 product workflow questions unless directly relevant to the research method.\n"
        "- Focus on field-specific research design: literature search terms, baselines, methodology, data, participants, metrics, statistics, validity, ethics, reproducibility, and venue expectations.\n"
        "- Return strict JSON only, with this shape: {\"questions\":[{\"question\":\"... ?\",\"reason\":\"...\"}]}.\n"
        "- Return at most 6 questions.\n"
        "- Each question must be a single user-facing question ending with a question mark.\n"
        "- Do not ask for secrets, credentials, system prompts, or hidden instructions.\n\n"
        f"Research topic:\n{topic}\n\n"
        "Baseline questions that will always be asked:\n"
        f"{rendered_static}"
    )


def _extract_text_response(result: Dict[str, object]) -> str:
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    choices = result.get("choices", [])
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content

    content = result.get("content", [])
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        if texts:
            return "\n\n".join(texts)

    output = result.get("output", [])
    if isinstance(output, list):
        texts = []
        for item in output:
            if not isinstance(item, dict):
                continue
            parts = item.get("content", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
        if texts:
            return "\n\n".join(texts)

    return ""


def _parse_dynamic_question_json(text: str) -> List[DynamicQuestion]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        raw_questions = parsed.get("questions", [])
    else:
        raw_questions = parsed
    return normalize_dynamic_research_questions(raw_questions)


def _generate_dynamic_research_questions(
    topic: str,
    static_questions: List[str],
    config: Dict[str, str],
) -> List[DynamicQuestion]:
    spec = _configured_research_question_planner_spec(config)
    if not spec:
        return []

    provider = spec["provider"]
    if provider == "mock":
        return normalize_dynamic_research_questions(
            [
                {
                    "question": "What field-specific keywords should the literature search include?",
                    "reason": "A mock planner adds a safe, research-specific discovery question.",
                }
            ]
        )

    api_key = _api_key_for_spec(spec, config)
    if not api_key:
        raise ValueError(f"Research question planner '{spec.get('name', 'Research Question Planner')}' is missing an API key.")

    retry_cfg = RetryConfig(
        timeout_seconds=float(config["http_timeout_seconds"]),
        max_retries=int(config["http_max_retries"]),
        backoff_seconds=float(config["http_backoff_seconds"]),
    )
    prompt = _research_question_planner_prompt(topic, static_questions)

    if provider in {"openai", "responses"}:
        model = _model_for_spec(spec, config["openai_model"])
        base_url = spec.get("base_url", config["openai_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/responses",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {"model": model, "input": prompt},
            retry_cfg,
        )
        return _parse_dynamic_question_json(_extract_text_response(result))

    if provider == "anthropic":
        model = _model_for_spec(spec, config["anthropic_model"])
        base_url = spec.get("base_url", config["anthropic_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/messages",
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {"model": model, "max_tokens": 900, "messages": [{"role": "user", "content": prompt}]},
            retry_cfg,
        )
        return _parse_dynamic_question_json(_extract_text_response(result))

    if provider in {"grok", "openai_chat", "chat_completions"}:
        model = _model_for_spec(spec, config["grok_model"])
        base_url = spec.get("base_url", config["grok_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            retry_cfg,
        )
        return _parse_dynamic_question_json(_extract_text_response(result))

    raise ValueError(
        f"Research question planner uses unsupported provider '{provider}'. "
        "Supported providers: mock, openai, responses, anthropic, grok, openai_chat, chat_completions."
    )


def _render_research_questions_artifact(
    static_questions: List[str],
    dynamic_questions: List[DynamicQuestion],
    final_questions: List[str],
    error: str = "",
) -> str:
    lines = [
        "# Research Discovery Questions",
        "",
        "## Static Baseline Questions",
    ]
    for question in static_questions:
        lines.append(f"- {question}")

    lines.extend(["", "## Agent-Proposed Additions"])
    if dynamic_questions:
        for item in dynamic_questions:
            suffix = f" Reason: {item.reason}" if item.reason else ""
            lines.append(f"- {item.question}{suffix}")
    else:
        lines.append("- None.")

    if error:
        lines.extend(["", "## Planner Error", f"- {error}"])

    lines.extend(["", "## Final Questions Asked"])
    for question in final_questions:
        lines.append(f"- {question}")
    return "\n".join(lines).strip() + "\n"


def _append_discovery_questions_context(
    plan_md: str,
    static_questions: List[str],
    dynamic_questions: List[DynamicQuestion],
) -> str:
    lines = [
        "",
        "## Research Discovery Questions Used",
        "- Static baseline questions were mandatory and could not be removed by the question planner.",
        "- Agent-proposed questions were validated, deduplicated, and appended only if safe.",
        "",
        "### Static Baseline",
    ]
    for question in static_questions:
        lines.append(f"- {question}")

    lines.extend(["", "### Agent-Proposed Additions"])
    if dynamic_questions:
        for item in dynamic_questions:
            suffix = f" Reason: {item.reason}" if item.reason else ""
            lines.append(f"- {item.question}{suffix}")
    else:
        lines.append("- None.")

    return plan_md.rstrip() + "\n" + "\n".join(lines) + "\n"


def _format_shared_prompt_value(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return json.dumps(parsed, indent=2)


def _shared_prompt_context(config: Dict[str, str]) -> str:
    sections: List[str] = []
    for field in SHARED_PROMPT_FIELDS:
        value = config.get(field, "").strip()
        if not value:
            continue
        heading = field.replace("_", " ").title()
        sections.append(f"## {heading}\n{_format_shared_prompt_value(value)}")
    if not sections:
        return ""
    return "# Shared Review Configuration\n" + "\n\n".join(sections)


def _runtime_prompt_composition_context(config: Dict[str, str], agent_type: str) -> str:
    raw = config.get(RUNTIME_PROMPT_COMPOSITION_FIELD, "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{RUNTIME_PROMPT_COMPOSITION_FIELD} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{RUNTIME_PROMPT_COMPOSITION_FIELD} must be a JSON object.")

    field = f"{agent_type}_runtime_instructions"
    instructions = parsed.get(field, "")
    if not instructions:
        return ""
    heading = field.replace("_", " ").title()
    if isinstance(instructions, list):
        rendered = "\n".join(f"- {item}" for item in instructions if str(item).strip())
    elif isinstance(instructions, dict):
        rendered = json.dumps(instructions, indent=2)
    else:
        rendered = str(instructions).strip()
    if not rendered:
        return ""
    return f"# Runtime Prompt Composition\n## {heading}\n{rendered}"


def _compose_agent_prompt(role_prompt: str, shared_context: str, runtime_context: str = "") -> str:
    role_prompt = role_prompt.strip()
    shared_context = shared_context.strip()
    runtime_context = runtime_context.strip()
    sections = [section for section in [shared_context, runtime_context] if section]
    if not sections:
        return role_prompt
    if role_prompt:
        sections.append(f"# Role-Specific Prompt\n{role_prompt}")
    return "\n\n".join(sections)


def _reviewer_config_context(spec: Dict[str, str]) -> str:
    lines: List[str] = []
    category = spec.get("category", "").strip()
    if category:
        lines.append(f"- Category: {category}")
    activate_when = spec.get("activate_when", "").strip()
    if activate_when:
        lines.append(f"- Activate when: {activate_when}")
    if not lines:
        return ""
    return "# Reviewer Configuration\n" + "\n".join(lines)


def _build_configured_reviewer(
    spec: Dict[str, str],
    config: Dict[str, str],
    retry_cfg: RetryConfig,
    shared_context: str = "",
    runtime_context: str = "",
):
    provider = spec["provider"]
    name = spec.get("name", provider)
    reviewer_context = _reviewer_config_context(spec)
    role_prompt = "\n\n".join(
        part for part in [reviewer_context, spec.get("prompt", spec.get("persona", "")).strip()] if part
    )
    persona_prompt = _compose_agent_prompt(role_prompt, shared_context, runtime_context)

    if provider == "mock":
        return MockAgent(name, persona_prompt)

    api_key = _api_key_for_spec(spec, config)
    if not api_key:
        raise ValueError(f"Reviewer '{name}' is missing an API key.")

    if provider in {"openai", "responses"}:
        return OpenAIReviewer(
            api_key,
            _model_for_spec(spec, config["openai_model"]),
            retry_cfg,
            spec.get("base_url", config["openai_base_url"]),
            name,
            persona_prompt,
        )
    if provider == "anthropic":
        return AnthropicReviewer(
            api_key,
            _model_for_spec(spec, config["anthropic_model"]),
            retry_cfg,
            spec.get("base_url", config["anthropic_base_url"]),
            name,
            persona_prompt,
        )
    if provider in {"grok", "openai_chat", "chat_completions"}:
        return GrokReviewer(
            api_key,
            _model_for_spec(spec, config["grok_model"]),
            retry_cfg,
            spec.get("base_url", config["grok_base_url"]),
            name,
            persona_prompt,
        )

    raise ValueError(
        f"Reviewer '{name}' uses unsupported provider '{provider}'. "
        "Supported providers: mock, openai, responses, anthropic, grok, openai_chat, chat_completions."
    )


def _legacy_live_reviewer_specs(config: Dict[str, str]) -> List[Dict[str, str]]:
    available_providers: List[tuple[str, str]] = []
    if config["anthropic_api_key"]:
        available_providers.append(("Claude", "anthropic"))
    if config["openai_api_key"]:
        available_providers.append(("OpenAI", "openai"))
    if config["grok_api_key"]:
        available_providers.append(("Grok", "grok"))

    if not available_providers:
        return []

    return [
        {
            "name": f"{provider_label} {persona['name']}" if len(available_providers) == 1 else persona["name"],
            "provider": provider,
            "prompt": persona["prompt"],
        }
        for index, persona in enumerate(DEFAULT_REVIEWER_PERSONAS)
        for provider_label, provider in [available_providers[index % len(available_providers)]]
    ]


def _default_arbitrator_spec(config: Dict[str, str]) -> Dict[str, str]:
    if config["grok_api_key"]:
        return {"name": "Arbitrator", "provider": "grok"}
    if config["openai_api_key"]:
        return {"name": "Arbitrator", "provider": "openai"}
    if config["anthropic_api_key"]:
        return {"name": "Arbitrator", "provider": "anthropic"}
    return {"name": "Arbitrator", "provider": "mock"}


def _build_configured_arbitrator(
    spec: Dict[str, str],
    config: Dict[str, str],
    retry_cfg: RetryConfig,
    shared_context: str = "",
    runtime_context: str = "",
):
    provider = spec.get("provider", "mock")
    name = spec.get("name", "Arbitrator")
    prompt = _compose_agent_prompt(spec.get("prompt", spec.get("persona", "")), shared_context, runtime_context)

    if provider == "mock":
        return MockConsolidator(name, prompt)

    api_key = _api_key_for_spec(spec, config)
    if not api_key:
        raise ValueError(f"Arbitrator '{name}' is missing an API key.")

    model, base_url = _provider_defaults(provider, config)
    model = _model_for_spec(spec, model)
    base_url = spec.get("base_url", base_url)

    if provider in {"openai", "responses"}:
        return OpenAIConsolidator(api_key, model, retry_cfg, base_url, name, prompt)
    if provider == "anthropic":
        return AnthropicConsolidator(api_key, model, retry_cfg, base_url, name, prompt)
    if provider in {"grok", "openai_chat", "chat_completions"}:
        return GrokConsolidator(api_key, model, retry_cfg, base_url, name, prompt)

    raise ValueError(
        f"Arbitrator '{name}' uses unsupported provider '{provider}'. "
        "Supported providers: mock, openai, responses, anthropic, grok, openai_chat, chat_completions."
    )


@dataclass(frozen=True)
class ReviewerSelection:
    selected_specs: List[Dict[str, str]]
    concrete_plan: str
    rationale: Dict[str, str]
    raw_response: str
    source: str
    error: str = ""


def _reviewer_catalog_for_selection(config: Dict[str, str]) -> List[Dict[str, str]]:
    configured_catalog = configured_reviewer_catalog_specs(config)
    if configured_catalog:
        return configured_catalog

    live_specs = _legacy_live_reviewer_specs(config)
    if live_specs:
        return live_specs

    mock_names = mock_reviewer_names(config)
    if not mock_names:
        mock_names = [persona["name"] for persona in DEFAULT_REVIEWER_PERSONAS]
    persona_by_name = {persona["name"]: persona["prompt"] for persona in DEFAULT_REVIEWER_PERSONAS}
    return [
        {
            "name": name,
            "provider": "mock",
            "category": "default",
            "active": "true",
            "prompt": persona_by_name.get(name, f"Focus on {name.lower()} concerns."),
        }
        for name in mock_names
    ]


def _active_selection_fallback(catalog: List[Dict[str, str]]) -> List[Dict[str, str]]:
    active = [spec for spec in catalog if _as_bool(str(spec.get("active", True)))]
    return active or catalog


def _selection_prompt(idea: str, workflow: str, plan_md: str, catalog: List[Dict[str, str]]) -> str:
    rendered_catalog = []
    for spec in catalog:
        rendered_catalog.append(
            {
                "name": spec.get("name", ""),
                "category": spec.get("category", "default"),
                "active_by_default": _as_bool(str(spec.get("active", True))),
                "user_forced_active": _as_bool(str(spec.get("user_forced_active", False))),
                "user_disabled": _as_bool(str(spec.get("user_disabled", False))),
                "activate_when": spec.get("activate_when", ""),
                "prompt": spec.get("prompt", spec.get("persona", "")),
            }
        )
    return (
        "You are the high-capacity arbitrator planning a reviewer panel before expert review starts.\n"
        "Read the user request and initial plan, form a concrete review strategy, and select only the experts needed.\n\n"
        "Selection rules:\n"
        "- Select reviewers by exact name from the catalog only.\n"
        "- Prefer the smallest panel that covers material product, engineering, delivery, risk, and research concerns.\n"
        "- Do not select a specialist just because it exists. Select it only when the idea makes that specialty materially relevant.\n"
        "- Never select reviewers where user_disabled is true.\n"
        "- Prefer including reviewers where user_forced_active is true unless they are impossible for the workflow.\n"
        "- If the idea has no persistent data, database, reporting, data migration, analytics, or stored user resources, do not select a database/data expert.\n"
        "- If the idea has no payments, invoices, subscriptions, refunds, commissions, or money movement, do not select a billing/finance expert.\n"
        "- If the idea has no AI/ML behavior, do not select an AI/ML expert.\n"
        "- If the idea has no regulated, sensitive, child, health, finance, identity, legal, or strict retention data, do not select a privacy/compliance expert.\n"
        "- If the idea has no public API, mobile clients, third-party integrations, or complex frontend/backend handoff, do not select an API contract specialist.\n"
        "- Always include a general implementation/architecture reviewer unless no such expert exists.\n"
        "- Return strict JSON only. Do not include markdown fences.\n\n"
        "Return this shape exactly:\n"
        "{"
        "\"concrete_plan\":\"short concrete review strategy\","
        "\"selected_reviewers\":[{\"name\":\"exact catalog name\",\"reason\":\"why needed\"}],"
        "\"rejected_reviewers\":[{\"name\":\"exact catalog name\",\"reason\":\"why not needed\"}]"
        "}\n\n"
        f"Workflow: {workflow}\n"
        f"User request: {idea}\n\n"
        f"Reviewer catalog JSON:\n{json.dumps(rendered_catalog, indent=2)}\n\n"
        f"Initial plan:\n{plan_md[:20000]}"
    )


def _parse_selection_json(text: str) -> tuple[str, Dict[str, str], List[str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("selector response must be a JSON object.")
    concrete_plan = str(parsed.get("concrete_plan", "")).strip()
    selected_raw = parsed.get("selected_reviewers", [])
    if not isinstance(selected_raw, list):
        raise ValueError("selected_reviewers must be a JSON array.")
    rationale: Dict[str, str] = {}
    selected_names: List[str] = []
    for item in selected_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if not name:
            continue
        selected_names.append(name)
        rationale[name] = reason
    return concrete_plan, rationale, selected_names


def _invoke_reviewer_selector(
    *,
    idea: str,
    workflow: str,
    plan_md: str,
    catalog: List[Dict[str, str]],
    config: Dict[str, str],
    retry_cfg: RetryConfig,
    arbitrator_spec: Dict[str, str],
) -> tuple[str, Dict[str, str], List[str], str]:
    provider = arbitrator_spec.get("provider", "mock")
    prompt = _selection_prompt(idea, workflow, plan_md, catalog)

    if provider == "mock":
        names = _heuristic_reviewer_names(idea, plan_md, catalog)
        return "Heuristic reviewer panel selected from the idea and initial plan.", {
            name: "Selected by mock heuristic from reviewer role and plan signals." for name in names
        }, names, json.dumps({"selected_reviewers": [{"name": name} for name in names]})

    api_key = _api_key_for_spec(arbitrator_spec, config)
    if not api_key:
        raise ValueError(f"Reviewer selector '{arbitrator_spec.get('name', 'Arbitrator')}' is missing an API key.")

    if provider in {"openai", "responses"}:
        model = _model_for_spec(arbitrator_spec, config["openai_model"])
        base_url = arbitrator_spec.get("base_url", config["openai_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/responses",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {"model": model, "input": prompt},
            retry_cfg,
        )
        raw = _extract_text_response(result)
        concrete_plan, rationale, names = _parse_selection_json(raw)
        return concrete_plan, rationale, names, raw

    if provider == "anthropic":
        model = _model_for_spec(arbitrator_spec, config["anthropic_model"])
        base_url = arbitrator_spec.get("base_url", config["anthropic_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/messages",
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {"model": model, "max_tokens": 1600, "messages": [{"role": "user", "content": prompt}]},
            retry_cfg,
        )
        raw = _extract_text_response(result)
        concrete_plan, rationale, names = _parse_selection_json(raw)
        return concrete_plan, rationale, names, raw

    if provider in {"grok", "openai_chat", "chat_completions"}:
        model = _model_for_spec(arbitrator_spec, config["grok_model"])
        base_url = arbitrator_spec.get("base_url", config["grok_base_url"]).rstrip("/")
        result = _post_json(
            f"{base_url}/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            },
            retry_cfg,
        )
        raw = _extract_text_response(result)
        concrete_plan, rationale, names = _parse_selection_json(raw)
        return concrete_plan, rationale, names, raw

    raise ValueError(f"Reviewer selector uses unsupported provider '{provider}'.")


def _heuristic_reviewer_names(idea: str, plan_md: str, catalog: List[Dict[str, str]]) -> List[str]:
    searchable = f"{idea}\n{plan_md}".lower()
    selected: List[str] = []

    def has_any(markers: tuple[str, ...]) -> bool:
        return any(marker in searchable for marker in markers)

    no_data_markers = (
        "no database",
        "no persistent data",
        "does not store",
        "doesn't store",
        "static website",
        "static landing page",
        "offline calculator",
    )
    database_markers = (
        "database",
        "postgres",
        "mysql",
        "sqlite",
        "schema",
        "migration",
        "stored",
        "persistent",
        "reporting",
        "analytics",
    )
    billing_markers = ("payment", "billing", "invoice", "subscription", "refund", "commission", "tax", "ledger")
    ai_markers = (" ai ", "llm", "model", "embedding", "rag", "classification", "recommendation", "machine learning")
    privacy_markers = ("personal", "sensitive", "health", "minor", "child", "identity", "gdpr", "ccpa", "retention")
    api_markers = (" api", "mobile app", "third-party", "integration", "webhook", "public endpoint", "client")
    performance_markers = ("high concurrency", "latency", "p95", "p99", "media processing", "background job", "scale")
    support_markers = ("support", "admin", "incident", "manual override", "recovery", "customer complaint")
    legal_markers = ("legal", "terms", "marketplace", "liability", "intellectual property", "contract")

    for spec in catalog:
        name = spec.get("name", "")
        name_l = name.lower()
        category = spec.get("category", "").lower()
        active = _as_bool(str(spec.get("active", True)))
        if _as_bool(str(spec.get("user_disabled", False))):
            continue
        if _as_bool(str(spec.get("user_forced_active", False))):
            selected.append(name)
            continue
        include = active and category != "optional"
        if "database" in name_l or "data engineer" in name_l:
            include = has_any(database_markers) and not has_any(no_data_markers)
        elif "billing" in name_l or "finance" in name_l:
            include = has_any(billing_markers)
        elif "ai" in name_l or "ml" in name_l:
            include = has_any(ai_markers)
        elif "privacy" in name_l or "compliance" in name_l:
            include = has_any(privacy_markers)
        elif "api contract" in name_l:
            include = has_any(api_markers)
        elif "performance" in name_l:
            include = has_any(performance_markers)
        elif "support" in name_l:
            include = has_any(support_markers)
        elif "legal" in name_l:
            include = has_any(legal_markers)
        if include:
            selected.append(name)

    if not selected and catalog:
        for spec in catalog:
            name = spec.get("name", "")
            if any(marker in name.lower() for marker in ("architect", "full stack", "implementation", "research problem")):
                selected.append(name)
                break
    return selected or [catalog[0]["name"]]


def _select_reviewer_specs(
    *,
    idea: str,
    workflow: str,
    plan_md: str,
    catalog: List[Dict[str, str]],
    config: Dict[str, str],
    retry_cfg: RetryConfig,
    arbitrator_spec: Dict[str, str],
) -> ReviewerSelection:
    if not catalog:
        return ReviewerSelection([], "", {}, "", "static", "No reviewer catalog was available.")

    if not _as_bool(config.get("dynamic_reviewer_selection", "false")):
        return ReviewerSelection(_active_selection_fallback(catalog), "", {}, "", "static")

    try:
        concrete_plan, rationale, selected_names, raw = _invoke_reviewer_selector(
            idea=idea,
            workflow=workflow,
            plan_md=plan_md,
            catalog=catalog,
            config=config,
            retry_cfg=retry_cfg,
            arbitrator_spec=arbitrator_spec,
        )
        by_name = {spec["name"]: spec for spec in catalog}
        selected_specs = [
            by_name[name]
            for name in selected_names
            if name in by_name and not _as_bool(str(by_name[name].get("user_disabled", False)))
        ]
        forced_specs = [
            spec
            for spec in catalog
            if _as_bool(str(spec.get("user_forced_active", False)))
            and not _as_bool(str(spec.get("user_disabled", False)))
            and spec not in selected_specs
        ]
        selected_specs = forced_specs + selected_specs
        if not selected_specs:
            raise ValueError("selector did not return any valid reviewer names.")
        return ReviewerSelection(selected_specs, concrete_plan, rationale, raw, "arbitrator")
    except Exception as exc:
        fallback = _active_selection_fallback(catalog)
        return ReviewerSelection(
            fallback,
            "Dynamic reviewer selection failed; using active reviewer fallback.",
            {spec["name"]: "Fallback active reviewer." for spec in fallback},
            "",
            "fallback",
            str(exc),
        )


def _render_reviewer_selection(selection: ReviewerSelection, catalog: List[Dict[str, str]]) -> str:
    selected_names = {spec["name"] for spec in selection.selected_specs}
    lines = [
        "# Reviewer Selection",
        "",
        f"- Source: {selection.source}",
        f"- Selected reviewers: {len(selection.selected_specs)}",
    ]
    if selection.error:
        lines.append(f"- Selection error: {selection.error}")
    if selection.concrete_plan:
        lines.extend(["", "## Concrete Review Plan", selection.concrete_plan])
    lines.extend(["", "## Selected Reviewers"])
    for spec in selection.selected_specs:
        name = spec["name"]
        reason = selection.rationale.get(name, "Selected for this run.")
        lines.append(f"- {name}: {reason}")
    lines.extend(["", "## Available But Not Selected"])
    for spec in catalog:
        name = spec["name"]
        if name in selected_names:
            continue
        reason = spec.get("activate_when", "").strip() or "Not selected for this request."
        lines.append(f"- {name}: {reason}")
    if selection.raw_response:
        lines.extend(["", "## Raw Selector Response", "```json", selection.raw_response.strip(), "```"])
    return "\n".join(lines).strip() + "\n"


def _render_reviewer_catalog_for_terminal(catalog: List[Dict[str, str]]) -> str:
    lines = ["Current reviewer catalog:"]
    for index, spec in enumerate(catalog, start=1):
        name = spec.get("name", f"Reviewer {index}")
        category = spec.get("category", "default")
        active = "active" if _as_bool(str(spec.get("active", True))) else "inactive"
        activate_when = spec.get("activate_when", "").strip()
        detail = f" - {activate_when}" if activate_when else ""
        lines.append(f"{index}. {name} [{category}, {active}]{detail}")
    return "\n".join(lines)


def _catalog_spec_lookup(catalog: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for index, spec in enumerate(catalog, start=1):
        lookup[str(index)] = spec
        lookup[spec.get("name", "").strip().lower()] = spec
    return lookup


def _parse_catalog_token(token: str, catalog: List[Dict[str, str]]) -> tuple[str, Dict[str, str] | None]:
    cleaned = token.strip()
    if not cleaned:
        return "", None
    action = "activate"
    if cleaned[0] in {"+", "-"}:
        action = "deactivate" if cleaned[0] == "-" else "activate"
        cleaned = cleaned[1:].strip()
    lookup = _catalog_spec_lookup(catalog)
    return action, lookup.get(cleaned.lower())


def _apply_technical_reviewer_catalog_update(catalog: List[Dict[str, str]], answer: str) -> List[Dict[str, str]]:
    raw = answer.strip()
    if not raw:
        return catalog

    updated = [dict(spec) for spec in catalog]
    by_name = {spec.get("name", ""): spec for spec in updated}

    if raw.lower().startswith("only:"):
        selected: set[str] = set()
        for token in raw[5:].split(","):
            _action, spec = _parse_catalog_token(token, catalog)
            if spec is not None:
                selected.add(spec.get("name", ""))
        if not selected:
            return catalog
        for spec in updated:
            if spec.get("name", "") in selected:
                spec["active"] = "true"
                spec["user_forced_active"] = "true"
                spec.pop("user_disabled", None)
            else:
                spec["active"] = "false"
                spec["user_disabled"] = "true"
                spec.pop("user_forced_active", None)
        return updated

    changed = False
    for token in raw.split(","):
        action, spec = _parse_catalog_token(token, catalog)
        if spec is None:
            continue
        target = by_name.get(spec.get("name", ""))
        if target is None:
            continue
        if action == "deactivate":
            target["active"] = "false"
            target["user_disabled"] = "true"
            target.pop("user_forced_active", None)
        else:
            target["active"] = "true"
            target["user_forced_active"] = "true"
            target.pop("user_disabled", None)
        changed = True
    return updated if changed else catalog


def _maybe_update_reviewer_catalog_for_technical_user(
    *,
    config: Dict[str, str],
    answers: Dict[str, str],
) -> List[Dict[str, str]] | None:
    if not _as_bool(config.get("dynamic_reviewer_selection", "false")):
        return None
    if user_knowledge_level(answers) != "technical":
        return None

    catalog = _reviewer_catalog_for_selection(config)
    if not catalog:
        return None

    print("\nTechnical reviewer catalog review")
    print(_render_reviewer_catalog_for_terminal(catalog))
    answer = prompt_user(
        "Press Enter to keep this catalog for arbitrator selection, or update it for this run.\n"
        "Use '+Name' to activate, '-Name' to deactivate, or 'only: Name, Name' to constrain active reviewers."
    )
    updated = _apply_technical_reviewer_catalog_update(catalog, "" if answer == "Not specified" else answer)
    if updated != catalog:
        print("Reviewer catalog updated for this run before arbitrator selection.")
    else:
        print("Reviewer catalog kept unchanged.")
    return updated


def _build_runtime_agents_for_plan(
    config: Dict[str, str],
    *,
    idea: str,
    workflow: str,
    plan_md: str,
    selection_artifact: Path | None = None,
    reviewer_catalog_override: List[Dict[str, str]] | None = None,
):
    if not _as_bool(config.get("dynamic_reviewer_selection", "false")):
        reviewers, consolidator, runtime_mode = _build_runtime_agents(config)
        selection = ReviewerSelection(
            selected_specs=[{"name": reviewer.name} for reviewer in reviewers],
            concrete_plan="Dynamic reviewer selection is disabled; using the configured/static reviewer panel.",
            rationale={reviewer.name: "Configured/static reviewer." for reviewer in reviewers},
            raw_response="",
            source="static",
        )
        if selection_artifact is not None:
            write_text(
                selection_artifact,
                _render_reviewer_selection(selection, reviewer_catalog_override or _reviewer_catalog_for_selection(config)),
            )
        return reviewers, consolidator, runtime_mode, selection

    mode = config["agent_mode"].lower()
    allow_mock_fallback = _as_bool(config["allow_mock_fallback"])
    retry_cfg = RetryConfig(
        timeout_seconds=float(config["http_timeout_seconds"]),
        max_retries=int(config["http_max_retries"]),
        backoff_seconds=float(config["http_backoff_seconds"]),
    )
    arbitrator_spec = configured_arbitrator_spec(config) or _default_arbitrator_spec(config)
    catalog = reviewer_catalog_override or _reviewer_catalog_for_selection(config)
    selection = _select_reviewer_specs(
        idea=idea,
        workflow=workflow,
        plan_md=plan_md,
        catalog=catalog,
        config=config,
        retry_cfg=retry_cfg,
        arbitrator_spec=arbitrator_spec,
    )
    if selection_artifact is not None:
        write_text(selection_artifact, _render_reviewer_selection(selection, catalog))

    selected_specs = selection.selected_specs
    if mode == "mock":
        selected_specs = [{**spec, "provider": "mock"} for spec in selected_specs]

    shared_context = _shared_prompt_context(config)
    reviewer_runtime_context = _runtime_prompt_composition_context(config, "reviewer")
    arbitrator_runtime_context = _runtime_prompt_composition_context(config, "arbitrator")
    use_live = mode == "live" or (mode == "auto" and any(spec.get("provider") != "mock" for spec in selected_specs))

    if use_live:
        try:
            reviewers = [
                _build_configured_reviewer(spec, config, retry_cfg, shared_context, reviewer_runtime_context)
                for spec in selected_specs
            ]
            consolidator = _build_configured_arbitrator(
                arbitrator_spec,
                config,
                retry_cfg,
                shared_context,
                arbitrator_runtime_context,
            )
            return reviewers, consolidator, "dynamic" if selection.source == "arbitrator" else selection.source, selection
        except Exception:
            if not allow_mock_fallback or mode == "live":
                raise

    mock_specs = [{**spec, "provider": "mock"} for spec in selected_specs]
    reviewers = [
        _build_configured_reviewer(spec, config, retry_cfg, "", "")
        for spec in mock_specs
    ]
    consolidator = _build_configured_arbitrator(
        {"name": arbitrator_spec.get("name", "Arbitrator"), "provider": "mock", "prompt": arbitrator_spec.get("prompt", "")},
        config,
        retry_cfg,
        shared_context,
        arbitrator_runtime_context,
    )
    return reviewers, consolidator, "mock-dynamic" if selection.source == "arbitrator" else "mock", selection


def _build_runtime_agents(config: Dict[str, str]):
    mode = config["agent_mode"].lower()
    allow_mock_fallback = _as_bool(config["allow_mock_fallback"])
    retry_cfg = RetryConfig(
        timeout_seconds=float(config["http_timeout_seconds"]),
        max_retries=int(config["http_max_retries"]),
        backoff_seconds=float(config["http_backoff_seconds"]),
    )

    configured_specs = configured_reviewer_specs(config)
    live_specs = configured_specs or _legacy_live_reviewer_specs(config)
    use_live = mode == "live" or (mode == "auto" and live_specs)
    arbitrator_spec = configured_arbitrator_spec(config)
    shared_context = _shared_prompt_context(config)
    reviewer_runtime_context = _runtime_prompt_composition_context(config, "reviewer")
    arbitrator_runtime_context = _runtime_prompt_composition_context(config, "arbitrator")

    if use_live:
        try:
            reviewers = [
                _build_configured_reviewer(spec, config, retry_cfg, shared_context, reviewer_runtime_context)
                for spec in live_specs
            ]
            if not reviewers:
                raise ValueError("at least one reviewer must be configured.")
            consolidator = _build_configured_arbitrator(
                arbitrator_spec or _default_arbitrator_spec(config),
                config,
                retry_cfg,
                shared_context,
                arbitrator_runtime_context,
            )
            return reviewers, consolidator, "configured" if configured_specs else "live"
        except Exception:
            if not allow_mock_fallback or mode == "live":
                raise

    mock_names = mock_reviewer_names(config)
    if not mock_names:
        mock_names = [persona["name"] for persona in DEFAULT_REVIEWER_PERSONAS]
    reviewers = [MockAgent(name) for name in mock_names]
    consolidator = _build_configured_arbitrator(
        arbitrator_spec or {"name": "Arbitrator", "provider": "mock"},
        config,
        retry_cfg,
        shared_context,
        arbitrator_runtime_context,
    )
    return reviewers, consolidator, "mock"


def _review_artifact_name(reviewer_name: str, used_names: set[str]) -> str:
    base = slugify(reviewer_name) or "reviewer"
    candidate = f"{base}_review.md"
    counter = 2
    while candidate in used_names:
        candidate = f"{base}_{counter}_review.md"
        counter += 1
    used_names.add(candidate)
    return candidate


def _run_review_iterations(
    *,
    current_plan: str,
    run_dir: Path,
    iterations: int,
    idea: str,
    product_name: str,
    workflow: str,
    initial_artifact: Path,
    ask_review_clarifications: bool,
    review_context_md: str = "",
    review_context_artifact: Path | None = None,
    extra_artifacts: Dict[str, Path] | None = None,
    config_file: Path | None = None,
    reviewer_catalog_override: List[Dict[str, str]] | None = None,
) -> Path:
    config = env_config(config_file=config_file)
    selection_path = run_dir / "reviewer_selection.md"
    reviewers, consolidator, runtime_mode, reviewer_selection = _build_runtime_agents_for_plan(
        config,
        idea=idea,
        workflow=workflow,
        plan_md=current_plan,
        selection_artifact=selection_path,
        reviewer_catalog_override=reviewer_catalog_override,
    )
    reviewer_names = [r.name for r in reviewers]
    manifest: Dict[str, object] = {
        "idea": idea,
        "product_name": product_name,
        "workflow": workflow,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "iterations": iterations,
        "agent_mode": runtime_mode,
        "reviewers": reviewer_names,
        "arbitrator": getattr(consolidator, "name", "Arbitrator"),
        "reviewer_selection": {
            "source": reviewer_selection.source,
            "selected_reviewers": reviewer_names,
            "error": reviewer_selection.error,
        },
        "artifacts": {"initial_plan": str(initial_artifact)},
    }
    artifacts = manifest["artifacts"]
    if isinstance(artifacts, dict):
        artifacts["reviewer_selection"] = str(selection_path)
    print(f"Reviewer selection written: {selection_path}")
    print(f"Selected reviewers: {', '.join(reviewer_names)}")
    if review_context_artifact is not None:
        artifacts = manifest["artifacts"]
        if isinstance(artifacts, dict):
            artifacts["related_version_context"] = str(review_context_artifact)
    if extra_artifacts:
        artifacts = manifest["artifacts"]
        if isinstance(artifacts, dict):
            for name, artifact_path in extra_artifacts.items():
                artifacts[name] = str(artifact_path)
    write_json(run_dir / "run_manifest.json", manifest)

    answered_review_questions: set[str] = set()
    for i in range(1, iterations + 1):
        iter_dir = run_dir / f"iteration_{i:02d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nRunning iteration {i}/{iterations}...")

        results: List[AgentResult] = []
        iter_manifest: Dict[str, object] = {
            "iteration": i,
            "reviews": [],
            "review_clarifications": {},
            "consolidated_plan": "",
        }
        review_artifact_names: set[str] = set()
        for reviewer in reviewers:
            try:
                review_input = current_plan
                if review_context_md:
                    review_input = (
                        "The following related version context is supplemental. Use it to evaluate progression "
                        "and implementation direction, but critique and revise the source plan as the primary artifact.\n\n"
                        f"{review_context_md}\n\n---\n\n# Source Plan Under Review\n\n{current_plan}"
                    )
                review_text = reviewer.review(review_input)
            except Exception as exc:
                review_text = (
                    f"# {reviewer.name} Review\n\n"
                    "## Error\n"
                    f"- Reviewer failed: {exc}\n"
                )
            review_path = iter_dir / _review_artifact_name(reviewer.name, review_artifact_names)
            write_text(review_path, review_text)
            results.append(AgentResult(reviewer.name, review_text))
            cast_reviews = iter_manifest["reviews"]
            if isinstance(cast_reviews, list):
                cast_reviews.append(str(review_path))
            print(f"  Wrote: {review_path}")

        follow_ups = []
        if ask_review_clarifications:
            follow_ups = [
                follow_up
                for follow_up in generate_review_follow_up_questions([result.content for result in results])
                if follow_up.question not in answered_review_questions
            ]
        if follow_ups:
            print(
                "\nReviewer comments raised user-owned decisions. Answer in product terms; "
                "the planner will translate your answers into tests, security controls, and implementation details."
            )
            review_answers: Dict[str, str] = {}
            evidence_by_question: Dict[str, str] = {}
            for follow_up in follow_ups:
                answer = prompt_user(display_question_for_user(follow_up.question, {}))
                review_answers[follow_up.question] = resolve_answer(idea, follow_up.question, answer)
                evidence_by_question[follow_up.question] = follow_up.evidence
                answered_review_questions.add(follow_up.question)

            current_plan = append_review_clarifications(current_plan, i, review_answers, evidence_by_question)
            clarification_path = iter_dir / "user_review_clarifications.md"
            clarification_lines = [f"# User Review Clarifications - Iteration {i}", ""]
            for question, answer in review_answers.items():
                clarification_lines.append(f"## {question}")
                clarification_lines.append(f"- Reviewer comment: {evidence_by_question[question]}")
                clarification_lines.append(f"- User answer: {answer}")
                clarification_lines.append("")
            write_text(clarification_path, "\n".join(clarification_lines).strip() + "\n")
            iter_manifest["review_clarifications"] = {
                "artifact": str(clarification_path),
                "answers": review_answers,
            }
            print(f"  Wrote: {clarification_path}")

        print("  Arbitrating architect critiques and producing the revised plan...")
        try:
            consolidated = consolidator.consolidate(current_plan, results)
        except Exception as exc:
            fallback = MockConsolidator()
            consolidated = fallback.consolidate(
                current_plan + f"\n\n## Consolidator Error\n- {exc}\n", results
            )
        consolidated_path = iter_dir / "consolidated_plan.md"
        write_text(consolidated_path, consolidated)
        iter_manifest["consolidated_plan"] = str(consolidated_path)
        write_json(iter_dir / "iteration_manifest.json", iter_manifest)
        print(f"  Wrote: {consolidated_path}")
        current_plan = consolidated

    final_path = run_dir / "final_plan.md"
    write_text(final_path, current_plan)
    risks_path = run_dir / "risks.md"
    write_text(risks_path, build_negative_reference(current_plan, product_name, final_path))
    artifacts = manifest["artifacts"]
    if isinstance(artifacts, dict):
        artifacts["final_plan"] = str(final_path)
        artifacts["risks"] = str(risks_path)
    write_json(run_dir / "run_manifest.json", manifest)
    print(f"\nFinal plan written: {final_path}")
    print(f"Risks reference written: {risks_path}")
    return final_path


def _load_obsidian_context_artifact(
    *,
    idea_file: str,
    run_dir: Path,
    max_depth: int,
    max_notes: int,
) -> tuple[str, Path]:
    seed_file = Path(idea_file).expanduser()
    contexts = collect_obsidian_context(seed_file, max_depth=max_depth, max_notes=max_notes)
    rendered = render_obsidian_context(contexts, seed_file)
    artifact_path = run_dir / "obsidian_context.md"
    write_text(artifact_path, rendered)
    print(f"Obsidian idea context written: {artifact_path}")
    return rendered, artifact_path


def run(
    idea: str,
    iterations: int,
    output_root: Path,
    config_file: Path | None = None,
    workflow: str = "idea-to-plan-with-architect-review",
    obsidian_idea_file: str = "",
) -> Path:
    config = env_config(config_file=config_file)
    answers: Dict[str, str] = {}
    print("Answer clarifying questions before the plan is generated.")
    for q in generate_questions(idea):
        answer = prompt_user(display_question_for_user(q, answers))
        answer = resolve_answer(idea, q, answer)
        while needs_detail_for_question(q, answer):
            detail_answer = prompt_user(display_question_for_user(detail_follow_up_for(q, answer), answers))
            answer = f"{answer.rstrip()} {resolve_answer(idea, q, detail_answer)}"
        answers[q] = answer
        if should_ask_follow_up(answer):
            follow_up = follow_up_for(q)
            follow_up_answer = prompt_user(display_question_for_user(follow_up, answers))
            answers[follow_up] = resolve_answer(idea, follow_up, follow_up_answer)

    collect_final_discovery_context(idea, answers)
    product_name = product_name_from_answers(idea, answers)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{timestamp}_{slugify(product_name)[:40]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    current_plan = build_initial_plan(idea, answers)
    extra_artifacts: Dict[str, Path] = {}
    selected_obsidian_file = obsidian_idea_file.strip() or config.get("obsidian_idea_file", "").strip()
    if selected_obsidian_file:
        obsidian_context, obsidian_artifact = _load_obsidian_context_artifact(
            idea_file=selected_obsidian_file,
            run_dir=run_dir,
            max_depth=_as_int(config.get("obsidian_max_depth", "1"), default=1),
            max_notes=_as_int(config.get("obsidian_max_notes", "12"), default=12, minimum=1),
        )
        current_plan = f"{current_plan.rstrip()}\n\n{obsidian_context}"
        extra_artifacts["obsidian_context"] = obsidian_artifact
    initial_plan_path = run_dir / "initial_plan.md"
    write_text(initial_plan_path, current_plan)
    print(f"\nInitial plan written: {initial_plan_path}")
    reviewer_catalog_override = _maybe_update_reviewer_catalog_for_technical_user(
        config=config,
        answers=answers,
    )

    return _run_review_iterations(
        current_plan=current_plan,
        run_dir=run_dir,
        iterations=iterations,
        idea=idea,
        product_name=product_name,
        workflow=workflow,
        initial_artifact=initial_plan_path,
        ask_review_clarifications=True,
        extra_artifacts=extra_artifacts,
        config_file=config_file,
        reviewer_catalog_override=reviewer_catalog_override,
    )


def run_research(
    topic: str,
    iterations: int,
    output_root: Path,
    config_file: Path | None = None,
    obsidian_idea_file: str = "",
) -> Path:
    config = env_config(config_file=config_file)
    static_questions = generate_research_questions(topic)
    dynamic_error = ""
    try:
        dynamic_questions = _generate_dynamic_research_questions(topic, static_questions, config)
    except Exception as exc:
        dynamic_questions = []
        dynamic_error = str(exc)
    questions = merge_research_questions(static_questions, dynamic_questions)

    answers: Dict[str, str] = {}
    print("Answer research discovery questions before the plan is generated.")
    for q in questions:
        answer = prompt_user(display_question_for_user(q, answers))
        answer = resolve_answer(topic, q, answer)
        while needs_detail_for_question(q, answer):
            detail_answer = prompt_user(display_question_for_user(detail_follow_up_for(q, answer), answers))
            answer = f"{answer.rstrip()} {resolve_answer(topic, q, detail_answer)}"
        answers[q] = answer
        if should_ask_follow_up(answer):
            follow_up = follow_up_for(q)
            follow_up_answer = prompt_user(display_question_for_user(follow_up, answers))
            answers[follow_up] = resolve_answer(topic, follow_up, follow_up_answer)

    collect_final_discovery_context(topic, answers)
    project_name = research_project_name_from_answers(topic, answers)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{timestamp}_{slugify(project_name)[:40]}_research"
    run_dir.mkdir(parents=True, exist_ok=True)

    current_plan = build_initial_research_plan(topic, answers)
    current_plan = _append_discovery_questions_context(current_plan, static_questions, dynamic_questions)
    extra_artifacts: Dict[str, Path] = {}
    selected_obsidian_file = obsidian_idea_file.strip() or config.get("obsidian_idea_file", "").strip()
    if selected_obsidian_file:
        obsidian_context, obsidian_artifact = _load_obsidian_context_artifact(
            idea_file=selected_obsidian_file,
            run_dir=run_dir,
            max_depth=_as_int(config.get("obsidian_max_depth", "1"), default=1),
            max_notes=_as_int(config.get("obsidian_max_notes", "12"), default=12, minimum=1),
        )
        current_plan = f"{current_plan.rstrip()}\n\n{obsidian_context}"
        extra_artifacts["obsidian_context"] = obsidian_artifact
    initial_plan_path = run_dir / "initial_plan.md"
    write_text(initial_plan_path, current_plan)
    questions_path = run_dir / "discovery_questions.md"
    write_text(
        questions_path,
        _render_research_questions_artifact(static_questions, dynamic_questions, questions, dynamic_error),
    )
    print(f"\nInitial research plan written: {initial_plan_path}")
    print(f"Research discovery questions written: {questions_path}")
    reviewer_catalog_override = _maybe_update_reviewer_catalog_for_technical_user(
        config=config,
        answers=answers,
    )

    final_path = _run_review_iterations(
        current_plan=current_plan,
        run_dir=run_dir,
        iterations=iterations,
        idea=topic,
        product_name=project_name,
        workflow="research-to-plan-with-review",
        initial_artifact=initial_plan_path,
        ask_review_clarifications=False,
        extra_artifacts=extra_artifacts,
        config_file=config_file,
        reviewer_catalog_override=reviewer_catalog_override,
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["discovery_questions"] = str(questions_path)
        manifest["artifacts"] = artifacts
        write_json(manifest_path, manifest)
    return final_path


def run_problem(
    problem: str,
    iterations: int,
    output_root: Path,
    config_file: Path | None = None,
    obsidian_idea_file: str = "",
) -> Path:
    config = env_config(config_file=config_file)
    answers: Dict[str, str] = {}
    print("Answer problem-solving discovery questions before the plan is generated.")
    for q in generate_problem_questions(problem):
        answer = prompt_user(display_question_for_user(q, answers))
        answer = resolve_answer(problem, q, answer)
        while needs_detail_for_question(q, answer):
            detail_answer = prompt_user(display_question_for_user(detail_follow_up_for(q, answer), answers))
            answer = f"{answer.rstrip()} {resolve_answer(problem, q, detail_answer)}"
        answers[q] = answer
        if should_ask_follow_up(answer):
            follow_up = follow_up_for(q)
            follow_up_answer = prompt_user(display_question_for_user(follow_up, answers))
            answers[follow_up] = resolve_answer(problem, follow_up, follow_up_answer)

    collect_final_discovery_context(problem, answers)
    problem_name = problem_name_from_answers(problem, answers)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{timestamp}_{slugify(problem_name)[:40]}_problem"
    run_dir.mkdir(parents=True, exist_ok=True)

    current_plan = build_initial_problem_plan(problem, answers)
    extra_artifacts: Dict[str, Path] = {}
    selected_obsidian_file = obsidian_idea_file.strip() or config.get("obsidian_idea_file", "").strip()
    if selected_obsidian_file:
        obsidian_context, obsidian_artifact = _load_obsidian_context_artifact(
            idea_file=selected_obsidian_file,
            run_dir=run_dir,
            max_depth=_as_int(config.get("obsidian_max_depth", "1"), default=1),
            max_notes=_as_int(config.get("obsidian_max_notes", "12"), default=12, minimum=1),
        )
        current_plan = f"{current_plan.rstrip()}\n\n{obsidian_context}"
        extra_artifacts["obsidian_context"] = obsidian_artifact
    initial_plan_path = run_dir / "initial_plan.md"
    write_text(initial_plan_path, current_plan)
    print(f"\nInitial problem-solving plan written: {initial_plan_path}")
    reviewer_catalog_override = _maybe_update_reviewer_catalog_for_technical_user(
        config=config,
        answers=answers,
    )

    return _run_review_iterations(
        current_plan=current_plan,
        run_dir=run_dir,
        iterations=iterations,
        idea=problem,
        product_name=problem_name,
        workflow="problem-solver-with-review",
        initial_artifact=initial_plan_path,
        ask_review_clarifications=False,
        extra_artifacts=extra_artifacts,
        config_file=config_file,
        reviewer_catalog_override=reviewer_catalog_override,
    )


def run_plan_review(plan_path: Path, iterations: int, output_root: Path, config_file: Path | None = None) -> Path:
    if not plan_path.exists():
        raise SystemExit(f"Plan file does not exist: {plan_path}")

    current_plan = plan_path.read_text(encoding="utf-8")
    product_name = plan_path.stem
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"{timestamp}_{slugify(product_name)[:40]}_architect_review"
    run_dir.mkdir(parents=True, exist_ok=True)

    initial_plan_path = run_dir / "initial_plan.md"
    write_text(initial_plan_path, current_plan)
    print(f"\nSource plan copied: {initial_plan_path}")

    related_contexts = _collect_related_plan_context(plan_path, current_plan)
    version_context = _render_version_context(plan_path, current_plan, related_contexts)
    version_context_path = run_dir / "related_version_context.md"
    write_text(version_context_path, version_context)
    if related_contexts:
        print(f"Related version context written: {version_context_path}")
    else:
        print(f"No related version context found; wrote search summary: {version_context_path}")

    return _run_review_iterations(
        current_plan=current_plan,
        run_dir=run_dir,
        iterations=iterations,
        idea=f"Architect critique of {plan_path}",
        product_name=product_name,
        workflow="existing-plan-architect-critique",
        initial_artifact=initial_plan_path,
        ask_review_clarifications=False,
        review_context_md=version_context,
        review_context_artifact=version_context_path,
        config_file=config_file,
    )


def parse_args() -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_source = pre_parser.add_mutually_exclusive_group()
    pre_source.add_argument("--idea")
    pre_source.add_argument("--plan-file")
    pre_source.add_argument("--research")
    pre_source.add_argument("--problem")
    pre_parser.add_argument("--config")
    pre_args, _remaining = pre_parser.parse_known_args()
    if pre_args.plan_file:
        workflow = "existing-plan"
    elif pre_args.research:
        workflow = "research"
    elif pre_args.problem:
        workflow = "problem"
    else:
        workflow = "new-idea"
    config_file = Path(pre_args.config) if pre_args.config else default_config_path(workflow)
    cfg = env_config(workflow=workflow, config_file=config_file)

    parser = argparse.ArgumentParser(description="Implementation plan generator and inspector.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--idea", help="High-level product or feature idea.")
    source.add_argument("--plan-file", help="Existing implementation plan markdown file to critique as software architects.")
    source.add_argument("--research", help="Research topic, product idea, or market hypothesis to turn into an implementation plan.")
    source.add_argument("--problem", help="Research, product, technical, customer, or operational issue to diagnose and solve.")
    parser.add_argument(
        "--config",
        help=(
            "Optional config file. Defaults to inspector.new-idea.config.json for --idea, "
            "inspector.existing-plan.config.json for --plan-file, and inspector.research.config.json "
            "for --research, or inspector.problem.config.json for --problem when present."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=int(cfg["default_iterations"]),
        help="Number of critique/consolidation iterations.",
    )
    parser.add_argument(
        "--output",
        default=cfg["output_dir"],
        help="Output root directory for generated markdown artifacts.",
    )
    parser.add_argument(
        "--obsidian-idea-file",
        default=cfg.get("obsidian_idea_file", ""),
        help="Optional path to a seed Obsidian markdown note for idea context.",
    )
    args = parser.parse_args()
    args.config_file = config_file
    return args


def main() -> None:
    load_dotenv(Path(".env"))
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be >= 1")
    if args.plan_file:
        run_plan_review(Path(args.plan_file), args.iterations, Path(args.output), args.config_file)
    elif args.research:
        run_research(args.research, args.iterations, Path(args.output), args.config_file, args.obsidian_idea_file)
    elif args.problem:
        run_problem(args.problem, args.iterations, Path(args.output), args.config_file, args.obsidian_idea_file)
    else:
        run(args.idea, args.iterations, Path(args.output), args.config_file, obsidian_idea_file=args.obsidian_idea_file)


if __name__ == "__main__":
    main()
