# Implementation Plan Inspector

Turn a raw product idea into an actionable implementation plan, or critique an existing implementation plan through software-architect reviewer agents.

## What it does

The project supports two workflows:

1. **Idea-to-plan workflow**: turn a raw product idea into a structured implementation plan, then harden it through reviewer-agent critique.
2. **Existing-plan architect critique workflow**: take an implementation plan markdown file and have Claude, OpenAI, and Grok behave as senior software architects who critique architecture, performance, security, edge cases, and testing gaps. The arbitrator produces the revised final document.

The idea-to-plan workflow:

1. **Discovery**: ask clarifying questions that expand the user's idea into concrete product intent.
2. **Readiness**: classify missing information as either user-owned product decisions or agent-filled engineering defaults.
3. **Planning**: generate a markdown implementation plan with architecture, schema, risks, security, tests, performance, delivery, future concerns, and open issues.
4. **Architect Review**: run multiple reviewer agents (Claude/OpenAI/Grok) to critique the plan from a software-architect viewpoint.
5. **Review-driven clarification**: convert reviewer comments that require user-owned product decisions into concrete user questions before consolidation.
6. **Arbitration/Consolidation**: merge review feedback and user clarifications into an improved plan and repeat for configurable iterations.

The planner is idea-agnostic but domain-aware. It uses discovery dimensions rather than a fixed technical questionnaire. Prompts are written in plain language for non-technical users, then mapped into planning labels such as target users, primary journey, v1 scope, sensitive data, failure behavior, integrations, technology constraints, and launch criteria.

Extra dimensions are added when the idea mentions broad signals such as AI, billing, APIs, hardware, alerts, location, or regulated data.

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

This workflow copies the source markdown to `initial_plan.md`, runs Claude/OpenAI/Grok reviewer agents as senior software architects, then asks the arbitrator to produce the final revised plan.

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

## Output structure

Runs create a timestamped folder under `output/`:

- `initial_plan.md`
- `iteration_01/claude_review.md`
- `iteration_01/openai_review.md`
- `iteration_01/grok_review.md`
- `iteration_01/user_review_clarifications.md`
- `iteration_01/consolidated_plan.md`
- `related_version_context.md` for existing-plan architect critique runs
- ...
- `final_plan.md`
- `risks.md`

Existing-plan architect critique runs use the same artifact names and add `_architect_review` to the run directory name.

## Notes

- By default this project uses built-in deterministic mock agents so it runs without API keys.
- Live provider-backed reviewers can be enabled with API keys and `INSPECTOR_AGENT_MODE=live`.
- Reviewer agents act as software architects. They check whether the plan follows from discovered user intent when available, then challenge architecture, risks, performance requirements, security flaws, edge cases, missing acceptance criteria, weak security controls, vague future concerns, and implementation gaps.
