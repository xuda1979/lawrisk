# LawRisk — 中小律所合同风险分 + 条款差异树

Law-firm contract risk scoring + clause diff tree (Harvey slice for SMB law
firms). Upload two document templates (DOCX / PDF / TXT) and get:

1. **Explainable risk score** — deterministic 0–100 per document, split into
   commercial / liability / data-protection / export-compliance dimensions.
   Every point deducted carries a reason, the rule id and the verbatim source
   paragraph (no "AI said high risk" — everything is reproducible).
2. **Clause diff tree** — a paragraph-level diff between the two templates,
   organised by section, with each change marked as added / removed / modified
   and described by a readable semantic summary.
3. **Rendering** — side-by-side web view, a scrollable diff tree, and a
   self-contained Markdown report.
4. **Template library (P3)** — bundled baseline clause sets (MSA, SaaS, NDA,
   DPA). Diff an incoming agreement against a known-good structure via
   `POST /api/templates/{id}/compare`, list them via `GET /api/templates`.
5. **Contract key-facts panel (P4)** — every compared document also surfaces
   its extracted business fields: deal currency, term, governing law and
   arbitration seat, each with the verbatim source paragraph.
6. **Single-document risk review (P4)** — score one agreement and get findings
   grouped under the contract sections they fall in, plus standalone
   Markdown / DOCX / HTML review reports. New `Review one` mode in the SPA.

Everything runs locally on regex/keyword rules (低成本、可复现). LLM
summarisation is optional and off by default.

## Tech stack

- Python 3.14, FastAPI, pydantic v2, python-docx, pypdf
- Diff: difflib (Myers-style) paragraph-level diff — local, deterministic
- Frontend: React 19 + TypeScript + Vite (single page, works offline against
  the local API)

## Quick start

```bash
# backend
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn lawrisk.api:app --reload --port 8000

# frontend (separate terminal, dev mode with HMR)
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Open http://localhost:5173, choose two templates (fixtures live in
`tests/fixtures/`, e.g. `template_a.docx` vs `template_b.docx`), and click
**Compare & score**.

### Single-port production serving

Build the SPA once, then run one process that serves both the API and the UI:

```bash
cd frontend && npm run build          # writes frontend/dist
cd ..
.venv/bin/python -m lawrisk.serve --host 127.0.0.1 --port 8000
# or: .venv/bin/uvicorn lawrisk.api:app --port 8000
```

Open http://localhost:8000 — `/` returns the SPA, `/api/*` the API, and any
unknown `/api/...` route is a 404 (not the SPA fallback). The static mount is
skipped when `LAWRISK_SERVE_SPA=0`.

### API

| Endpoint        | Method | Description                                       |
|-----------------|--------|---------------------------------------------------|
| `/api/health`   | GET    | Health + LLM flag                                 |
| `/api/parse`    | POST   | Multipart file → paragraphs + extracted fields    |
| `/api/score`    | POST   | JSON `{paragraphs: [...]}` → deterministic RiskReport |
| `/api/compare`  | POST   | Two files `template_a` + `template_b` → diff + risks + markdown |
| `/api/diff-text`| POST   | JSON `{left, right, ...}` → CompareResult for plain text |
| `/api/templates`| GET    | List the bundled clause-template library (P3)          |
| `/api/templates/{id}/compare` | POST | One file → diff vs a baseline template + risk panel |
| `/api/rules`   | GET    | Rule handbook: the full deterministic rule catalog (id, dimension, severity, reason, mitigation, kind) |
| `/api/review`  | POST   | One file → section-grouped risk review + Markdown/DOCX/HTML reports |

Uploaded files are size-limited to 20 MiB (413 on exceed). All endpoints are
local, deterministic and LLM-free by default.

### Command-line interface

`lawrisk-cli` runs the same parse → score → diff pipeline directly on local
files, with no server required. Deterministic and LLM-free, matching the web
API exactly:

```bash
lawrisk-cli score  tests/fixtures/risky_contract.docx      # verdict line
lawrisk-cli review tests/fixtures/risky_contract.docx      # Markdown review report
lawrisk-cli diff   tests/fixtures/template_a.docx tests/fixtures/template_b.docx
lawrisk-cli rules                                        # rule handbook
```

Every subcommand takes `--json` to emit machine-readable output instead;
`diff` accepts `--name-a/--name-b` labels. All inputs accept DOCX / PDF / TXT
(dispatched by file extension). `python -m lawrisk.cli ...` is equivalent.

### LLM enhancement (optional)

Set `LAWRISK_LLM=1` to enable the summary layer; `LAWRISK_LLM_PROVIDER=mock`
(the default) selects the deterministic mock summariser. Implement your own by
subclassing `lawrisk.llm.Summarizer` and registering it (see `test_llm.py`).
Without the flag the pipeline never touches the network and results are fully
local and reproducible.

## Risk engine

`lawrisk/rules.py` compiles a fixed rule set (auto-renewal, one-sided
termination, unilateral price changes, unilateral amendment without consent,
assignment without consent, liability caps, indemnities, warranties
disclaimers, data transfers, sanctioned jurisdictions, export controls, …).
Each rule fires on the already-extracted
paragraphs and emits a `Penalty` with `reason`, `rule_id`, `severity`, and a
verbatim `excerpt`. Dimension scores cap at 100 and are weighted into the
overall 0–100 score. The report carries a `deterministic_hash` (SHA-256 of
content + engine version) so identical input provably yields identical output.

## Diff engine

`lawrisk/diff/differ.py` splits each document into sections at headings,
aligns sections by heading signature, then diffs paragraphs inside aligned
sections (`difflib.SequenceMatcher`). Each change becomes a `DiffItem`
(added/removed/modified) with global paragraph indices into both documents
and a keyword-driven semantic summary. `lawrisk/diff/sidebyside.py` flattens
those items into aligned rows (with word-level add/remove tokens) for the web
view; `lawrisk/diff/markdown_report.py` renders the Markdown diff report.

## Template library

`lawrisk/templates.py` ships four curated baseline clause sets — `msa`, `sps`
(SaaS), `nda` and `saas-dpa` — used as comparison baselines. Each template is
plain text (versioned with the repo, no network needed), exposes its sections
and a deterministic content hash, and can be diffed against any uploaded
document with `POST /api/templates/msa/compare`. Dump them offline with:

```bash
.venv/bin/python scripts/dump_templates.py            # JSON to stdout
.venv/bin/python scripts/dump_templates.py --md out.md
```

## Tests

```bash
pytest -q        # 98 tests, all local
cd frontend && npm run build   # verifies the SPA compiles
```

Fixtures are generated by `scripts/gen_fixtures.py` and committed under
`tests/fixtures/`. Key acceptance coverage:

- `tests/test_scoring.py` — determinism (same input → same score & hash),
  explainability (every finding has reason + excerpt), calibration (risky
  fixture HIGH, clean fixture LOW, template B riskier than A), per-rule meshes.
- `tests/test_diff.py` — the `diff_template_x` vs `diff_template_y` fixture
  yields 30+ marked differences, tree organised by section, indices point back
  at the source paragraphs, summaries are readable, markdown report is valid.
- `tests/test_api.py` — FastAPI integration for health/score/parse/compare/​diff-text.
- `tests/test_api_extended.py` — template endpoints, size limits, diff-text risk
  panels, SPA static serving.
- `tests/test_templates.py` — P3 template-library registry + diff-vs-template.
- `tests/test_llm.py` — provider registry, deterministic mock, custom providers.
- `tests/test_parser.py` — DOCX/TXT ingestion + field extraction.

## Non-goals

- Full legal advice (this is a risk detection + diff tool)
- Automatic contract drafting
