"""Dump the bundled clause-template library to JSON / Markdown.

Usage:
    python scripts/dump_templates.py            # JSON to stdout
    python scripts/dump_templates.py --md FILE  # Markdown report to FILE
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from lawrisk.templates import DEFAULT_TEMPLATES, ClauseTemplate


def _to_json() -> str:
    return json.dumps([t.to_dict() for t in DEFAULT_TEMPLATES], indent=2)


def _to_markdown(templates: List[ClauseTemplate]) -> str:
    lines: List[str] = ["# LawRisk built-in clause templates", ""]
    for t in templates:
        lines.append(f"## {t.name} (`{t.id}`)")
        lines.append("")
        lines.append(t.description or "_no description_")
        lines.append("")
        lines.append(f"- paragraphs: {len(t.paragraphs)}")
        lines.append(f"- content hash: `{t.content_hash[:16]}`")
        lines.append("")
        lines.append("### Sections")
        lines.append("")
        for s in t.sections:
            lines.append(f"- {s}")
        lines.append("")
        lines.append("```text")
        for p in t.paragraphs:
            lines.append(p)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--md",
        metavar="FILE",
        help="write a Markdown report to FILE instead of JSON to stdout",
    )
    args = parser.parse_args(argv)

    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(DEFAULT_TEMPLATES))
        print(f"wrote {args.md}", file=sys.stderr)
        return 0

    print(_to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
