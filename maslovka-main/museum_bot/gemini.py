from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NO_MATCH = "NO_MATCH"


class GeminiError(RuntimeError):
    """Raised when Gemini cannot classify a question."""


@dataclass(frozen=True)
class GeminiClassification:
    intent: str
    confidence: float
    reason: str

    @property
    def is_match(self) -> bool:
        return self.intent != NO_MATCH


def compact_faq_items(faq_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "intent": str(item.get("intent") or item.get("id")),
            "question": str(item.get("question", "")),
            "keywords": [str(keyword) for keyword in item.get("keywords", [])],
        }
        for item in faq_items
    ]


def build_prompt(user_message: str, faq_items: list[dict[str, Any]]) -> str:
    faq_json = json.dumps(compact_faq_items(faq_items), ensure_ascii=False)
    user_json = json.dumps(user_message[:1500], ensure_ascii=False)
    return (
        "Ты классификатор FAQ для Telegram-бота музея. "
        "Нужно выбрать один intent из списка FAQ, если вопрос пользователя по смыслу совпадает "
        "с одним из готовых вопросов, даже если формулировка другая.\n\n"
        "Правила:\n"
        "- Не придумывай новые ответы и не выбирай FAQ только по одному общему слову.\n"
        "- Если подходящего FAQ нет, пользователь пишет не по теме музея или уверенность низкая, верни NO_MATCH.\n"
        "- confidence: число от 0 до 1.\n"
        "- reason: коротко на русском, почему выбран intent или почему NO_MATCH.\n\n"
        'Верни только JSON вида {"intent":"faq_001","confidence":0.92,"reason":"..."}.\n\n'
        f"Вопрос пользователя: {user_json}\n\n"
        f"Список FAQ: {faq_json}"
    )


def parse_classification_text(text: str) -> GeminiClassification:
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini returned invalid JSON: {cleaned[:300]}") from exc

    intent = str(data.get("intent") or NO_MATCH).strip()
    if not intent:
        intent = NO_MATCH

    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip()
    return GeminiClassification(intent=intent, confidence=confidence, reason=reason)


class GeminiFAQClassifier:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.5-flash-lite",
        timeout_seconds: float = 8,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def classify(
        self,
        *,
        user_message: str,
        faq_items: list[dict[str, Any]],
    ) -> GeminiClassification:
        payload = self._build_payload(user_message=user_message, faq_items=faq_items)
        response = await asyncio.to_thread(self._post, payload)
        text = self._response_text(response)
        return parse_classification_text(text)

    def _build_payload(self, *, user_message: str, faq_items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": build_prompt(user_message, faq_items)}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 220,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "intent": {"type": "STRING"},
                        "confidence": {"type": "NUMBER"},
                        "reason": {"type": "STRING"},
                    },
                    "required": ["intent", "confidence", "reason"],
                },
            },
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = GEMINI_ENDPOINT.format(model=self.model)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GeminiError(f"Gemini HTTP {exc.code}: {details[:500]}") from exc
        except urllib.error.URLError as exc:
            raise GeminiError(f"Gemini request failed: {exc}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GeminiError("Gemini returned a non-JSON HTTP response") from exc

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini response has no candidates")

        parts = candidates[0].get("content", {}).get("parts") or []
        texts = [str(part.get("text", "")) for part in parts if part.get("text")]
        text = "".join(texts).strip()
        if not text:
            raise GeminiError("Gemini response has no text")
        return text

