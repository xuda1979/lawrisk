"""Offline command-line interface: score / review / diff from the terminal.

The web API uploads documents over HTTP; this module does the same work
directly on local files, so the whole pipeline (parse -> rules -> diff) stays
usable without a running server. Everything is deterministic and LLM-free.

Usage:
    lawrisk-cli score FILE [--json] [--name NAME]
    lawrisk-cli review FILE [--json] [--name NAME]
    lawrisk-cli diff FILE_A FILE_B [--json] [--name-a NAME] [--name-b NAME]
    lawrisk-cli rules [--json]

`python -m lawrisk.cli ...` works the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from lawrisk.diff.differ import build_diff_tree
from lawrisk.diff.markdown_report import render_markdown
from lawrisk.diff.single_report import render_markdown_review
from lawrisk.parser import parse_document
from lawrisk.rules import ENGINE_VERSION, rule_catalog, score_document


def _load_doc(path: str, name: str) -> tuple:
    """Parse a local file into (paragraphs, fields, full_text), regardless of suffix."""
    data = Path(path).read_bytes()
    doc = parse_document(data, uuid.uuid4().hex[:8], name or path)
    full = "\n".join(doc.paragraphs)
    fields = [f.model_dump() for f in doc.fields]
    return doc.paragraphs, fields, full


def cmd_score(args: argparse.Namespace) -> int:
    paragraphs, _, _ = _load_doc(args.file, args.name)
    if not paragraphs:
        print(f"error: {args.file} yielded no paragraphs", file=sys.stderr)
        return 2
    report = score_document(paragraphs, document_id=args.name)
    if args.json:
        print(json.dumps(json.loads(report.model_dump_json()), indent=2))
        return 0
    print(
        f"{args.name or args.file}: {report.overall_score}/100 "
        f"({report.overall_level.value}) · {len(report.penalties)} findings "
        f"· hash {report.deterministic_hash[:12]}"
    )
    for p in report.penalties:
        print(f"  - [{p.rule_id}] {p.dimension}: {p.reason}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    paragraphs, fields, full = _load_doc(args.file, args.name)
    if not paragraphs:
        print(f"error: {args.file} yielded no paragraphs", file=sys.stderr)
        return 2
    risk = score_document(paragraphs, document_id=args.name)
    if args.json:
        print(
            json.dumps(
                {
                    "document_name": args.name or args.file,
                    "risk": json.loads(risk.model_dump_json()),
                    "facts": fields,
                    "llm_enabled": False,
                },
                indent=2,
            )
        )
        return 0
    print(render_markdown_review(args.name or args.file, paragraphs, risk, fields))
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    paras_a, facts_a, _ = _load_doc(args.file_a, args.name_a)
    paras_b, facts_b, _ = _load_doc(args.file_b, args.name_b)
    if not paras_a or not paras_b:
        print("error: both files must yield paragraphs", file=sys.stderr)
        return 2
    label_a = args.name_a or args.file_a
    label_b = args.name_b or args.file_b
    report = build_diff_tree(paras_a, paras_b, label_a, label_b)
    risk_a = score_document(paras_a, document_id=f"{label_a}-{uuid.uuid4().hex[:8]}")
    risk_b = score_document(paras_b, document_id=f"{label_b}-{uuid.uuid4().hex[:8]}")
    if args.json:
        print(
            json.dumps(
                {
                    "diff": report.model_dump(),
                    "risk_a": json.loads(risk_a.model_dump_json()),
                    "risk_b": json.loads(risk_b.model_dump_json()),
                    "llm_enabled": False,
                },
                indent=2,
            )
        )
        return 0
    print(
        render_markdown(
            report,
            risk_left=risk_a,
            risk_right=risk_b,
            facts_left=facts_a,
            facts_right=facts_b,
            label_left=label_a,
            label_right=label_b,
        )
    )
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    catalog = rule_catalog()
    if args.json:
        print(json.dumps({"engine": ENGINE_VERSION, "rules": catalog}, indent=2))
        return 0
    print(f"LawRisk risk engine: {ENGINE_VERSION} ({len(catalog)} rules)")
    for r in catalog:
        kind = "absence" if r["kind"] == "absence" else "paragraph"
        cond = f"  condition: {r['condition']}" if r.get("condition") else ""
        print(f"  {r['rule_id']} [{r['dimension']} sv={r['severity']} {kind}] {r['reason']}{cond}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="lawrisk-cli",
        description="Offline LawRisk: deterministic contract risk scoring, review and clause diff.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="score a single document")
    p_score.add_argument("file")
    p_score.add_argument("--name", default="", help="label stored as the document id")
    p_score.add_argument("--json", action="store_true", help="emit the RiskReport as JSON")
    p_score.set_defaults(func=cmd_score)

    p_review = sub.add_parser("review", help="score a document and render the Markdown review report")
    p_review.add_argument("file")
    p_review.add_argument("--name", default="", help="display name of the document")
    p_review.add_argument("--json", action="store_true", help="emit findings JSON instead of Markdown")
    p_review.set_defaults(func=cmd_review)

    p_diff = sub.add_parser("diff", help="diff two documents and render the Markdown diff report")
    p_diff.add_argument("file_a")
    p_diff.add_argument("file_b")
    p_diff.add_argument("--name-a", default="", help="label for the left document")
    p_diff.add_argument("--name-b", default="", help="label for the right document")
    p_diff.add_argument("--json", action="store_true", help="emit the diff and risk panels as JSON")
    p_diff.set_defaults(func=cmd_diff)

    p_rules = sub.add_parser("rules", help="print the rule handbook (catalog)")
    p_rules.add_argument("--json", action="store_true", help="emit the catalog as JSON")
    p_rules.set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
