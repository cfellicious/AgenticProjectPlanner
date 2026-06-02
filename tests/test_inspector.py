from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inspector import (
    _collect_related_plan_context,
    _extract_versions,
    build_negative_reference,
    resolve_answer,
    run,
    run_plan_review,
)
from planner import (
    QUESTION_BANK,
    assess_discovery,
    build_initial_plan,
    display_question_for_user,
    generate_review_follow_up_questions,
    generate_questions,
    guidance_for,
    hardware_requirements_for,
    needs_detail_for_question,
    product_name_from_answers,
    sentence_count,
    should_ask_follow_up,
    wants_agent_guidance,
)


class PlannerTests(unittest.TestCase):
    def test_initial_plan_contains_required_sections(self) -> None:
        answers = {q: "answer" for q in QUESTION_BANK}
        answers["Is this a brand-new product, or something added to an existing product?"] = "new product"
        plan = build_initial_plan("My Idea", answers)

        self.assertIn("## 4. Readiness Gate", plan)
        self.assertIn("## 9. Risk Assessment", plan)
        self.assertIn("## 10. Future Concerns", plan)
        self.assertIn("## 11. Performance Considerations", plan)
        self.assertIn("## 12. Security Concerns", plan)
        self.assertIn("## 13. Test Plan", plan)
        self.assertIn("## 13.1 Test Routes", plan)
        self.assertIn("## 14. Detailed Implementation Checklist", plan)
        self.assertIn("## 15. Workstream Breakdown", plan)
        self.assertIn("## 16. Launch Readiness Checklist", plan)
        self.assertIn("## 17. Milestones and Implementation Order", plan)
        self.assertIn("IDOR/BOLA", plan)
        self.assertIn("## 18. Database Schema (Initial Draft)", plan)
        self.assertIn("## 19. Framework, Software, and Database Recommendations", plan)
        self.assertIn("## 20. Hardware Requirements", plan)
        self.assertIn("- No dedicated hardware is required for v1.", plan)
        self.assertNotIn("If hardware is involved", plan)
        self.assertNotIn("If no hardware is involved", plan)
        self.assertIn("## 21. Frontend", plan)
        self.assertIn("## 22. Backend", plan)
        self.assertIn("## 23. Docker and Delivery (New Product)", plan)
        self.assertIn("## 24. Final Deliverable Requirements", plan)
        self.assertIn("- [ ] Unit tests:", plan)
        self.assertIn("- [ ] Define v1 scope", plan)
        self.assertIn("- [ ] All critical product decisions", plan)
        self.assertIn("- [ ] Milestones with acceptance criteria", plan)

    def test_generate_questions_adds_contextual_prompts(self) -> None:
        questions = generate_questions("AI billing API platform")
        joined = "\n".join(questions)
        self.assertIn("How technical are you", joined)
        self.assertIn("What do you plan to name this product", joined)
        self.assertIn("no fewer than 10 sentences", joined)
        self.assertIn("public, private, or shareable by default", joined)
        self.assertIn("What content or behavior should not be allowed", joined)
        self.assertIn("deletes content or an account", joined)
        self.assertIn("How should this product make money", joined)
        self.assertIn("comfortable saying v1 is ready", joined)
        self.assertIn("what should it never do automatically", joined)
        self.assertIn("money, invoices, balances", joined)
        self.assertIn("main things the system manages", joined)

    def test_low_signal_answer_triggers_follow_up(self) -> None:
        self.assertTrue(should_ask_follow_up("n/a"))
        self.assertTrue(should_ask_follow_up("a"))
        self.assertFalse(should_ask_follow_up("p95 latency target is 250ms"))

    def test_guidance_request_gets_recommendation(self) -> None:
        question = "Do you care what technology is used, or should the planner recommend a practical default?"
        self.assertTrue(wants_agent_guidance("No preference. Which do you think are the best?"))
        guidance = guidance_for(question, "A safety button for women with iOS Android app")
        self.assertIsNotNone(guidance)
        self.assertIn("React Native", guidance or "")

    def test_discovery_assessment_marks_critical_gaps_not_ready(self) -> None:
        answers = {q: "answer" for q in QUESTION_BANK}
        answers["Who is this for, and what problem are they trying to solve?"] = "not sure"
        assessment = assess_discovery("A project planning app", answers)

        self.assertEqual(assessment.readiness, "NOT READY")
        self.assertIn("Who is this for", "\n".join(assessment.needs_user_input))

    def test_safety_idea_adds_discovery_questions(self) -> None:
        questions = generate_questions("A safety button for women")
        joined = "\n".join(questions)
        self.assertIn("what should happen next", joined)
        self.assertIn("who gets notified", joined)

    def test_plan_includes_gap_sections_and_generic_schema(self) -> None:
        answers = {q: "answer" for q in QUESTION_BANK}
        answers["Is this a brand-new product, or something added to an existing product?"] = "new product"
        answers["In simple steps, what should the user do and what should happen next?"] = "not sure"
        plan = build_initial_plan("A safety button for women", answers)
        self.assertIn("## 5. User Decisions", plan)
        self.assertIn("## 6. Assumed Engineering Defaults", plan)
        self.assertIn("## 7. Needs User Input", plan)
        self.assertIn("`domain_entities(", plan)
        self.assertIn("`domain_events(", plan)

    def test_hardware_requirements_are_resolved_by_context(self) -> None:
        software_only = hardware_requirements_for("Photography showcase app", {"q": "upload photos"})
        hardware = hardware_requirements_for("Safety button wearable", {"q": "bluetooth device"})

        self.assertIn("No dedicated hardware is required for v1.", software_only)
        self.assertIn("Hardware is in scope", hardware[0])

    def test_question_display_is_tailored_by_knowledge_level(self) -> None:
        question = "What database should this use?"
        nontechnical = display_question_for_user(
            question,
            {"How technical are you? Choose one: non-technical, somewhat technical, or technical.": "non-technical founder"},
        )
        technical = display_question_for_user(
            question,
            {"How technical are you? Choose one: non-technical, somewhat technical, or technical.": "technical engineer"},
        )

        self.assertIn("plain product/business terms", nontechnical)
        self.assertIn("technical constraints", technical)

    def test_product_narrative_requires_ten_sentences(self) -> None:
        question = "Please explain the product, main workflows, and how it will make money in no fewer than 10 sentences."
        short = "Users upload photos. They create collections."
        long = " ".join([f"Sentence {i}." for i in range(1, 11)])

        self.assertEqual(sentence_count(long), 10)
        self.assertTrue(needs_detail_for_question(question, short))
        self.assertFalse(needs_detail_for_question(question, long))

    def test_product_name_falls_back_to_idea_when_missing(self) -> None:
        question = "What do you plan to name this product?"

        self.assertEqual(product_name_from_answers("Fallback Idea", {question: "LensHub"}), "LensHub")
        self.assertEqual(product_name_from_answers("Fallback Idea", {question: "not sure"}), "Fallback Idea")

    def test_review_comments_generate_user_follow_up_questions(self) -> None:
        review = """
        ## Key Issues
        - Critical Scope Mismatch: title claims safety button but discovery reveals photo platform.
        - IDOR/BOLA is under-specified and ownership rules are missing.
        - Missing Authentication & Session Model.
        - No database choice specified for this new product.
        """
        questions = generate_review_follow_up_questions([review])
        rendered = "\n".join(item.question for item in questions)

        self.assertIn("product-scope mismatch", rendered)
        self.assertIn("who should be able to see it", rendered)
        self.assertIn("How should users log in", rendered)
        self.assertIn("planner recommend the database", rendered)


class WorkflowTests(unittest.TestCase):
    def test_extract_versions_from_filename_and_content(self) -> None:
        versions = _extract_versions("Version: 1.1\nPolicy version is separate.", "product-plan-v.0.9.1.md")

        self.assertIn("0.9.1", versions)
        self.assertIn("1.1", versions)

    def test_collect_related_plan_context_uses_version_and_topic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "billing-plan-v1.1.md"
            source.write_text("# Billing Plan\n\nVersion: 1.1\n", encoding="utf-8")
            same_version = tmp_path / "other-plan-v1.1.md"
            same_version.write_text(
                "# Other Plan\n\nVersion: 1.1\n\n## Security\n- Risk: authorization gap.\n",
                encoding="utf-8",
            )
            same_topic = tmp_path / "billing-plan-v1.0.md"
            same_topic.write_text(
                "# Billing Plan Old\n\nVersion: 1.0\n\n## Decisions\n- Decision: old billing scope.\n",
                encoding="utf-8",
            )

            contexts = _collect_related_plan_context(source, source.read_text(encoding="utf-8"))
            context_paths = {item.path.name for item in contexts}

            self.assertIn("other-plan-v1.1.md", context_paths)
            self.assertIn("billing-plan-v1.0.md", context_paths)

    def test_build_negative_reference_extracts_sections(self) -> None:
        content = build_negative_reference(
            "# Plan\n\n"
            "## Product Goal\n"
            "- Build it.\n\n"
            "## Performance Requirements\n"
            "- p95 must be below 200ms.\n\n"
            "## Edge Cases\n"
            "- Duplicate request must not corrupt state.\n\n"
            "## Future Issues\n"
            "- Deferred table policy.\n",
            "Product",
            Path("final_plan.md"),
        )

        self.assertIn("# Negative Reference: Product", content)
        self.assertIn("## Performance Requirements", content)
        self.assertIn("## Edge Cases", content)
        self.assertIn("## Future Issues", content)
        self.assertNotIn("## Product Goal", content)

    @patch("inspector.input")
    @patch.dict("os.environ", {"INSPECTOR_AGENT_MODE": "mock"})
    def test_run_creates_expected_artifacts(self, mock_input) -> None:
        mock_input.side_effect = [
            "technical engineer",
            "PlanPilot",
            "PMs and engineers plan delivery",
            (
                "The product helps teams turn rough ideas into executable implementation plans. "
                "A user starts by entering a product idea. "
                "The app asks discovery questions to understand the workflow. "
                "The app then creates a first implementation plan. "
                "Reviewer agents critique the plan from different angles. "
                "The user answers product-level follow-up questions after reviews. "
                "The plan is revised through one or more iterations. "
                "Teams use the final plan to assign implementation work. "
                "The product can make money through paid subscriptions for teams. "
                "Larger companies can pay more for collaboration, history, and live agent integrations."
            ),
            "new product",
            "User creates invoice, sends invoice, customer pays, status updates.",
            "Invoice create/send/pay are mandatory; AI summary is optional.",
            "5k users",
            "PII includes client contact and invoice metadata.",
            "If payment API is down, queue retries and show pending state.",
            "Show a retryable error and keep paid invoice status visible in read-only mode.",
            "Prevent cross-account invoice access and unauthorized payout changes.",
            "Invoices are private to account members; paid receipts can be shared by secure link.",
            "Fraudulent invoices, impersonation, and abusive messages are not allowed; support reviews reports.",
            "Soft delete by default, permanent deletion on request when legally allowed, export account data.",
            "No mobile app",
            "Team subscriptions in v1, enterprise plans later.",
            "Python + Postgres + React",
            "Launch if 95% success and no Sev1",
            "Core billing workflow works, no critical security findings remain, and support can handle reports.",
            "B2B entities: org/project/task",
            "Provider cap is $1k/mo",
            "Idempotent billing writes and daily reconciliation",
            "Only account owners can mutate resources; non-owners get 404 for private resources.",
            "Retain customer metadata for seven years where legally required; export/delete user-owned content on request.",
            "The app should feel fast when viewing galleries and liking photos; 5k users in year one.",
            "Use PostgreSQL with tenant-scoped entities, ownership indexes, migrations, and rollback scripts.",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            final_path = run("AI billing API platform", 1, Path(tmp))
            run_dir = final_path.parent

            self.assertTrue((run_dir / "initial_plan.md").exists())
            self.assertTrue((run_dir / "run_manifest.json").exists())
            self.assertTrue((run_dir / "iteration_01" / "claude_review.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "openai_review.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "grok_review.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "user_review_clarifications.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "consolidated_plan.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "iteration_manifest.json").exists())
            self.assertTrue((run_dir / "final_plan.md").exists())
            self.assertTrue((run_dir / "risks.md").exists())
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["idea"], "AI billing API platform")
            self.assertEqual(manifest["product_name"], "PlanPilot")
            self.assertIn("risks", manifest["artifacts"])
            self.assertTrue(run_dir.name.endswith("_planpilot"))
            final_plan = (run_dir / "final_plan.md").read_text(encoding="utf-8")
            self.assertIn("Review-Driven User Clarifications", final_plan)
            self.assertIn("Only account owners can mutate resources", final_plan)
            risks = (run_dir / "risks.md").read_text(encoding="utf-8")
            self.assertIn("Negative Reference", risks)
            self.assertIn("Security Flaws", risks)

    @patch.dict("os.environ", {"INSPECTOR_AGENT_MODE": "mock"})
    def test_run_plan_review_critiques_existing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_plan = tmp_path / "implementation-plan.md"
            source_plan.write_text(
                "# Implementation Plan\n\n"
                "## Architecture Overview\n"
                "- Build an API and frontend.\n",
                encoding="utf-8",
            )

            final_path = run_plan_review(source_plan, 1, tmp_path / "out")
            run_dir = final_path.parent

            self.assertTrue((run_dir / "initial_plan.md").exists())
            self.assertTrue((run_dir / "related_version_context.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "claude_review.md").exists())
            self.assertTrue((run_dir / "iteration_01" / "consolidated_plan.md").exists())
            self.assertFalse((run_dir / "iteration_01" / "user_review_clarifications.md").exists())
            self.assertTrue((run_dir / "risks.md").exists())

            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["workflow"], "existing-plan-architect-critique")
            self.assertIn("related_version_context", manifest["artifacts"])
            self.assertIn("risks", manifest["artifacts"])

            final_plan = final_path.read_text(encoding="utf-8")
            self.assertIn("## Architectural Concerns", final_plan)
            self.assertIn("## Performance Requirements", final_plan)
            self.assertIn("## Security Flaws", final_plan)
            self.assertIn("## Edge Cases", final_plan)
            self.assertIn("## Specific Testing Required", final_plan)
            risks = (run_dir / "risks.md").read_text(encoding="utf-8")
            self.assertIn("## Performance Requirements", risks)
            self.assertIn("## Security Flaws", risks)

    @patch("inspector.input", return_value="")
    def test_resolve_answer_accepts_agent_recommendation(self, _mock_input) -> None:
        question = "Do you care what technology is used, or should the planner recommend a practical default?"
        answer = resolve_answer(
            "A safety button for women with iOS Android app",
            question,
            "No preference. Which do you think are the best?",
        )

        self.assertIn("Recommended default", answer)
        self.assertIn("React Native", answer)


if __name__ == "__main__":
    unittest.main()
