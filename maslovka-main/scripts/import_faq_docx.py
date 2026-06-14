from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from museum_bot.db import Database
from museum_bot.faq_docx import parse_faq_docx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import FAQ items from a structured DOCX file.")
    parser.add_argument("docx", type=Path, help="Path to the FAQ DOCX file.")
    parser.add_argument("--db", type=Path, default=ROOT_DIR / "bot.sqlite3")
    parser.add_argument("--json", type=Path, help="Write parsed FAQ to JSON instead of SQLite.")
    parser.add_argument("--replace", action="store_true", help="Replace existing FAQ rows.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    items = parse_faq_docx(args.docx)
    if not items:
        raise SystemExit("No FAQ items found. Expected numbered question / keywords / answer blocks.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {len(items)} FAQ items to {args.json}")
        return

    db = Database(args.db)
    db.init()
    count = db.seed_faq(items, replace=args.replace)
    print(f"Imported {count} FAQ items into {args.db}")


if __name__ == "__main__":
    main()
