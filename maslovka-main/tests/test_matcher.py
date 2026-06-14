from __future__ import annotations

import json
import unittest
from pathlib import Path

from museum_bot.matcher import find_best_match


ROOT_DIR = Path(__file__).resolve().parent.parent


class MatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = json.loads((ROOT_DIR / "data" / "faq_seed.json").read_text(encoding="utf-8"))

    def assert_question(self, message: str, expected: str) -> None:
        result = find_best_match(message, self.items, threshold=0.57)
        self.assertIsNotNone(result, msg=message)
        assert result is not None
        self.assertEqual(result.item["question"], expected)

    def test_hours_worded_differently(self) -> None:
        self.assert_question("во сколько музей открыт в воскресенье?", "Как работает музей?")

    def test_address(self) -> None:
        self.assert_question("подскажите адрес и ближайшее метро", "Где находится музей?")

    def test_ticket_refund(self) -> None:
        self.assert_question("как оформить возврат билета?", "Как вернуть билет?")

    def test_unknown_question(self) -> None:
        result = find_best_match("у вас есть кафе с завтраками?", self.items, threshold=0.57)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

