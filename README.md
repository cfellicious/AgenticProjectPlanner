# Agentic AI Planner for Ideation

Turn a raw product idea or research topic into an actionable implementation plan, or critique an existing implementation plan through software-architect reviewer agents.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 src/inspector.py --idea "A B2B billing platform for freelancers" --iterations 2
```

Critique an existing implementation plan:

```bash
python3 src/inspector.py --plan-file plans/implementation-plan-inspector-plan.md --iterations 2
```

Start from a research topic or product hypothesis:

```bash
python3 src/inspector.py --research "Research whether a privacy-first photo sharing app is viable" --iterations 2
```

Add Obsidian idea-note context:

```bash
python3 src/inspector.py --idea "A B2B billing platform for freelancers" --obsidian-idea-file ~/Vault/Ideas/Billing.md
```

## What it does

The project supports three workflows:

1. **Idea-to-plan workflow**: turn a raw product idea into a structured implementation plan, then harden it through reviewer-agent critique.
2. **Existing-plan architect critique workflow**: take an implementation plan markdown file and have configurable reviewer agents behave as senior software architects who critique architecture, performance, security, edge cases, and testing gaps. The arbitrator produces the revised final document.
3. **Research-to-plan workflow**: take a research topic, early product hypothesis, market question, or product idea that needs research framing, then run the planning and architect-review pipeline with a research-specific agent configuration.

The idea-to-plan workflow:

1. **Discovery**: ask clarifying questions that expand the user's idea into concrete product intent.
2. **Readiness**: classify missing information as either user-owned product decisions or agent-filled engineering defaults.
3. **Planning**: generate a markdown implementation plan with architecture, schema, risks, security, tests, performance, delivery, future concerns, and open issues.
4. **Architect Review**: run seven configured reviewer agents to critique the plan from different product, engineering, implementation, staffing, and operations viewpoints.
5. **Review-driven clarification**: convert reviewer comments that require user-owned product decisions into concrete user questions before consolidation.
6. **Arbitration/Consolidation**: merge review feedback and user clarifications into an improved plan and repeat for configurable iterations.

The planner is idea-agnostic but domain-aware. It uses discovery dimensions rather than a fixed technical questionnaire. Prompts are written in plain language for non-technical users, then mapped into planning labels such as target users, primary journey, v1 scope, sensitive data, failure behavior, integrations, technology constraints, and launch criteria.

Extra dimensions are added when the idea mentions broad signals such as AI, billing, APIs, hardware, alerts, location, or regulated data.

The research-to-plan workflow uses a separate research discovery flow. Instead of product launch, monetization, and v1 user-journey questions, it asks about research area, research problem, research question, hypothesis, related work, novelty, methodology, datasets or participants, evaluation design, metrics, constraints, ethics, reproducibility, target output, and venue/review expectations.

Research runs can optionally use a `research_question_planner` agent to propose extra topic-specific discovery questions. This is additive only: static critical questions remain mandatory, agent output must be strict JSON, unsafe or duplicate questions are discarded, and the final question set is written to `discovery_questions.md` and embedded in `initial_plan.md` for reviewer context.

## Discovery behavior

The initial planner separates gaps into two categories:

- **Needs User Input**: product/feature decisions that should not be invented silently, such as the primary workflow, mandatory v1 behavior, launch criteria, escalation behavior, data sharing, or scope boundaries.
- **Assumed Engineering Defaults**: implementation details the planner can fill with conservative defaults, such as test coverage, idempotency, observability, encryption, and CI gates.

If a user asks for advice instead of giving a technical answer, the CLI provides a recommendation with a short rationale and lets the user accept it or override it. For example, if the user has no preferred technology stack, the planner can recommend a practical default based on the idea type.

The generated plan includes a readiness gate:

- `READY`: discovery answers cover the required planning inputs.
- `CONDITIONAL`: enough exists for a draft plan, but product gaps remain.
- `NOT READY`: critical product decisions are unresolved.

Critical discovery gaps include target users, primary workflow, mandatory v1 behavior, and measurable launch criteria.

The discovery flow first asks for the user's knowledge level:

- `non-technical`
- `somewhat technical`
- `technical`

Questions are then displayed at the right level. Non-technical users can answer in product and business terms; the planner translates those answers into engineering details such as tests, security controls, database design, and infrastructure assumptions. Technical users can include constraints, protocols, data ownership, scale, and operational details if they already know them.

The discovery flow also asks for a product, workflow, and monetization explanation in no fewer than 10 sentences. This gives reviewer agents enough context to detect scope mismatches and produce a useful implementation plan instead of relying on a short title.

The discovery flow asks for the planned product name. Run output directories use that product name when available, for example `output/20260602_120000_planpilot/`, instead of using the raw idea text.

## Obsidian idea context

You can point the inspector at a single Obsidian markdown note that represents the idea:

```env
INSPECTOR_OBSIDIAN_IDEA_FILE=/home/you/Vault/Ideas/My Idea.md
INSPECTOR_OBSIDIAN_MAX_DEPTH=1
INSPECTOR_OBSIDIAN_MAX_NOTES=12
```

The runtime reads that seed note, extracts `[[wiki links]]`, tags, headings, and a bounded excerpt, then resolves linked markdown notes from the same Obsidian vault or folder tree. It writes `obsidian_context.md` in the run directory and appends that context to `initial_plan.md` before reviewer agents run.

Use depth `1` for most implementation planning. Depth `2` can be useful when idea notes link to feature notes that link to risk, customer, or architecture notes. Higher depth usually adds noise.

The discovery flow also asks explicit gap-filling product questions before planning:

- Visibility and sharing defaults for user-created resources.
- Moderation and abuse response.
- Deletion, retention, and export expectations.
- Monetization model.
- Degraded-mode behavior when parts of the product are unavailable.
- Launch comfort criteria in product terms.

The user only needs to answer these as product expectations. The planner turns them into engineering defaults such as authorization matrices, test routes, storage strategy, security controls, and release gates.

## Review-driven clarification

After reviewer-agent comments are written for an iteration, the CLI scans those comments for user-owned decisions such as scope mismatches, authorization ownership, authentication/session policy, moderation, privacy retention, performance targets, database choices, infrastructure, hardware requirements, technology stack, and implementation-order constraints.

When such gaps are found, the CLI asks the user targeted questions before consolidation. Answers are written to:

- `iteration_xx/user_review_clarifications.md`

Those answers are appended to the current plan as authoritative context so the consolidator can fix the plan and the next iteration reviews the improved version.

## Existing-plan architect critique

If you already have an implementation plan, skip discovery and planning:

```bash
python3 src/inspector.py --plan-file plans/implementation-plan-inspector-plan.md --iterations 2
```

This workflow copies the source markdown to `initial_plan.md`, runs configured reviewer agents as senior software architects, then asks the arbitrator to produce the final revised plan.

When the source plan or filename includes a version such as `v1.1`, `v.0.9.1`, or `Version: 1.1`, the workflow also searches related plan directories for markdown files with the same version or matching topic tokens. It writes:

- `related_version_context.md`

Reviewer agents receive this context so they can see how decisions, risks, constraints, and implementation direction progressed across versions. The arbitrator still treats the source plan as the primary artifact and uses older context only where it improves the final implementation plan.

Architect reviewers must critique:

- Architectural boundaries, service ownership, data ownership, schema direction, and operational readiness.
- Performance requirements such as p95/p99 latency, concurrency, capacity, background jobs, and load-test data shape.
- Security flaws including IDOR/BOLA, authentication/session risk, authorization matrices, replay/idempotency, audit logging, and sensitive-data exposure.
- Edge cases including duplicate requests, dependency outages, partial writes, stale permissions, deleted resources, empty states, retries, and rollback.
- Specific testing required across unit, integration, E2E, security, performance, reliability, privacy, migration, and release validation.

The arbitrator must preserve the final implementation plan while adding or updating:

- `Architectural Concerns`
- `Performance Requirements`
- `Security Flaws`
- `Edge Cases`
- `Specific Testing Required`
- `Open Concerns`

After each run, the CLI also writes `risks.md` next to `final_plan.md`. This file consolidates negative and risk-oriented material from the final plan, including risks, concerns, flaws, performance issues, future concerns, edge cases, blocked states, open issues, and risk-driven tests. It is a quick-reference artifact; `final_plan.md` remains the source of truth.

## Final plan contract

The final deliverable is an implementation plan. It must include:

- Milestones with acceptance criteria.
- Ordered implementation checklist.
- Test routes for unit, integration, E2E, security, performance, reliability, privacy, and release validation.
- Future issues and deferred decisions.
- Hardware requirements when devices or physical infrastructure are involved.
- Software concerns including hosting, observability, security, privacy, CI/CD, and rollback.
- Framework/language recommendation when the user has no hard constraint.
- Database recommendation for new products, including ownership boundaries, constraints, indexes, and migration strategy.

## Output structure

Runs create a timestamped folder under `output/`:

- `initial_plan.md`
- `iteration_01/software-architect_review.md`
- `iteration_01/security-analyst_review.md`
- `iteration_01/delivery-manager_review.md`
- `iteration_01/ui-ux-analyst_review.md`
- `iteration_01/devops-engineer_review.md`
- `iteration_01/full-stack-engineer_review.md`
- `iteration_01/team-lead_review.md`
- `iteration_01/user_review_clarifications.md`
- `iteration_01/consolidated_plan.md`
- `related_version_context.md` for existing-plan architect critique runs
- ...
- `final_plan.md`
- `risks.md`

Existing-plan architect critique runs use the same artifact names and add `_architect_review` to the run directory name.

## Notes

- By default this project uses built-in deterministic mock agents so it runs without API keys.
- The runtime supports any non-empty reviewer list plus one arbitrator.
- Prefer workflow-specific config files for agent setup. Start from `inspector.new-idea.config.example.json` for `--idea`, `inspector.existing-plan.config.example.json` for `--plan-file`, and `inspector.research.config.example.json` for `--research`.
- The CLI automatically uses `inspector.new-idea.config.json` for new ideas, `inspector.existing-plan.config.json` for existing-plan critique, and `inspector.research.config.json` for research runs when those files exist. Use `--config` or `INSPECTOR_CONFIG_FILE` to override.
- Set provider-level model defaults once with `OPENAI_MODEL`, `ANTHROPIC_MODEL`, and `GROK_MODEL` in `.env`, or with top-level `openai_model`, `anthropic_model`, and `grok_model` in a workflow config. Reviewer and arbitrator entries inherit those defaults when they omit `model`.
- Use an agent-level `model` only when one reviewer or arbitrator should intentionally use a different model than the provider default.
- Use an agent-level `model_env` when one reviewer or arbitrator should read its model from a named environment variable, for example `OPENAI_FAST_MODEL` or `OPENAI_DEEP_MODEL`.
- For research runs, `research_question_planner` can be enabled in `inspector.research.config.json` or through `INSPECTOR_RESEARCH_QUESTION_PLANNER`. It proposes extra discovery questions before the user interview.

Example reviewer entries using two OpenAI models:

```json
{
  "name": "Fast Reviewer",
  "provider": "openai",
  "model_env": "OPENAI_FAST_MODEL",
  "api_key_env": "OPENAI_API_KEY",
  "prompt": "Do a fast first-pass review."
},
{
  "name": "Deep Reviewer",
  "provider": "openai",
  "model_env": "OPENAI_DEEP_MODEL",
  "api_key_env": "OPENAI_API_KEY",
  "prompt": "Do a deeper risk review."
}
```

Example research question planner:

```json
{
  "active": true,
  "name": "Research Question Planner",
  "provider": "openai",
  "model_env": "OPENAI_DEEP_MODEL",
  "api_key_env": "OPENAI_API_KEY"
}
```

- The examples demonstrate a seven-reviewer default stack: Software Architect and Security Analyst backed by Claude, Delivery Manager, UI/UX Analyst, Full Stack Engineer, and Team Lead backed by OpenAI, DevOps Engineer backed by Grok, and an Arbitrator backed by Grok.
- `reviewers` and `arbitrator` support `mock`, `openai`/`responses`, `anthropic`, and OpenAI-compatible chat providers via `grok`, `openai_chat`, or `chat_completions`.
- Reviewer entries can include `category` metadata and `active`. Reviewers with `active: false` are skipped; missing `active` defaults to enabled for backward compatibility.
- Each reviewer and the arbitrator can include a `prompt` field. Keep this role-specific; shared contracts and repeated instructions belong at the top level. This lets one provider key run multiple distinct personas, for example Software Architect, Security Analyst, Delivery Manager, UI/UX Analyst, DevOps Engineer, Full Stack Engineer, and Team Lead.
- Shared top-level config fields such as `document_goal`, `global_instruction`, `input_expectation`, `severity_scale`, `reviewer_output_contract`, and `final_output_contract` are automatically injected into every reviewer and arbitrator prompt before the role-specific prompt.
- `runtime_prompt_composition` defines common reviewer and arbitrator instructions that the runtime injects during prompt assembly, so repeated instructions do not need to be copied into each reviewer prompt.
- If only one live provider key is available and `INSPECTOR_REVIEWERS` is not set, the CLI automatically creates the standard reviewers from that provider.
- Live provider-backed reviewers can be enabled with API keys and `INSPECTOR_AGENT_MODE=live`.
- Reviewer agents act as software architects. They check whether the plan follows from discovered user intent when available, then challenge architecture, risks, performance requirements, security flaws, edge cases, missing acceptance criteria, weak security controls, vague future concerns, and implementation gaps.
