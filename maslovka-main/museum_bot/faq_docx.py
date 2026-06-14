from __future__ import annotations

import re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}


def extract_paragraphs(path: str | Path) -> list[str]:
    with ZipFile(path) as docx:
        root = ET.fromstring(docx.read("word/document.xml"))

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", NS):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{WORD_NS}}}t":
                parts.append(node.text or "")
            elif node.tag == f"{{{WORD_NS}}}tab":
                parts.append("\t")
            elif node.tag == f"{{{WORD_NS}}}br":
                parts.append("\n")

        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return paragraphs


def parse_faq_docx(path: str | Path) -> list[dict[str, object]]:
    paragraphs = extract_paragraphs(path)
    items: list[dict[str, object]] = []
    index = 0

    while index < len(paragraphs):
        match = re.match(r"^(\d+)\.\s*(.+?)\s*$", paragraphs[index])
        if not match:
            index += 1
            continue

        number = int(match.group(1))
        question = match.group(2)
        keywords: list[str] = []
        answer = ""

        if index + 1 < len(paragraphs):
            raw_keywords = paragraphs[index + 1]
            if ":" in raw_keywords:
                raw_keywords = raw_keywords.split(":", 1)[1]
            keywords = [part.strip() for part in raw_keywords.split(",") if part.strip()]

        if index + 2 < len(paragraphs):
            raw_answer = paragraphs[index + 2]
            answer = raw_answer.split(":", 1)[1].strip() if ":" in raw_answer else raw_answer

        if question and answer:
            items.append(
                {
                    "intent": f"faq_{number:03d}",
                    "question": question,
                    "keywords": keywords,
                    "answer": answer,
                }
            )

        index += 1

    return items

