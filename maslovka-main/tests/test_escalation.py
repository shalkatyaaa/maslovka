from __future__ import annotations

import unittest

from museum_bot.escalation import is_human_handoff_request


class EscalationTest(unittest.TestCase):
    def test_detects_operator_request(self) -> None:
        self.assertTrue(is_human_handoff_request("переведите меня на оператора"))
        self.assertTrue(is_human_handoff_request("хочу поговорить с живым человеком"))
        self.assertTrue(is_human_handoff_request("позовите координатора пожалуйста"))

    def test_contact_question_is_not_handoff(self) -> None:
        self.assertFalse(is_human_handoff_request("как связаться с музеем?"))
        self.assertFalse(is_human_handoff_request("какой телефон у музея?"))


if __name__ == "__main__":
    unittest.main()
