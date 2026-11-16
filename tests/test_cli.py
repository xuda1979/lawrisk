"""P4/CLI: the offline command-line interface is deterministic and complete."""

from __future__ import annotations

import json
from pathlib import Path

from lawrisk.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _run(*argv: str) -> int:
    try:
        return main(list(argv))
    except SystemExit as exc:
        assert exc.code == 0, f"lawrisk-cli {' '.join(argv)} exited {exc.code}"
        return 0


def test_score_prints_verdict_and_parses_json(capsys):
    _run("score", str(FIXTURES / "risky_contract.docx"))
    out = capsys.readouterr().out
    assert "/100" in out and "findings" in out
    assert "hash" in out

    _run("score", str(FIXTURES / "clean_contract.docx"), "--json")
    report = json.loads(capsys.readouterr().out)
    assert report["overall_level"] == "low"
    assert report["penalties"] == []
    assert {"overall_score", "deterministic_hash", "dimensions"} <= set(report)


def test_review_renders_markdown_review(capsys):
    _run("review", str(FIXTURES / "risky_contract.docx"))
    md = capsys.readouterr().out
    assert md.startswith("# Contract Risk Review")
    assert "Overall risk" in md

    _run("review", str(FIXTURES / "risky_contract.docx"), "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["document_name"]
    assert payload["risk"]["penalties"]


def test_diff_renders_markdown_diff(capsys):
    fx = FIXTURES / "diff_template_x.docx"
    fy = FIXTURES / "diff_template_y.docx"
    _run("diff", str(fx), str(fy), "--name-a", "X", "--name-b", "Y")
    md = capsys.readouterr().out
    assert md.startswith("# Contract Clause Diff Report")
    assert "**Document A:** X" in md and "**Document B:** Y" in md

    _run("diff", str(fx), str(fy), "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["diff"]["stats"]["modifications"] >= 1


def test_rules_prints_full_catalog(capsys):
    _run("rules")
    out = capsys.readouterr().out
    assert "LawRisk risk engine:" in out
    assert "R-DATA-4" in out  # an absence rule is part of the handbook

    _run("rules", "--json")
    catalog = json.loads(capsys.readouterr().out)
    assert len(catalog["rules"]) >= 15
    assert {e["dimension"] for e in catalog["rules"]} >= {
        "commercial",
        "liability",
        "data",
        "export",
    }


def test_score_rejects_file_with_no_paragraphs(capsys):
    tmp = Path("tests/_empty.txt")
    tmp.write_text("\n\n\n", encoding="utf-8")
    try:
        try:
            main(["score", str(tmp)])
            raise AssertionError("expected SystemExit(2)")
        except SystemExit as exc:
            assert exc.code == 2
    finally:
        tmp.unlink()
