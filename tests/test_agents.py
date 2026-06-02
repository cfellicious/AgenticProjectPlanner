from __future__ import annotations

import io
import unittest
from unittest.mock import patch
import urllib.error

from agents import AgentResult, MockAgent, MockConsolidator, OpenAIConsolidator, OpenAIReviewer, RetryConfig, _post_json


class AgentIntegrationTests(unittest.TestCase):
    @patch("agents._post_json")
    def test_openai_reviewer_uses_mocked_response(self, mock_post_json) -> None:
        mock_post_json.return_value = {"output_text": "# OpenAI Review\n\n- Looks good"}
        reviewer = OpenAIReviewer("k", "m", RetryConfig(), "https://api.openai.com/v1")
        text = reviewer.review("plan")
        self.assertIn("OpenAI Review", text)
        self.assertIn("Looks good", text)

    def test_mock_agent_uses_architect_review_sections(self) -> None:
        text = MockAgent("Claude").review("plan")

        self.assertIn("## Architectural Concerns", text)
        self.assertIn("## Performance Requirements", text)
        self.assertIn("## Security Flaws", text)
        self.assertIn("## Edge Cases", text)
        self.assertIn("## Specific Testing Required", text)

    def test_mock_consolidator_outputs_arbitrated_required_sections(self) -> None:
        out = MockConsolidator().consolidate("# Plan", [AgentResult("Claude", "- IDOR/BOLA gap")])

        self.assertIn("## Architectural Concerns", out)
        self.assertIn("## Performance Requirements", out)
        self.assertIn("## Security Flaws", out)
        self.assertIn("## Edge Cases", out)
        self.assertIn("## Specific Testing Required", out)
        self.assertIn("## Open Concerns", out)

    @patch("agents._post_json")
    def test_openai_reviewer_reads_raw_responses_output(self, mock_post_json) -> None:
        mock_post_json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "# OpenAI Review\n\n- Parsed from raw output"}
                    ],
                }
            ]
        }
        reviewer = OpenAIReviewer("k", "m", RetryConfig(), "https://api.openai.com/v1")
        text = reviewer.review("plan")
        self.assertIn("Parsed from raw output", text)

    @patch("agents._post_json")
    def test_openai_consolidator_falls_back_to_current_plan_on_empty_output(self, mock_post_json) -> None:
        mock_post_json.return_value = {"output_text": ""}
        consolidator = OpenAIConsolidator("k", "m", RetryConfig(), "https://api.openai.com/v1")
        current = "# Plan\n\nBase"
        out = consolidator.consolidate(current, [AgentResult("Claude", "- issue")])
        self.assertEqual(out, current)

    @patch("agents._post_json", side_effect=RuntimeError("network down"))
    def test_openai_reviewer_raises_on_provider_failure(self, _mock_post_json) -> None:
        reviewer = OpenAIReviewer("k", "m", RetryConfig(max_retries=0), "https://api.openai.com/v1")
        with self.assertRaises(RuntimeError):
            reviewer.review("plan")

    @patch("urllib.request.urlopen")
    def test_post_json_includes_http_error_body(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.example.test",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"message":"model not found"}}'),
        )

        with self.assertRaisesRegex(RuntimeError, "model not found"):
            _post_json(
                "https://api.example.test",
                {"Content-Type": "application/json"},
                {"model": "missing"},
                RetryConfig(max_retries=0),
            )


if __name__ == "__main__":
    unittest.main()
