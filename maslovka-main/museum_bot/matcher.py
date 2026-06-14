from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass
from typing import Any

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - runtime fallback for minimal installs.
    fuzz = None


TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
ALIAS_EXPANSIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("во сколько", "открываетесь", "откроетесь", "когда открыты", "когда работаете", "режим работы"),
        "часы график расписание работает режим открыт когда открыты",
    ),
    (
        ("выходной", "какие дни закрыты", "по понедельникам", "по вторникам"),
        "выходной закрыт понедельник вторник не работает",
    ),
    (
        ("как добраться", "доехать", "куда идти", "ближайшее метро", "адрес"),
        "адрес где как найти локация верхняя масловка метро",
    ),
    (
        ("как зайти", "где вход", "куда заходить", "со двора", "через арку", "подъезд"),
        "вход где вход как зайти арка двор",
    ),
    (
        ("сдать билет", "вернуть деньги", "возврат денег", "отменить покупку"),
        "возврат вернуть билет отменить билет деньги назад",
    ),
    (
        ("поменять дату", "перенести дату", "перенести билет", "другая дата"),
        "обмен поменять билет другая дата перенести билет",
    ),
    (
        ("не пришел билет", "не пришло письмо", "нет письма", "не вижу билет", "где мой билет"),
        "билет не пришел почта письмо оплата подтверждение",
    ),
    (
        ("цена", "стоимость", "сколько стоит", "почем", "прайс"),
        "цена стоимость сколько стоит билет",
    ),
    (
        ("купить онлайн", "оплатить картой", "оплата картой", "оплатить на сайте"),
        "оплата оплатить онлайн карта купить билет",
    ),
    (
        ("льгот", "скидк", "дешевле", "студент", "пенсионер", "школьник"),
        "льгота льготный скидка школьник студент пенсионер инвалид союз художников",
    ),
    (
        ("бесплатный вход", "бесплатно пройти", "icom", "аис"),
        "бесплатно бесплатный вход icom аис музейный сотрудник инвалид ветеран",
    ),
    (
        ("коляск", "маломобиль", "безбарьер", "лифт", "инвалид"),
        "доступная среда инвалидность маломобильный коляска лифт",
    ),
    (
        ("парковк", "шлагбаум", "заехать на машине", "въезд на машине"),
        "парковка инвалидность шлагбаум машина въезд",
    ),
    (
        ("афиша", "что будет", "ближайшие события", "мероприятия", "лекции"),
        "события афиша лекции встречи кинопоказы мероприятия",
    ),
    (
        ("что сейчас идет", "что посмотреть", "какая выставка", "выставки сейчас"),
        "выставка текущая выставка сейчас экспозиция что посмотреть",
    ),
    (
        ("экскурсовод", "гид", "экскурсия", "экскурсии"),
        "экскурсия экскурсии гид куратор научный сотрудник",
    ),
    (
        ("индивидуальная экскурсия", "частная экскурсия", "для своей группы", "корпоративная экскурсия"),
        "индивидуальная экскурсия группа частная экскурсия корпоративная экскурсия заявка анкета",
    ),
    (
        ("с классом", "группой", "групповое посещение", "студенты"),
        "группа групповое посещение экскурсия для группы класс студенты",
    ),
    (
        ("с ребенком", "с детьми", "дети", "ребенок"),
        "дети ребенок семейный билет с детьми детская экскурсия возраст 12+",
    ),
    (
        ("фоткать", "фотографировать", "снимать", "видеосъемка"),
        "фото фотографировать съемка видео",
    ),
    (
        ("с собакой", "с питомцем", "с животным", "животные"),
        "собака животные питомец можно с собакой",
    ),
    (
        ("гардероб", "оставить рюкзак", "оставить сумку", "камеры хранения"),
        "гардероб вещи сумка рюкзак хранение",
    ),
    (
        ("телега", "тг канал", "telegram канал", "подписаться на канал"),
        "телеграм telegram канал подписаться новости",
    ),
    (
        ("карта друга", "абонемент", "друг музея"),
        "карта друга друг музея абонемент привилегии",
    ),
    (
        ("опаздываю", "задерживаюсь", "не успеваю", "приду позже"),
        "опаздываю задерживаюсь поздно не успеваю",
    ),
    (
        ("отменили", "перенесли", "новая дата", "событие отменили"),
        "отмена перенос мероприятие отменили новая дата",
    ),
)
STOP_WORDS = {
    "а",
    "без",
    "бы",
    "в",
    "вам",
    "вас",
    "вы",
    "где",
    "да",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "есть",
    "и",
    "из",
    "или",
    "как",
    "ко",
    "ли",
    "мне",
    "можно",
    "мы",
    "на",
    "над",
    "не",
    "нет",
    "нужно",
    "о",
    "об",
    "от",
    "по",
    "под",
    "при",
    "с",
    "со",
    "такое",
    "у",
    "что",
    "это",
    "я",
}


@dataclass(frozen=True)
class MatchResult:
    item: dict[str, Any]
    score: float
    reason: str


def normalize(text: str) -> str:
    tokens = TOKEN_RE.findall(text.casefold().replace("ё", "е"))
    return " ".join(tokens)


def expand_text(text: str) -> str:
    normalized = normalize(text)
    additions: list[str] = []
    for aliases, expansion in ALIAS_EXPANSIONS:
        if any(alias in normalized for alias in aliases):
            additions.append(expansion)

    return " ".join([text, *additions])


def stem_token(token: str) -> str:
    endings = (
        "ыми",
        "ими",
        "ого",
        "ему",
        "ому",
        "ыми",
        "ами",
        "ями",
        "иях",
        "ах",
        "ях",
        "ые",
        "ие",
        "ая",
        "яя",
        "ое",
        "ее",
        "ой",
        "ий",
        "ый",
        "ую",
        "юю",
        "ом",
        "ем",
        "ов",
        "ев",
        "а",
        "я",
        "ы",
        "и",
        "у",
        "ю",
        "е",
        "о",
    )
    for ending in endings:
        if token.endswith(ending) and len(token) > len(ending) + 3:
            return token[: -len(ending)]
    return token


def tokens(text: str, *, meaningful: bool = False) -> set[str]:
    raw_tokens = TOKEN_RE.findall(text.casefold().replace("ё", "е"))
    result = {stem_token(token) for token in raw_tokens}
    if meaningful:
        result = {token for token in result if token not in STOP_WORDS and len(token) > 1}
    return result


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0

    if fuzz is not None:
        return fuzz.WRatio(left, right) / 100

    return difflib.SequenceMatcher(a=left, b=right).ratio()


def _partial_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0

    if fuzz is not None:
        return fuzz.partial_ratio(left, right) / 100

    shorter, longer = sorted((left, right), key=len)
    if shorter in longer:
        return 1.0
    return difflib.SequenceMatcher(a=left, b=right).ratio()


def _token_set_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0

    if fuzz is not None:
        return fuzz.token_set_ratio(left, right) / 100

    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return (2 * overlap) / (len(left_tokens) + len(right_tokens))


def _keyword_score(user_text: str, user_tokens: set[str], keyword: str) -> float:
    keyword_text = normalize(keyword)
    keyword_tokens = tokens(keyword, meaningful=True)
    if not keyword_text or not keyword_tokens:
        return 0.0

    if len(keyword_tokens) > 1 and keyword_text in user_text:
        return 0.96 if len(keyword_text) > 3 else 0.68

    if len(keyword_tokens) == 1:
        keyword_token = next(iter(keyword_tokens))
        if keyword_token in user_tokens:
            return 0.70
        if len(keyword_token) >= 5:
            return _partial_ratio(user_text, keyword_text) * 0.46
        return 0.0

    overlap = len(user_tokens & keyword_tokens) / len(keyword_tokens)
    fuzzy = _partial_ratio(user_text, keyword_text)
    return max(overlap * 0.88, fuzzy * 0.86)


def score_item(user_message: str, item: dict[str, Any]) -> tuple[float, str]:
    expanded_message = expand_text(user_message)
    user_text = normalize(expanded_message)
    user_tokens = tokens(expanded_message, meaningful=True)
    question = str(item.get("question", ""))
    keywords = [str(keyword) for keyword in item.get("keywords", [])]

    question_text = normalize(question)
    question_tokens = tokens(question, meaningful=True)
    question_score = max(
        _ratio(user_text, question_text) * 0.90,
        _token_set_ratio(user_text, question_text) * 0.86,
    )

    if question_tokens:
        question_overlap = len(user_tokens & question_tokens) / len(question_tokens)
        question_score = max(question_score, question_overlap * 0.82)

    best_keyword = 0.0
    for keyword in keywords:
        best_keyword = max(best_keyword, _keyword_score(user_text, user_tokens, keyword))

    bank_text = normalize(" ".join([question, *keywords]))
    bank_score = _token_set_ratio(user_text, bank_text) * 0.78

    candidates = {
        "question": question_score,
        "keyword": best_keyword,
        "bank": bank_score,
    }
    reason, score = max(candidates.items(), key=lambda pair: pair[1])
    return score, reason


def _corpus_weights(faq_items: list[dict[str, Any]]) -> dict[str, float]:
    document_frequency: dict[str, int] = {}
    for item in faq_items:
        bank_tokens = tokens(
            " ".join(
                [
                    str(item.get("question", "")),
                    *[str(keyword) for keyword in item.get("keywords", [])],
                ]
            ),
            meaningful=True,
        )
        for token in bank_tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    count = max(len(faq_items), 1)
    return {
        token: math.log((count + 1) / (frequency + 1)) + 1
        for token, frequency in document_frequency.items()
    }


def _weighted_bank_score(
    user_message: str,
    item: dict[str, Any],
    weights: dict[str, float],
) -> float:
    user_tokens = tokens(expand_text(user_message), meaningful=True)
    bank_tokens = tokens(
        " ".join(
            [
                str(item.get("question", "")),
                *[str(keyword) for keyword in item.get("keywords", [])],
            ]
        ),
        meaningful=True,
    )
    if not user_tokens or not bank_tokens:
        return 0.0

    overlap = user_tokens & bank_tokens
    if not overlap:
        return 0.0

    matched_weight = sum(weights.get(token, 1.0) for token in overlap)
    user_weight = sum(weights.get(token, 1.0) for token in user_tokens)
    bank_weight = sum(weights.get(token, 1.0) for token in bank_tokens)
    user_coverage = matched_weight / user_weight
    bank_coverage = matched_weight / min(bank_weight, user_weight)
    return min(0.97, (user_coverage * 0.72 + bank_coverage * 0.28) * 0.95)


def find_best_match(
    user_message: str,
    faq_items: list[dict[str, Any]],
    *,
    threshold: float,
) -> MatchResult | None:
    best: MatchResult | None = None
    weights = _corpus_weights(faq_items)
    for item in faq_items:
        score, reason = score_item(user_message, item)
        weighted_score = _weighted_bank_score(user_message, item, weights)
        if weighted_score > score:
            score = weighted_score
            reason = "weighted"

        if best is None or score > best.score:
            best = MatchResult(item=item, score=score, reason=reason)

    if best is None or best.score < threshold:
        return None

    return best
