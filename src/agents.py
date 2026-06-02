from __future__ import annotations

import datetime as dt
import contextlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Protocol

ARCHITECT_REVIEW_INSTRUCTIONS = (
    "Act as a senior software architect critiquing an implementation plan, not as a general copy editor. "
    "Challenge architecture, boundaries, data ownership, operational readiness, failure modes, and release risk. "
    "Return concise markdown with these sections exactly: Key Issues, Architectural Concerns, Performance Requirements, "
    "Security Flaws, Edge Cases, Specific Testing Required, Documentation Gaps, Recommended Additions, Score. "
    "Include IDOR/BOLA and object-level authorization concerns where relevant. "
    "When a finding requires a product decision from the user, state it as a concrete question. "
    "Check that the final deliverable includes milestones, an ordered checklist, test routes, future issues, "
    "hardware requirements if applicable, software concerns, framework choice, and database recommendation for new products."
)

ARBITRATOR_INSTRUCTIONS = (
    "You are the arbitrator for Claude, OpenAI, and Grok architect critiques. Produce a revised full markdown "
    "implementation plan, not just a summary. Reconcile contradictions explicitly, preserve justified dissenting concerns, "
    "and integrate Review-Driven User Clarifications as authoritative product decisions. "
    "The final document must include sections for Architectural Concerns, Performance Requirements, Security Flaws, "
    "Edge Cases, Specific Testing Required, Open Concerns, milestones, ordered implementation checklist, test routes, "
    "future issues, hardware requirements if applicable, software concerns, framework recommendation, and database "
    "recommendation for new products. Preserve security/testing details including IDOR/BOLA."
)


@dataclass
class AgentResult:
    name: str
    content: str


class Reviewer(Protocol):
    name: str

    def review(self, plan_md: str) -> str:
        ...


@dataclass
class RetryConfig:
    timeout_seconds: float = 30.0
    max_retries: int = 2
    backoff_seconds: float = 1.0


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, object], cfg: RetryConfig) -> Dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=headers, method="POST")
    last_error: Exception | None = None

    for attempt in range(cfg.max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(_format_http_error(exc))
            if attempt == cfg.max_retries:
                break
            time.sleep(cfg.backoff_seconds * (2 ** attempt))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == cfg.max_retries:
                break
            time.sleep(cfg.backoff_seconds * (2 ** attempt))

    raise RuntimeError(f"request failed after retries: {last_error}")


def _format_http_error(exc: urllib.error.HTTPError) -> str:
    detail = ""
    with contextlib.suppress(Exception):
        detail = exc.read().decode("utf-8").strip()
    if detail:
        return f"HTTP Error {exc.code}: {exc.reason}; response body: {detail}"
    return f"HTTP Error {exc.code}: {exc.reason}"


class MockAgent:
    def __init__(self, name: str) -> None:
        self.name = name

    def review(self, _plan_md: str) -> str:
        findings = [
            f"# {self.name} Review",
            "",
            "## Key Issues",
            "- Authorization model is underspecified; add object-level checks to prevent IDOR/BOLA.",
            "- Data retention/deletion policy needs explicit lifecycle states and ownership.",
            "- Failure-mode behavior is incomplete for dependency outage and partial writes.",
            "",
            "## Architectural Concerns",
            "- Service boundaries, resource ownership, and cross-module transaction rules need to be explicit before implementation.",
            "- Database constraints and application authorization checks must reinforce each other rather than relying on UI filtering.",
            "",
            "## Performance Requirements",
            "- Add p95/p99 latency targets for every core user-facing action and background job.",
            "- Define expected data volume, concurrency, burst behavior, and load-test fixtures.",
            "",
            "## Security Flaws",
            "- Missing per-resource access matrix creates IDOR/BOLA risk for reads, writes, deletes, and shares.",
            "- Sensitive mutations need audit logging, replay protection, and least-privilege enforcement.",
            "",
            "## Edge Cases",
            "- Duplicate requests, partial provider failure, stale permissions, deleted-owner resources, and retry storms are not covered.",
            "- Degraded-mode behavior should define what remains read-only, what is blocked, and how users recover.",
            "",
            "## Specific Testing Required",
            "- Positive and negative authorization tests for every resource mutation and read path.",
            "- Migration rollback, dependency-outage, idempotency, rate-limit, and production-shaped load tests.",
            "",
            "## Documentation Gaps",
            "- Add explicit schema evolution and migration rollback plan.",
            "- Add performance test thresholds and test data profile assumptions.",
            "- Add threat model mapping endpoints to authorization decisions.",
            "",
            "## Recommended Additions",
            "- Per-endpoint access matrix (actor, resource, allowed action, denial behavior).",
            "- Test matrix including positive/negative authz tests for every resource mutation.",
            "- Operational runbook notes for incident triage and degraded mode.",
            "",
            "## Score",
            "Plan quality: 7/10; implementation-ready after authz and test hardening.",
        ]
        return "\n".join(findings)


class OpenAIReviewer:
    name = "OpenAI"

    def __init__(self, api_key: str, model: str, cfg: RetryConfig, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")

    def review(self, plan_md: str) -> str:
        prompt = f"{ARCHITECT_REVIEW_INSTRUCTIONS}\n\nIMPLEMENTATION PLAN:\n{plan_md}"
        payload = {"model": self.model, "input": prompt}
        result = _post_json(
            f"{self.base_url}/responses",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload,
            self.cfg,
        )
        output_text = _extract_openai_response_text(result)
        if output_text:
            return output_text
        return f"# {self.name} Review\n\nNo output returned."


class AnthropicReviewer:
    name = "Claude"

    def __init__(self, api_key: str, model: str, cfg: RetryConfig, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")

    def review(self, plan_md: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 1200,
            "messages": [
                {
                    "role": "user",
                    "content": f"{ARCHITECT_REVIEW_INSTRUCTIONS}\n\nIMPLEMENTATION PLAN:\n{plan_md}",
                }
            ],
        }
        result = _post_json(
            f"{self.base_url}/messages",
            {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload,
            self.cfg,
        )
        content = result.get("content", [])
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "")
                if isinstance(text, str) and text.strip():
                    return text
        return f"# {self.name} Review\n\nNo output returned."


def _extract_openai_response_text(result: Dict[str, object]) -> str:
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    texts: List[str] = []
    output = result.get("output", [])
    if not isinstance(output, list):
        return ""

    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())

    return "\n\n".join(texts)


class GrokReviewer:
    name = "Grok"

    def __init__(self, api_key: str, model: str, cfg: RetryConfig, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")

    def review(self, plan_md: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a strict senior software architect reviewing implementation plans."},
                {
                    "role": "user",
                    "content": f"{ARCHITECT_REVIEW_INSTRUCTIONS}\n\nIMPLEMENTATION PLAN:\n{plan_md}",
                },
            ],
        }
        result = _post_json(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload,
            self.cfg,
        )
        choices = result.get("choices", [])
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message", {})
                if isinstance(message, dict):
                    text = message.get("content", "")
                    if isinstance(text, str) and text.strip():
                        return text
        return f"# {self.name} Review\n\nNo output returned."


class MockConsolidator:
    def consolidate(self, current_plan_md: str, reviews: List[AgentResult]) -> str:
        issues = []
        for review in reviews:
            for line in review.content.splitlines():
                if line.startswith("- "):
                    issues.append(line[2:])

        uniq_issues = sorted(set(issues))
        addenda = "\n".join([f"- {item}" for item in uniq_issues])
        section = [
            "",
            "## Consolidated Review Improvements",
            "Integrated from Claude/OpenAI/Grok review outputs:",
            addenda if addenda else "- No additional findings.",
            "",
            "## Architectural Concerns",
            "- Confirm service boundaries, resource ownership, transaction boundaries, and authorization enforcement points before implementation.",
            "- Keep database constraints, application authorization, and API contracts aligned so access control does not depend on client behavior.",
            "",
            "## Performance Requirements",
            "- Define p95/p99 latency targets, concurrency assumptions, data-volume targets, background-job timing, and load-test data shape for every core workflow.",
            "",
            "## Security Flaws",
            "- IDOR/BOLA remains the primary security flaw until every owned resource has explicit read, write, share, delete, and denial behavior tests.",
            "- Sensitive mutations require audit logging, replay/idempotency controls, and least-privilege role checks.",
            "",
            "## Edge Cases",
            "- Cover duplicate submissions, provider outages, partial writes, stale permissions, deleted resources, retry storms, empty states, and rollback paths.",
            "",
            "## Specific Testing Required",
            "- Unit: validation, permissions, domain transitions, edge cases, and failure-state reducers.",
            "- Integration: API/database/provider flows, migrations, rollback, idempotency, and outage handling.",
            "- E2E: primary workflow, degraded mode, authorization denial, deletion/export, and release smoke paths.",
            "- Security/performance: IDOR/BOLA probes, replay attempts, secrets exposure, rate limits, and p95/p99 load tests.",
            "",
            "## Open Concerns",
            "- Any unresolved reviewer concern must stay visible with an owner or decision deadline before launch.",
            "",
            "## Reconciliation Notes",
            "- Kept existing scope boundaries.",
            "- Prioritized authorization, test coverage, and operational readiness.",
            f"- Consolidation timestamp: {dt.datetime.now(dt.UTC).isoformat()}",
        ]
        return current_plan_md.strip() + "\n" + "\n".join(section) + "\n"


class OpenAIConsolidator:
    def __init__(self, api_key: str, model: str, cfg: RetryConfig, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")

    def consolidate(self, current_plan_md: str, reviews: List[AgentResult]) -> str:
        joined_reviews = "\n\n".join([f"## {r.name}\n{r.content}" for r in reviews])
        prompt = (
            f"{ARBITRATOR_INSTRUCTIONS}\n\n"
            "CURRENT PLAN:\n"
            f"{current_plan_md}\n\n"
            "REVIEWS:\n"
            f"{joined_reviews}"
        )
        payload = {"model": self.model, "input": prompt}
        result = _post_json(
            f"{self.base_url}/responses",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            payload,
            self.cfg,
        )
        output_text = _extract_openai_response_text(result)
        if output_text:
            return output_text
        return current_plan_md
