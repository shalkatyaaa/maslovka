from __future__ import annotations

import unittest

from museum_bot.gemini import NO_MATCH, build_prompt, parse_classification_text


class GeminiTest(unittest.TestCase):
    def test_parse_json(self) -> None:
        result = parse_classification_text(
            '{"intent":"faq_007","confidence":0.84,"reason":"спрашивают про возврат"}'
        )

        self.assertEqual(result.intent, "faq_007")
        self.assertAlmostEqual(result.confidence, 0.84)
        self.assertTrue(result.is_match)

    def test_parse_no_match(self) -> None:
        result = parse_classification_text(
            '```json\n{"intent":"NO_MATCH","confidence":0.2,"reason":"нет такого FAQ"}\n```'
        )

        self.assertEqual(result.intent, NO_MATCH)
        self.assertFalse(result.is_match)

    def test_prompt_contains_only_compact_faq(self) -> None:
        prompt = build_prompt(
            "Когда вы работаете?",
            [
                {
                    "intent": "faq_001",
                    "question": "Как работает музей?",
                    "keywords": ["часы", "график"],
                    "answer": "Не нужно отправлять ответ в Gemini.",
                }
            ],
        )

        self.assertIn("faq_001", prompt)
        self.assertIn("Как работает музей?", prompt)
        self.assertNotIn("Не нужно отправлять ответ", prompt)


if __name__ == "__main__":
    unittest.main()
