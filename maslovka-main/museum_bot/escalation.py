from __future__ import annotations

import re


HUMAN_HANDOFF_PATTERNS = (
    re.compile(
        r"\b(перевед\w*|переключ\w*|соедин\w*|свяж\w*|позов\w*|передай\w*)\b"
        r".{0,80}\b(координатор\w*|оператор\w*|человек\w*|сотрудник\w*|администратор\w*|менеджер\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(координатор\w*|оператор\w*|жив\w*\s+человек\w*|сотрудник\w*|администратор\w*)\b"
        r".{0,80}\b(ответит\w*|поможет\w*|свяжет\w*|напишет\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(нужен|нужна|нужны|хочу|можно|дайте|позовите)\b"
        r".{0,80}\b(оператор\w*|координатор\w*|жив\w*\s+человек\w*|сотрудник\w*|администратор\w*)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(поговорить|пообщаться|связаться)\b"
        r".{0,80}\b(с|со)\s+(оператор\w*|координатор\w*|жив\w*\s+человек\w*|сотрудник\w*|администратор\w*)\b",
        re.IGNORECASE,
    ),
)


def is_human_handoff_request(text: str) -> bool:
    normalized = " ".join(text.casefold().replace("ё", "е").split())
    if not normalized:
        return False

    return any(pattern.search(normalized) for pattern in HUMAN_HANDOFF_PATTERNS)

