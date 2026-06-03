from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

LOW_SIGNAL_ANSWERS = {
    "n/a",
    "na",
    "none",
    "idk",
    "unknown",
    "not sure",
    "tbd",
    "not specified",
    "a",
    "no idea",
}

GUIDANCE_REQUEST_MARKERS = (
    "which do you think",
    "what do you think",
    "what would you recommend",
    "recommend",
    "best",
    "you decide",
    "no preference",
)

ENGINEERING_DEFAULTS = [
    "Assumed Default: Security tests include IDOR/BOLA attempts across every user-owned resource.",
    "Assumed Default: Mutation APIs use idempotency keys where retries could duplicate effects.",
    "Assumed Default: Observability includes structured logs, core workflow metrics, and failure alerts.",
    "Assumed Default: Sensitive fields are encrypted at rest and minimized by default.",
    "Assumed Default: CI runs unit, integration, and core user-journey E2E tests before release.",
]

HARDWARE_MARKERS = ("button", "hardware", "device", "wearable", "iot", "ble", "bluetooth", "sensor", "firmware")

IMPLEMENTATION_CHECKLIST = [
    "Define v1 scope, non-goals, assumptions, and measurable acceptance criteria.",
    "Create domain model and resource ownership rules before writing API endpoints.",
    "Design database schema with constraints, indexes, migrations, and rollback path.",
    "Implement authentication, authorization, and object-level access checks.",
    "Implement core workflow APIs with validation, idempotency, and audit events.",
    "Build the primary user interface flow and all required empty/loading/error states.",
    "Add integration adapters for external providers and define retry/fallback behavior.",
    "Add observability: structured logs, metrics, traces, dashboards, and alerts.",
    "Document operational runbooks for degraded mode, incident response, and rollback.",
    "Prepare release pipeline with linting, tests, security scans, builds, and deploy gates.",
]

TEST_MATRIX = [
    "Unit tests: validation rules, domain state transitions, permissions, and edge cases.",
    "Integration tests: API-to-database flows, migrations, external-provider adapters, and retry paths.",
    "End-to-end tests: primary user journey, cancellation/rollback paths, and degraded-mode behavior.",
    "Security tests: IDOR/BOLA attempts, unauthorized mutations, replay/deduplication, and sensitive-data exposure.",
    "Performance tests: latency thresholds, expected first-year scale, burst behavior, and background jobs.",
    "Reliability tests: dependency outage, partial failure, duplicate requests, timeout handling, and recovery.",
    "Privacy tests: retention policy, deletion/export behavior, consent boundaries, and audit trail coverage.",
    "Release tests: smoke tests, rollback verification, monitoring alerts, and post-deploy health checks.",
]

LAUNCH_CHECKLIST = [
    "All critical product decisions are resolved or explicitly accepted as launch assumptions.",
    "Acceptance criteria are measurable and have passing evidence.",
    "Security review is complete for every user-owned resource and sensitive workflow.",
    "Operational dashboards and alert thresholds are live.",
    "Rollback plan is documented and tested.",
    "Known risks have owners, mitigations, and decision deadlines.",
]

FINAL_DELIVERABLE_SECTIONS = [
    "Milestones with acceptance criteria and owner-ready outcomes.",
    "Ordered implementation checklist covering discovery, data, backend, frontend, QA, operations, and release.",
    "Test routes for unit, integration, E2E, security, performance, reliability, privacy, and release validation.",
    "Future issues and deferred decisions with owners or decision deadlines.",
    "Hardware requirements when devices, sensors, wearables, buttons, or on-prem infrastructure are involved.",
    "Software concerns including framework, runtime, hosting, observability, security, privacy, and compliance.",
    "Framework and language recommendation with rationale when the user has no hard constraint.",
    "Database recommendation with schema direction, ownership boundaries, constraints, indexes, and migration strategy for new products.",
]

REVIEW_FOLLOW_UP_RULES = [
    (
        ("scope mismatch", "wrong product", "which product", "scope boundaries", "title claims"),
        "Reviewer flagged a possible product-scope mismatch. Which product are we building, and what is explicitly out of scope for v1?",
    ),
    (
        ("idor", "bola", "authorization", "ownership", "access rules", "public vs. private", "roles"),
        "Reviewer flagged access-control gaps. For each main thing users create, who should be able to see it, change it, delete it, or share it?",
    ),
    (
        ("authentication", "session", "jwt", "oauth", "csrf", "token", "login"),
        "Reviewer flagged login/session gaps. How should users log in, and when should the app ask them to log in again or end their session?",
    ),
    (
        ("harmful content", "moderation", "abuse response", "reporting", "takedown", "appeal"),
        "Reviewer flagged harmful-content gaps. What content should not be allowed, who can report it, who reviews reports, and can users appeal a decision?",
    ),
    (
        ("retention", "deletion", "export", "gdpr", "ccpa", "privacy", "personal data"),
        "Reviewer flagged privacy gaps. What user data should be kept, removed, restored, or downloadable, and are there cases where data must stay for legal or safety reasons?",
    ),
    (
        ("performance", "latency", "p95", "p99", "file size", "bandwidth", "capacity", "scale"),
        "Reviewer flagged speed/scale gaps. How fast should the app feel for key actions, what actions must not feel slow, and how many users or uploads should v1 comfortably handle?",
    ),
    (
        ("database", "postgresql", "mongodb", "schema", "migration", "indexes"),
        "Reviewer flagged data-structure gaps. What are the main things the app stores, who owns them, and should the planner recommend the database and technical data design?",
    ),
    (
        ("storage", "s3", "cdn", "infrastructure", "cloud", "multi-region", "disaster recovery"),
        "Reviewer flagged hosting/storage gaps. Should the planner recommend where the app runs and where files are stored, or do you have provider, backup, or region requirements?",
    ),
    (
        ("hardware", "device", "button", "wearable", "iot", "bluetooth", "sensor"),
        "Reviewer flagged hardware gaps. Does v1 require any physical device or special equipment, and if so what should users expect when setting it up, using it, or replacing it?",
    ),
    (
        ("framework", "technology", "tech stack", "language", "runtime"),
        "Reviewer flagged stack decisions. Should the planner recommend a framework/language/runtime/database stack, or are there hard technology constraints?",
    ),
    (
        ("milestone", "checklist", "order of implementation", "implementation order", "delivery plan"),
        "Reviewer flagged delivery-planning gaps. What must be built first, what can wait, and what would make you comfortable saying v1 is ready?",
    ),
]


@dataclass(frozen=True)
class DiscoveryAssessment:
    user_decisions: List[str]
    needs_user_input: List[str]
    assumed_defaults: List[str]
    readiness: str
    readiness_score: int
    readiness_reason: str


@dataclass(frozen=True)
class DiscoveryDimension:
    key: str
    prompt: str
    planning_label: str
    critical: bool = False
    markers: tuple[str, ...] = ()
    guidance: str | None = None


@dataclass(frozen=True)
class ReviewFollowUp:
    question: str
    evidence: str


@dataclass(frozen=True)
class DynamicQuestion:
    question: str
    reason: str = ""


DISCOVERY_DIMENSIONS = [
    DiscoveryDimension(
        key="knowledge_level",
        prompt="How technical are you? Choose one: non-technical, somewhat technical, or technical.",
        planning_label="User knowledge level for question tailoring",
    ),
    DiscoveryDimension(
        key="product_name",
        prompt="What do you plan to name this product?",
        planning_label="Product name",
    ),
    DiscoveryDimension(
        key="target_users",
        prompt="Who is this for, and what problem are they trying to solve?",
        planning_label="Target users and core problem",
        critical=True,
    ),
    DiscoveryDimension(
        key="product_narrative",
        prompt="Please explain the product, main workflows, and how it will make money in no fewer than 10 sentences.",
        planning_label="Product, workflow, and monetization narrative",
        critical=True,
    ),
    DiscoveryDimension(
        key="product_shape",
        prompt="Is this a brand-new product, or something added to an existing product?",
        planning_label="Product shape",
    ),
    DiscoveryDimension(
        key="primary_journey",
        prompt="In simple steps, what should the user do and what should happen next?",
        planning_label="Primary v1 user journey",
        critical=True,
    ),
    DiscoveryDimension(
        key="v1_scope",
        prompt="What must work in the first version, and what can wait until later?",
        planning_label="v1 scope and non-goals",
        critical=True,
        guidance=(
            "Recommended default: v1 should include only the main user journey, account/setup basics, "
            "essential safety/error handling, and operational visibility. Defer advanced analytics, "
            "automation, complex admin tools, and nonessential integrations."
        ),
    ),
    DiscoveryDimension(
        key="scale",
        prompt="How many people do you expect to use this in the first year?",
        planning_label="Expected first-year scale",
    ),
    DiscoveryDimension(
        key="sensitive_data",
        prompt="What personal, private, financial, health, or otherwise sensitive information is involved?",
        planning_label="Sensitive data and privacy expectations",
        guidance=(
            "Recommended default: assume sensitive data exists if users, contacts, payments, messages, "
            "location, identity, or health information are involved. Minimize collection, encrypt it, "
            "and define deletion/export expectations."
        ),
    ),
    DiscoveryDimension(
        key="failure_modes",
        prompt="What should happen when something goes wrong, such as no internet, a failed payment, or a third-party outage?",
        planning_label="Failure and degraded-mode behavior",
        guidance=(
            "Recommended default: tell the user what failed, keep their data safe, retry operations that are safe to retry, "
            "avoid duplicate side effects, and alert operators when a core workflow is affected."
        ),
    ),
    DiscoveryDimension(
        key="degraded_behavior",
        prompt="If part of the product is unavailable, should users see a blank/error screen, retry later, or still use limited read-only features?",
        planning_label="User-facing degraded-mode expectation",
        guidance=(
            "Recommended default: avoid a blank app. Show a clear error, preserve user data, retry safe operations, "
            "and allow read-only browsing for already available public content when that does not create safety or privacy risk."
        ),
    ),
    DiscoveryDimension(
        key="abuse_cases",
        prompt="How could someone misuse this product, or what would be especially harmful if it went wrong?",
        planning_label="Abuse and misuse scenarios",
    ),
    DiscoveryDimension(
        key="visibility_rules",
        prompt="For things users create, such as posts, images, collections, comments, likes, or projects, what should be public, private, or shareable by default?",
        planning_label="Visibility and sharing defaults",
        critical=True,
    ),
    DiscoveryDimension(
        key="moderation_rules",
        prompt="What content or behavior should not be allowed, who can report it, who reviews it, and can users appeal?",
        planning_label="Moderation and abuse response",
    ),
    DiscoveryDimension(
        key="data_deletion",
        prompt="What should happen when a user deletes content or an account: hide it, soft delete it, permanently delete it on request, or allow export/download?",
        planning_label="Deletion, retention, and export expectations",
    ),
    DiscoveryDimension(
        key="integrations",
        prompt="Does it need to connect to anything else, such as payments, maps, email, SMS, calendars, devices, or AI models?",
        planning_label="External integrations",
    ),
    DiscoveryDimension(
        key="monetization_model",
        prompt="How should this product make money in v1 or later: subscriptions, one-time payments, commissions, ads, paid profiles, marketplace fees, enterprise plans, or free at first?",
        planning_label="Monetization model",
        critical=True,
    ),
    DiscoveryDimension(
        key="tech_stack",
        prompt="Do you care what technology is used, or should the planner recommend a practical default?",
        planning_label="Technology constraints or recommendation",
        guidance=(
            "Recommended default: use a mainstream stack with strong ecosystem support, automated tests, "
            "managed hosting, a relational database, and simple local development. The exact choice should follow the product type."
        ),
    ),
    DiscoveryDimension(
        key="success_criteria",
        prompt="How will you know version 1 is good enough to launch?",
        planning_label="Launch and acceptance criteria",
        critical=True,
        guidance=(
            "Recommended default: launch only when the main user journey works end to end, critical security issues are closed, "
            "known failures have clear behavior, monitoring is live, and rollback has been tested."
        ),
    ),
    DiscoveryDimension(
        key="launch_comfort",
        prompt="What would make you comfortable saying v1 is ready: specific workflows working, no serious abuse risk, acceptable speed, payment readiness, moderation coverage, or something else?",
        planning_label="Launch comfort criteria",
        critical=True,
    ),
    DiscoveryDimension(
        key="api_entities",
        prompt="What are the main things the system manages, and who owns or can change them?",
        planning_label="Domain entities and ownership boundaries",
        markers=("api", "platform", "saas", "service"),
    ),
    DiscoveryDimension(
        key="ai_constraints",
        prompt="What should the AI be allowed to do, and what should it never do automatically?",
        planning_label="AI/provider constraints",
        markers=("ai", "agent", "llm", "model"),
    ),
    DiscoveryDimension(
        key="financial_controls",
        prompt="Where could money, invoices, balances, or payment status be wrong, and how should that be checked?",
        planning_label="Financial correctness controls",
        markers=("payment", "billing", "invoice", "fintech"),
    ),
    DiscoveryDimension(
        key="regulated_data",
        prompt="Are there health, medical, legal, child-safety, workplace, or regulated-data concerns?",
        planning_label="Regulated-data handling",
        markers=("health", "medical", "patient", "legal", "child"),
    ),
    DiscoveryDimension(
        key="device_lifecycle",
        prompt="If there is a physical device, how is it paired, trusted, disconnected, reconnected, or replaced?",
        planning_label="Device lifecycle",
        markers=("button", "hardware", "device", "wearable", "iot", "ble", "bluetooth"),
    ),
    DiscoveryDimension(
        key="escalation_flow",
        prompt="If alerts or emergencies are involved, who gets notified, when, and what happens if nobody responds?",
        planning_label="Alert/escalation flow",
        markers=("alert", "panic", "emergency", "safety", "incident"),
    ),
    DiscoveryDimension(
        key="location_controls",
        prompt="If location is involved, when is it collected, who sees it, and how long is it kept?",
        planning_label="Location collection and retention",
        markers=("location", "tracking", "gps"),
    ),
]

QUESTION_BANK = [dimension.prompt for dimension in DISCOVERY_DIMENSIONS if not dimension.markers]

RESEARCH_DISCOVERY_DIMENSIONS = [
    DiscoveryDimension(
        key="knowledge_level",
        prompt="How familiar are you with this research area? Choose one: beginner, familiar, or expert.",
        planning_label="Research-area familiarity for question tailoring",
    ),
    DiscoveryDimension(
        key="project_name",
        prompt="What is the working title or short name for this research project?",
        planning_label="Research project title",
    ),
    DiscoveryDimension(
        key="research_area",
        prompt="What research area, field, or subfield does this project belong to?",
        planning_label="Research area and subfield",
        critical=True,
    ),
    DiscoveryDimension(
        key="research_problem",
        prompt="What problem, gap, or uncertainty should this research investigate?",
        planning_label="Research problem or gap",
        critical=True,
    ),
    DiscoveryDimension(
        key="research_question",
        prompt="What is the main research question you want to answer?",
        planning_label="Main research question",
        critical=True,
    ),
    DiscoveryDimension(
        key="hypothesis",
        prompt="What hypothesis, claim, or expected contribution should the research test?",
        planning_label="Hypothesis or expected contribution",
        critical=True,
    ),
    DiscoveryDimension(
        key="related_work",
        prompt="What related work, existing methods, products, papers, or baselines do you already know about?",
        planning_label="Known related work and baselines",
    ),
    DiscoveryDimension(
        key="novelty",
        prompt="What do you believe is new, different, or worth publishing about this idea?",
        planning_label="Novelty and contribution angle",
        critical=True,
    ),
    DiscoveryDimension(
        key="methodology",
        prompt="What method, prototype, analysis, model, system, survey, or study do you expect to use?",
        planning_label="Planned methodology",
        critical=True,
    ),
    DiscoveryDimension(
        key="data_sources",
        prompt="What data, participants, systems, documents, logs, benchmarks, or examples will the research need?",
        planning_label="Data sources or study material",
    ),
    DiscoveryDimension(
        key="evaluation",
        prompt="How should the research be evaluated: experiments, user study, case study, benchmark, statistical test, qualitative analysis, or another approach?",
        planning_label="Evaluation approach",
        critical=True,
    ),
    DiscoveryDimension(
        key="metrics",
        prompt="What outcomes or metrics would show that the claim is supported?",
        planning_label="Evaluation metrics and success evidence",
    ),
    DiscoveryDimension(
        key="constraints",
        prompt="What constraints exist: time, compute, budget, data access, ethics approval, team skills, or publication deadline?",
        planning_label="Research constraints",
    ),
    DiscoveryDimension(
        key="ethics",
        prompt="Could this involve human subjects, sensitive data, privacy risk, security risk, bias, or possible misuse?",
        planning_label="Ethics, privacy, safety, and misuse risks",
    ),
    DiscoveryDimension(
        key="reproducibility",
        prompt="What should be reproducible or shared: code, data, prompts, models, environment, scripts, or experiment logs?",
        planning_label="Reproducibility and artifact expectations",
    ),
    DiscoveryDimension(
        key="target_output",
        prompt="What is the desired output: paper, thesis chapter, prototype, benchmark, dataset, survey, grant proposal, or internal research report?",
        planning_label="Target research output",
        critical=True,
    ),
    DiscoveryDimension(
        key="target_venue",
        prompt="Do you have a target conference, journal, course, supervisor, company audience, or review standard?",
        planning_label="Target venue or review standard",
    ),
]

RESEARCH_QUESTION_BANK = [dimension.prompt for dimension in RESEARCH_DISCOVERY_DIMENSIONS if not dimension.markers]


def _prompt_for(key: str) -> str:
    for dimension in DISCOVERY_DIMENSIONS:
        if dimension.key == key:
            return dimension.prompt
    raise KeyError(key)


def _research_prompt_for(key: str) -> str:
    for dimension in RESEARCH_DISCOVERY_DIMENSIONS:
        if dimension.key == key:
            return dimension.prompt
    raise KeyError(key)


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "idea"


def product_name_from_answers(idea: str, answers: Dict[str, str]) -> str:
    product_name = answers.get(_prompt_for("product_name"), "").strip()
    if product_name and not _is_low_signal(product_name):
        return product_name
    return idea


def research_project_name_from_answers(topic: str, answers: Dict[str, str]) -> str:
    project_name = answers.get(_research_prompt_for("project_name"), "").strip()
    if project_name and not _is_low_signal(project_name):
        return project_name
    return topic


def generate_questions(idea: str, answers: Dict[str, str] | None = None) -> List[str]:
    existing_answers = answers or {}
    lower_idea = idea.lower()

    selected: List[str] = []
    for dimension in DISCOVERY_DIMENSIONS:
        if dimension.markers and not any(marker in lower_idea for marker in dimension.markers):
            continue
        if dimension.prompt not in existing_answers:
            selected.append(dimension.prompt)

    return selected


def generate_research_questions(topic: str, answers: Dict[str, str] | None = None) -> List[str]:
    existing_answers = answers or {}
    lower_topic = topic.lower()

    selected: List[str] = []
    for dimension in RESEARCH_DISCOVERY_DIMENSIONS:
        if dimension.markers and not any(marker in lower_topic for marker in dimension.markers):
            continue
        if dimension.prompt not in existing_answers:
            selected.append(dimension.prompt)

    return selected


def normalize_dynamic_research_questions(raw_items: object, max_questions: int = 6) -> List[DynamicQuestion]:
    if not isinstance(raw_items, list):
        return []

    questions: List[DynamicQuestion] = []
    seen: set[str] = set()
    baseline = {_normalize_question_key(question) for question in RESEARCH_QUESTION_BANK}

    for item in raw_items:
        reason = ""
        if isinstance(item, str):
            question = item
        elif isinstance(item, dict):
            question = str(item.get("question", ""))
            reason = str(item.get("reason", ""))
        else:
            continue

        cleaned = _clean_dynamic_question(question)
        if not cleaned:
            continue
        key = _normalize_question_key(cleaned)
        if key in seen or key in baseline:
            continue
        seen.add(key)
        questions.append(DynamicQuestion(question=cleaned, reason=reason.strip()))
        if len(questions) >= max_questions:
            break

    return questions


def merge_research_questions(static_questions: List[str], dynamic_questions: List[DynamicQuestion]) -> List[str]:
    merged = list(static_questions)
    seen = {_normalize_question_key(question) for question in merged}
    for dynamic_question in dynamic_questions:
        key = _normalize_question_key(dynamic_question.question)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dynamic_question.question)
    return merged


def _clean_dynamic_question(question: str) -> str:
    cleaned = " ".join(question.strip().split())
    if not cleaned:
        return ""
    if len(cleaned) > 220:
        return ""
    if not cleaned.endswith("?"):
        return ""
    lowered = cleaned.lower()
    blocked_markers = (
        "ignore previous",
        "system prompt",
        "developer message",
        "api key",
        "secret",
        "password",
        "token",
        "execute",
        "shell",
    )
    if any(marker in lowered for marker in blocked_markers):
        return ""
    return cleaned


def _normalize_question_key(question: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()


def should_ask_follow_up(answer: str) -> bool:
    normalized = answer.strip().lower()
    if not normalized:
        return True
    return normalized in LOW_SIGNAL_ANSWERS


def sentence_count(answer: str) -> int:
    return len([part for part in re.split(r"[.!?]+", answer.strip()) if part.strip()])


def needs_detail_for_question(question: str, answer: str) -> bool:
    if question == _prompt_for("product_narrative"):
        return sentence_count(answer) < 10
    if question == _research_prompt_for("research_problem"):
        return sentence_count(answer) < 3
    return False


def detail_follow_up_for(question: str, answer: str) -> str:
    if question == _prompt_for("product_narrative"):
        remaining = max(10 - sentence_count(answer), 1)
        return (
            "Please expand this answer with at least "
            f"{remaining} more sentence{'s' if remaining != 1 else ''}. "
            "Cover the product, main user workflows, buyer/customer, pricing or revenue model, and why users would pay or engage."
        )
    if question == _research_prompt_for("research_problem"):
        remaining = max(3 - sentence_count(answer), 1)
        return (
            "Please expand this answer with at least "
            f"{remaining} more sentence{'s' if remaining != 1 else ''}. "
            "Cover the research gap, why it matters, and what would make the answer useful."
        )
    return follow_up_for(question)


def user_knowledge_level(answers: Dict[str, str]) -> str:
    answer = answers.get(
        _prompt_for("knowledge_level"),
        answers.get(_research_prompt_for("knowledge_level"), ""),
    ).strip().lower()
    if any(marker in answer for marker in ("non", "beginner", "business", "founder", "not technical")):
        return "non-technical"
    if any(marker in answer for marker in ("some", "medium", "moderate")):
        return "somewhat technical"
    if any(marker in answer for marker in ("technical", "engineer", "developer", "architect", "expert")):
        return "technical"
    if any(marker in answer for marker in ("familiar", "researcher", "academic")):
        return "somewhat technical"
    return "unknown"


def display_question_for_user(question: str, answers: Dict[str, str]) -> str:
    level = user_knowledge_level(answers)
    is_research_question = question in {dimension.prompt for dimension in RESEARCH_DISCOVERY_DIMENSIONS}
    if question in {
        _prompt_for("knowledge_level"),
        _prompt_for("product_name"),
        _research_prompt_for("knowledge_level"),
        _research_prompt_for("project_name"),
    }:
        return question

    if level == "non-technical":
        if is_research_question:
            return (
                f"{question}\n"
                "Answer in plain research terms. You do not need to know statistics, methodology, or publication terminology."
            )
        return (
            f"{question}\n"
            "Answer in plain product/business terms. You do not need to know testing, security, database, or infrastructure terminology."
        )
    if level == "somewhat technical":
        if is_research_question:
            return (
                f"{question}\n"
                "Use research goals first. Add methods, datasets, metrics, or venue constraints only where you already know them."
            )
        return (
            f"{question}\n"
            "Use product terms first. Add technical preferences only where you already know them."
        )
    if level == "technical":
        if is_research_question:
            return (
                f"{question}\n"
                "Include relevant research constraints, methodology, data, metrics, baselines, or validity concerns if you know them."
            )
        return (
            f"{question}\n"
            "Include relevant technical constraints, protocols, data ownership, scale, or operational requirements if you know them."
        )
    return question


def wants_agent_guidance(answer: str) -> bool:
    normalized = answer.strip().lower()
    return any(marker in normalized for marker in GUIDANCE_REQUEST_MARKERS)


def guidance_for(question: str, idea: str) -> str | None:
    lowered_question = question.lower()
    lowered_idea = idea.lower()

    if "technology" in lowered_question or "tech stack" in lowered_question or "language" in lowered_question:
        if any(marker in lowered_idea for marker in ["ios", "android", "mobile", "app", "button", "device"]):
            return (
                "Recommended default: React Native for the mobile app, TypeScript for shared client code, "
                "Python FastAPI for the backend, PostgreSQL for relational data, Redis for queues/rate limits, "
                "and a managed cloud such as AWS or GCP. Rationale: one shared mobile codebase for iOS/Android, "
                "strong backend productivity, mature database constraints, and enough operational support for v1."
            )
        if any(marker in lowered_idea for marker in ["ai", "agent", "llm"]):
            return (
                "Recommended default: Python FastAPI backend, PostgreSQL, Redis, React/TypeScript frontend, "
                "and managed cloud deployment. Rationale: Python has the strongest AI integration ecosystem, "
                "while Postgres and Redis cover durable state, queues, caching, and rate limits."
            )
        return (
            "Recommended default: TypeScript React frontend, Python FastAPI backend, PostgreSQL database, "
            "Redis for async work/rate limits, Docker for local development, and managed cloud deployment. "
            "Rationale: this is a pragmatic default for a new product with good hiring, tooling, and test support."
        )

    if "first year" in lowered_question or "how many people" in lowered_question:
        return (
            "Recommended default: for an early v1 plan, size for the first realistic launch cohort plus headroom. "
            "If the number is unknown, assume a small beta first, then a first-year target such as 1k, 10k, or 100k users."
        )

    if "performance goals" in lowered_question or "latency" in lowered_question:
        return (
            "Recommended default: set p95 user-facing API latency below 500ms, p95 background job start below "
            "5 seconds, and define stricter targets for safety-critical or payment-critical workflows. "
            "Rationale: it gives engineering a measurable baseline without pretending we know production traffic yet."
        )

    if "availability" in lowered_question or "reliability" in lowered_question:
        return (
            "Recommended default: target 99.9% availability for v1, document degraded-mode behavior, and alert on "
            "core workflow failures. Rationale: it is achievable for an early product while still forcing operational discipline."
        )

    if "compliance" in lowered_question or "security constraints" in lowered_question:
        return (
            "Recommended default: assume PII is present, apply GDPR/CCPA-style deletion/export expectations, encrypt "
            "sensitive data, and keep audit logs for sensitive mutations. Rationale: this avoids under-scoping privacy "
            "and security before legal review."
        )

    if "first version" in lowered_question or "wait until later" in lowered_question or "out of scope" in lowered_question:
        return (
            "Recommended default: keep v1 limited to the primary workflow, account setup, basic admin/support tooling, "
            "observability, and release safety. Defer advanced automation, analytics, complex role models, and nonessential "
            "integrations. Rationale: v1 should prove the core value before expanding surface area."
        )

    if "good enough to launch" in lowered_question or "acceptance criteria" in lowered_question or "launch criteria" in lowered_question:
        return (
            "Recommended default: launch only when the primary user journey passes E2E tests, no critical security issues "
            "remain, core workflows meet agreed latency/reliability targets, rollback is tested, and known risks have owners. "
            "Rationale: acceptance criteria must be measurable enough to block an unsafe launch."
        )

    return None


def hardware_requirements_for(idea: str, answers: Dict[str, str]) -> List[str]:
    combined_context = " ".join([idea, *answers.values()]).lower()
    has_hardware = any(marker in combined_context for marker in HARDWARE_MARKERS)

    if has_hardware:
        return [
            "Hardware is in scope and must be specified before implementation starts.",
            "Define device model, pairing/trust lifecycle, disconnect/reconnect behavior, replacement flow, firmware/update path, battery expectations, connectivity requirements, and test hardware inventory.",
            "If the product can run without the device, define degraded behavior and user messaging.",
        ]

    return [
        "No dedicated hardware is required for v1.",
        "Users need only standard client devices: desktop browser and/or mobile phone depending on the chosen frontend.",
        "No pairing, firmware, battery, sensor, wearable, or physical-device inventory is required.",
    ]


def follow_up_for(question: str) -> str:
    return f"Please add concrete detail for: {question}"


def _is_low_signal(value: str) -> bool:
    return value.strip().lower() in LOW_SIGNAL_ANSWERS


def _dedupe(items: List[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def generate_review_follow_up_questions(review_texts: List[str], max_questions: int = 6) -> List[ReviewFollowUp]:
    selected: List[ReviewFollowUp] = []
    seen_questions: set[str] = set()
    lowered_reviews = "\n".join(review_texts).lower()

    for markers, question in REVIEW_FOLLOW_UP_RULES:
        if question in seen_questions:
            continue
        if not any(marker in lowered_reviews for marker in markers):
            continue
        evidence = _first_matching_review_line(review_texts, markers)
        selected.append(ReviewFollowUp(question=question, evidence=evidence))
        seen_questions.add(question)
        if len(selected) >= max_questions:
            break

    return selected


def _first_matching_review_line(review_texts: List[str], markers: tuple[str, ...]) -> str:
    for review in review_texts:
        for raw_line in review.splitlines():
            line = raw_line.strip()
            lowered_line = line.lower()
            if line and any(marker in lowered_line for marker in markers):
                return line.lstrip("- ").strip()
    return "Reviewer raised this topic in the iteration comments."


def append_review_clarifications(
    current_plan_md: str,
    iteration: int,
    clarifications: Dict[str, str],
    evidence_by_question: Dict[str, str],
) -> str:
    if not clarifications:
        return current_plan_md

    lines = [
        "",
        f"## Review-Driven User Clarifications - Iteration {iteration}",
        "- These answers were requested after reviewer-agent comments and must be integrated before the next iteration.",
        "- User answers are product expectations; the planner is responsible for translating them into engineering defaults, test routes, security controls, and implementation details.",
    ]
    for question, answer in clarifications.items():
        evidence = evidence_by_question.get(question, "Reviewer raised this topic in the iteration comments.")
        lines.append(f"- **Reviewer comment:** {evidence}")
        lines.append(f"- **Question:** {question}")
        lines.append(f"- **User answer:** {answer}")

    return current_plan_md.strip() + "\n" + "\n".join(lines) + "\n"


def assess_discovery(idea: str, answers: Dict[str, str]) -> DiscoveryAssessment:
    questions = _dedupe(generate_questions(idea, {}))
    user_decisions: List[str] = []
    needs_user_input: List[str] = []

    for question in questions:
        answer = answers.get(question, "Not specified")
        if _is_low_signal(answer):
            needs_user_input.append(question)
        else:
            user_decisions.append(f"{question} {answer}")

    answered_count = len(user_decisions)
    total_count = len(questions) or 1
    readiness_score = round((answered_count / total_count) * 100)
    critical_prompts = {dimension.prompt for dimension in DISCOVERY_DIMENSIONS if dimension.critical}
    critical_missing = [q for q in needs_user_input if q in critical_prompts]

    if critical_missing:
        readiness = "NOT READY"
        readiness_reason = "Critical product decisions are unresolved."
    elif needs_user_input:
        readiness = "CONDITIONAL"
        readiness_reason = "Enough exists for a draft plan, but product gaps must be resolved."
    else:
        readiness = "READY"
        readiness_reason = "Discovery answers cover the required planning inputs."

    return DiscoveryAssessment(
        user_decisions=user_decisions,
        needs_user_input=needs_user_input,
        assumed_defaults=ENGINEERING_DEFAULTS,
        readiness=readiness,
        readiness_score=readiness_score,
        readiness_reason=readiness_reason,
    )


def assess_research_discovery(topic: str, answers: Dict[str, str]) -> DiscoveryAssessment:
    questions = _dedupe(generate_research_questions(topic, {}))
    user_decisions: List[str] = []
    needs_user_input: List[str] = []

    for question in questions:
        answer = answers.get(question, "Not specified")
        if _is_low_signal(answer):
            needs_user_input.append(question)
        else:
            user_decisions.append(f"{question} {answer}")

    answered_count = len(user_decisions)
    total_count = len(questions) or 1
    readiness_score = round((answered_count / total_count) * 100)
    critical_prompts = {dimension.prompt for dimension in RESEARCH_DISCOVERY_DIMENSIONS if dimension.critical}
    critical_missing = [q for q in needs_user_input if q in critical_prompts]

    if critical_missing:
        readiness = "NOT READY"
        readiness_reason = "Critical research-design decisions are unresolved."
    elif needs_user_input:
        readiness = "CONDITIONAL"
        readiness_reason = "Enough exists for a draft research plan, but research-design gaps remain."
    else:
        readiness = "READY"
        readiness_reason = "Discovery answers cover the required research-planning inputs."

    assumed_defaults = [
        "Assumed Default: Do not invent citations; related-work gaps become literature-search tasks.",
        "Assumed Default: Evaluation must include explicit baselines, metrics, and validity threats.",
        "Assumed Default: Research involving people, sensitive data, or possible harm requires ethics/privacy review before data collection.",
        "Assumed Default: Reproducibility includes pinned environment, documented data processing, seeds where applicable, and experiment logs.",
        "Assumed Default: Claims must be traceable to evidence, statistical tests, qualitative coding, or clearly labeled assumptions.",
    ]

    return DiscoveryAssessment(
        user_decisions=user_decisions,
        needs_user_input=needs_user_input,
        assumed_defaults=assumed_defaults,
        readiness=readiness,
        readiness_score=readiness_score,
        readiness_reason=readiness_reason,
    )


def build_initial_research_plan(topic: str, answers: Dict[str, str]) -> str:
    assessment = assess_research_discovery(topic, answers)
    label_by_prompt = {dimension.prompt: dimension.planning_label for dimension in RESEARCH_DISCOVERY_DIMENSIONS}

    lines = [
        f"# Research Plan: {topic}",
        "",
        "## 1. Research Framing",
        f"- Raw topic or hypothesis: {topic}",
        "- Goal: convert the research idea into a concrete research execution plan with questions, methods, evidence, risks, and deliverables.",
        "",
        "## 2. Discovery Conversation",
    ]
    for q, a in answers.items():
        lines.append(f"- **{q}** {a}")

    lines.extend(
        [
            "",
            "## 3. Research Contract",
            "- Research gaps must be made explicit instead of silently converted into product assumptions.",
            "- Literature, baselines, datasets, ethics, and evaluation choices are first-class planning inputs.",
            "- Reviewers must not invent specific citations; unknown prior work becomes a search task.",
            "- The final plan must distinguish hypotheses, assumptions, evidence needed, and open risks.",
            "",
            "## 4. Readiness Gate",
            f"- Status: {assessment.readiness}",
            f"- Score: {assessment.readiness_score}/100",
            f"- Reason: {assessment.readiness_reason}",
            "",
            "## 5. Confirmed Research Decisions",
        ]
    )
    if assessment.user_decisions:
        for item in assessment.user_decisions:
            prompt, _, answer = item.partition("? ")
            label = label_by_prompt.get(prompt + "?", prompt)
            lines.append(f"- {label}: {answer if answer else item}")
    else:
        lines.append("- No validated research decisions yet.")

    lines.extend(["", "## 6. Assumed Research Defaults"])
    for default in assessment.assumed_defaults:
        lines.append(f"- {default}")

    lines.extend(["", "## 7. Needs Research Input"])
    if assessment.needs_user_input:
        for item in assessment.needs_user_input:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## 8. Research Questions and Hypotheses",
            "- Define the primary research question in falsifiable or answerable terms.",
            "- Define secondary questions only if they support the primary contribution.",
            "- Map each hypothesis or claim to the evidence required to support it.",
            "",
            "## 9. Related Work and Baseline Search Plan",
            "- Identify keywords, venues, authors, products, datasets, and baseline methods to search.",
            "- Record closest prior work and explain the novelty boundary against each baseline.",
            "- Do not claim novelty until the search has been completed and summarized.",
            "",
            "## 10. Methodology",
            "- Specify the method, prototype, model, survey, study protocol, analysis, or system to build or examine.",
            "- Define variables, controls, assumptions, and operational definitions.",
            "- Identify confounders and decisions that could bias the results.",
            "",
            "## 11. Data, Participants, and Materials",
            "- List required datasets, participant groups, logs, documents, benchmarks, prompts, or systems.",
            "- Define acquisition, cleaning, labeling, consent, licensing, access control, and retention expectations.",
            "- Define train/validation/test or sampling strategy where applicable.",
            "",
            "## 12. Evaluation Design",
            "- Select baselines, controls, ablations, case studies, user tasks, or comparison groups.",
            "- Define primary and secondary metrics before running experiments.",
            "- Define statistical tests, confidence intervals, effect sizes, or qualitative coding methods where applicable.",
            "",
            "## 13. Validity, Ethics, and Risk",
            "- Internal validity: confounders, leakage, implementation bias, measurement error.",
            "- External validity: generalization limits, dataset representativeness, domain transfer.",
            "- Construct validity: whether metrics and observations actually measure the claimed concept.",
            "- Ethics/privacy/safety: human-subjects review, sensitive data, consent, bias, misuse, and disclosure boundaries.",
            "",
            "## 14. Reproducibility and Artifact Plan",
            "- Pin code, dependencies, data-processing scripts, random seeds, prompts, model versions, and hardware assumptions.",
            "- Track experiment configs, raw outputs, analysis notebooks, and final result tables.",
            "- Decide what can be released publicly and what must remain private or synthetic.",
            "",
            "## 15. Work Plan",
            "1. Finalize research question, hypothesis, contribution, and target output.",
            "2. Run literature and baseline search; summarize closest prior work.",
            "3. Lock methodology, datasets/materials, ethics requirements, and evaluation protocol.",
            "4. Build prototype, collection pipeline, benchmark harness, survey, or analysis workflow.",
            "5. Run pilot study or dry-run experiments and adjust only pre-declared protocol issues.",
            "6. Run final evaluation, statistical/qualitative analysis, and validity review.",
            "7. Write paper/report with limitations, reproducibility notes, and artifact appendix.",
            "",
            "## 16. Acceptance Criteria",
            "- Research question is specific enough that reviewers can tell whether it was answered.",
            "- Related-work search identifies closest baselines and novelty risks.",
            "- Evaluation protocol directly tests the main claim.",
            "- Ethics/privacy risks are reviewed before data collection or deployment.",
            "- Results are reproducible enough for the target output or venue.",
            "",
            "## 17. Review Handoff",
            "- Reviewer agents should challenge novelty, methodology, evaluation, statistics, validity, reproducibility, ethics, and writing clarity.",
            "- Reviewer agents should identify missing research-design decisions as questions, not silently invent results or citations.",
            "- Arbitrator should produce a concrete research execution plan, not a product launch plan.",
            "",
            "## 18. Open Risks",
            "- Literature search may reveal the contribution is not novel.",
            "- Data or participant access may be unavailable or biased.",
            "- Evaluation may not support the claimed contribution.",
            "- Ethics, privacy, or misuse risks may require scope changes.",
        ]
    )

    return "\n".join(lines) + "\n"


def build_initial_plan(idea: str, answers: Dict[str, str]) -> str:
    product_shape = answers.get(
        _prompt_for("product_shape"),
        answers.get("Is this a net-new product or an addition to an existing system?", "Not specified"),
    ).lower()
    is_new_product = "yes" if "new" in product_shape else "no"
    assessment = assess_discovery(idea, answers)

    lines = [
        f"# Implementation Plan: {idea}",
        "",
        "## 1. Idea Development",
        f"- Raw idea: {idea}",
        "- Goal: convert the idea into a concrete v1 implementation plan with known risks, assumptions, and open decisions.",
        "",
        "## 2. Discovery Conversation",
    ]
    for q, a in answers.items():
        lines.append(f"- **{q}** {a}")

    lines.extend(
        [
            "",
            "## 3. Discovery Contract",
            "- Product/feature gaps must be confirmed with the user before planning is marked READY.",
            "- Engineering gaps are filled with assumed defaults and kept reviewable.",
            "- The plan can still be drafted while CONDITIONAL, but unresolved product decisions remain blockers.",
            "- After the first review iteration, reviewer comments that expose user-owned product decisions must be converted into user questions before consolidation continues.",
            "",
            "## 4. Readiness Gate",
            f"- Status: {assessment.readiness}",
            f"- Score: {assessment.readiness_score}/100",
            f"- Reason: {assessment.readiness_reason}",
            "",
            "## 5. User Decisions",
        ]
    )
    if assessment.user_decisions:
        label_by_prompt = {dimension.prompt: dimension.planning_label for dimension in DISCOVERY_DIMENSIONS}
        for item in assessment.user_decisions:
            prompt, _, answer = item.partition("? ")
            label = label_by_prompt.get(prompt + "?", prompt)
            lines.append(f"- {label}: {answer if answer else item}")
    else:
        lines.append("- No validated product decisions yet.")

    lines.extend(["", "## 6. Assumed Engineering Defaults"])
    for default in assessment.assumed_defaults:
        lines.append(f"- {default}")

    lines.extend(["", "## 7. Needs User Input"])
    if assessment.needs_user_input:
        for item in assessment.needs_user_input:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## 8. Architecture Overview",
            "- Define service boundaries, API contracts, and data ownership early.",
            "- Prefer explicit authorization checks in service layer plus database constraints.",
            "",
            "## 9. Risk Assessment",
            "- Security risk: insufficient object-level authorization can cause IDOR/BOLA.",
            "- Product risk: unclear scope can create delivery churn.",
            "- Operational risk: missing observability and runbooks can slow incident response.",
            "",
            "## 10. Future Concerns",
            "- Versioning strategy for API and schema evolution.",
            "- Backward compatibility during iterative releases.",
            "- Cost management as traffic and data grow.",
            "",
            "## 11. Performance Considerations",
            "- Define p95/p99 latency targets per core endpoint.",
            "- Add caching/indexing strategy with invalidation ownership.",
            "- Plan load tests with production-like data shape.",
            "",
            "## 12. Security Concerns",
            "- Threat model covering authentication, authorization, and data exposure.",
            "- Add object-level access rules for every resource type.",
            "- Enforce audit trails for sensitive mutations.",
            "",
            "## 13. Test Plan",
        ]
    )
    for item in TEST_MATRIX:
        lines.append(f"- [ ] {item}")

    lines.extend(
        [
            "",
            "## 13.1 Test Routes",
            "- Unit route: run domain, validation, permission, and edge-case tests locally and in CI.",
            "- Integration route: test API/database/provider flows against disposable environments with migrations applied.",
            "- E2E route: execute the primary v1 journey plus critical failure and rollback paths.",
            "- Security route: run IDOR/BOLA, auth/session, replay, secrets, and sensitive-data exposure tests.",
            "- Performance route: load-test core endpoints and background jobs against explicit p95/p99 thresholds.",
            "- Release route: run smoke tests, rollback verification, alert checks, and post-deploy health validation.",
        ]
    )

    lines.extend(
        [
            "",
            "## 14. Detailed Implementation Checklist",
        ]
    )
    for item in IMPLEMENTATION_CHECKLIST:
        lines.append(f"- [ ] {item}")

    lines.extend(
        [
            "",
            "## 15. Workstream Breakdown",
            "- Discovery and product: finalize v1 scope, non-goals, user journeys, acceptance criteria, and unresolved product decisions.",
            "- Data and backend: model owned resources, migrations, APIs, authz policy, idempotency, audit events, and provider integrations.",
            "- Client experience: implement core screens, primary workflow, settings/configuration, permissions prompts, and degraded states.",
            "- Security and privacy: threat model, access matrix, retention/deletion behavior, encryption, logging boundaries, and abuse prevention.",
            "- Quality and operations: test automation, load tests, dashboards, alerts, runbooks, release gates, and rollback.",
            "",
            "## 16. Launch Readiness Checklist",
        ]
    )
    for item in LAUNCH_CHECKLIST:
        lines.append(f"- [ ] {item}")

    lines.extend(
        [
            "",
            "## 17. Milestones and Implementation Order",
            "1. Confirm scope, user-owned review questions, success criteria, and non-goals.",
            "2. Lock architecture, stack, database choice, hardware assumptions, and security model.",
            "3. Build domain model, migrations, ownership constraints, and API contracts.",
            "4. Implement backend services, auth/session controls, authorization matrix, and audit events.",
            "5. Implement frontend/client workflows, device flows if applicable, and degraded states.",
            "6. Add test routes, observability, runbooks, release gates, and rollback verification.",
            "7. Run final review iteration and close or explicitly defer remaining future issues.",
            "",
            "## 18. Database Schema (Initial Draft)",
        ]
    )
    lines.extend(
        [
            "- `users(id, account_identifier, role_or_type, created_at, updated_at)`",
            "- `domain_entities(...)` derived from confirmed workflow/entities.",
            "- `domain_events(...)` for state transitions and auditability.",
            "- Add foreign keys, unique constraints, and owner/tenant scoping indexes.",
        ]
    )
    lines.extend(
        [
            "",
            "## 19. Framework, Software, and Database Recommendations",
            "- Preferred stack constraints from input: "
            + answers.get(
                _prompt_for("tech_stack"),
                answers.get(
                    "Do you have preferred tech stack constraints (language, framework, database, cloud)?",
                    "Not specified",
                ),
            ),
            "- Document rationale for selected language/framework/runtime.",
            "- For new products, recommend a database explicitly and explain fit against data shape, ownership rules, consistency needs, migration safety, and operating complexity.",
            "- Capture software concerns: hosting, CI/CD, observability, privacy/security controls, dependency management, secrets, backups, and rollback.",
            "",
            "## 20. Hardware Requirements",
        ]
    )
    for item in hardware_requirements_for(idea, answers):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 21. Frontend",
            "- Define core screens, state model, and client-side authz handling.",
            "- Add error-state UX for timeout/degraded scenarios.",
            "",
            "## 22. Backend",
            "- Define endpoint contracts, authorization policy checks, and idempotency behavior.",
            "- Add structured logging, tracing, and metrics from day 1.",
        ]
    )

    if is_new_product == "yes":
        lines.extend(
            [
                "",
                "## 23. Docker and Delivery (New Product)",
                "- Multi-stage Docker build with pinned base image and SBOM generation.",
                "- Local docker-compose for app + database + observability stack.",
                "- CI pipeline: lint, test, security scan, build, push, deploy.",
            ]
        )

    lines.extend(
        [
            "",
            "## 24. Final Deliverable Requirements",
            "The final plan must include:",
        ]
    )
    for item in FINAL_DELIVERABLE_SECTIONS:
        lines.append(f"- [ ] {item}")

    lines.extend(
        [
            "",
            "## 25. Review Handoff",
            "- Reviewer agents should check whether the plan follows from the discovered user intent.",
            "- Reviewer agents should challenge risks, missing acceptance criteria, weak security controls, and vague future concerns.",
            "- Reviewer agents should identify user-owned decisions as questions, not silently invent product scope.",
            "",
            "## 26. Open Concerns",
            "- Clarify ownership for cross-cutting concerns (security, migrations, incident response).",
            "- Confirm launch guardrails and rollback strategy.",
        ]
    )

    return "\n".join(lines) + "\n"
