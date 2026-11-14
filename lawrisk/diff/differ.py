"""Clause diff tree: section-aware paragraph diff between two documents.

Algorithm (all local, deterministic):
  1. Split each document into sections at heading paragraphs.
  2. Align sections by label (difflib.SequenceMatcher).
  3. Within aligned sections, align paragraphs; mark add/delete/modify.
  4. Summarise each change with keyword-driven, deterministic semantic captions.

AC3/AC4: fixtures with 30+ changes produce marked add/remove/modify items each
with a readable summary.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from lawrisk.models import (
    DiffItem,
    DiffNode,
    DiffOp,
    DiffReport,
    DiffStats,
)
from lawrisk.textutil import looks_like_heading, normalize

_WORD_RE = re.compile(r"\S+")


@dataclass
class _Section:
    heading: str = ""
    head_level: int = 0
    paras: List[str] = None  # type: ignore[assignment]
    start: int = 0  # global index (into the doc's paragraph array) of paras[0]

    def __post_init__(self) -> None:
        if self.paras is None:
            self.paras = []


def _heading_level(text: str) -> int:
    t = text.strip()
    m = re.match(r"^(\d+)(?:\.(\d+))*\s*", t)
    if m:
        depth = len(m.group(0).strip(" .")) + 1  # rough: more digits → deeper
        return depth
    if re.match(r"^(?:ARTICLE|SECTION)\b", t, re.IGNORECASE):
        return 1
    if re.match(r"^第", t):
        return 1
    return 1


def split_sections(paragraphs: Sequence[str]) -> List[_Section]:
    sections: List[_Section] = []
    current = _Section()
    start = 0
    for idx, p in enumerate(paragraphs):
        if looks_like_heading(p):
            sections.append(current if current.paras or current.heading else _Section())
            current = _Section(heading=p, head_level=_heading_level(p), start=idx + 1)
            start = idx + 1
        else:
            if not current.paras and not current.heading:
                current.start = idx
            current.paras.append(p)
    if current.heading or current.paras:
        sections.append(current)
    return [s for s in sections if s.heading or s.paras]


# ---------------------------------------------------------------------------
# Semantic impact: deterministic keyword-driven captions
# ---------------------------------------------------------------------------
_SUMMARY_FACTS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"auto[- ]?renew", re.IGNORECASE), "renewal mechanics"),
    (re.compile(r"terminat", re.IGNORECASE), "termination"),
    (re.compile(r"notice", re.IGNORECASE), "notice period"),
    (re.compile(r"indemnif", re.IGNORECASE), "indemnification"),
    (re.compile(r"liab\w+", re.IGNORECASE), "liability"),
    (re.compile(r"warrant", re.IGNORECASE), "warranties"),
    (re.compile(r"personal (?:data|information)", re.IGNORECASE), "data protection"),
    (re.compile(r"transfer", re.IGNORECASE), "data transfer"),
    (re.compile(r"confidential", re.IGNORECASE), "confidentiality"),
    (re.compile(r"intellectual property|copyright|patent|proprietary", re.IGNORECASE), "IP ownership"),
    (re.compile(r"govern", re.IGNORECASE), "governing law"),
    (re.compile(r"arbitrat|court", re.IGNORECASE), "dispute resolution"),
    (re.compile(r"export|sanctions?|embargo", re.IGNORECASE), "export compliance"),
    (re.compile(r"\$[\d,]+(?:\.\d+)?|\d[\d,]*\s*(?:USD|EUR|RMB)", re.IGNORECASE), "financial terms"),
]


def _topics(text: str) -> List[str]:
    found: List[str] = []
    for pat, label in _SUMMARY_FACTS:
        if pat.search(text) and label not in found:
            found.append(label)
    return found[:3]


def _changed_topics(left: str, right: str) -> Tuple[List[str], List[str]]:
    ll, rr = _topics(left), _topics(right)
    added = [t for t in rr if t not in ll]
    removed = [t for t in ll if t not in rr]
    return added, removed


def _build_summary(op: DiffOp, left: str, right: str) -> str:
    if op is DiffOp.ADD:
        if not right.strip():
            return "Blank/separator line added."
        added, _ = _changed_topics("", right)
        topics = ", ".join(added) or "terms"
        return f"New paragraph added addressing {topics}."
    if op is DiffOp.DELETE:
        if not left.strip():
            return "Blank/separator line removed."
        _, removed = _changed_topics(left, "")
        topics = ", ".join(removed) or "terms"
        return f"Paragraph covering {topics} was removed."
    # modify
    added_topics, removed_topics = _changed_topics(left, right)
    parts = []
    if removed_topics:
        parts.append(f"dropped {', '.join(removed_topics)}")
    if added_topics:
        parts.append(f"added {', '.join(added_topics)}")
    if parts:
        return "Modification " + ("; ".join(parts)) + "."
    ll = left.split()
    rl = right.split()
    forced = (len(ll) + len(rl)) // 2 if ll or rl else 0
    return (
        f"Wording revised; the new text {'expands' if len(rl) > len(ll) else 'tightens' if rl else ''} "
        f"the original ({len(ll)}→{len(rl)} words)."
    ).replace("  ", " ")


def word_diff(left: str, right: str) -> Tuple[List[str], List[str]]:
    """Token-level diff for inline highlight; returns (removed, added)."""
    l_tokens = _WORD_RE.findall(left) if left else []
    r_tokens = _WORD_RE.findall(right) if right else []
    sm = difflib.SequenceMatcher(a=l_tokens, b=r_tokens, autojunk=False)
    removed: List[str] = []
    added: List[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            removed.extend(l_tokens[i1:i2])
        if tag in ("insert", "replace"):
            added.extend(r_tokens[j1:j2])
    return removed, added


def _pair_replace(
    left: Sequence[str], right: Sequence[str],
) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
    """Align a replace block pair-wise; returns (pairs, extra_left, extra_right)."""
    pairs: List[Tuple[str, str]] = []
    for i, j in zip(range(len(left)), range(len(right))):
        pairs.append((left[i], right[j]))
    extra_left = list(left[len(right):]) if len(left) > len(right) else []
    extra_right = list(right[len(left):]) if len(right) > len(left) else []
    return pairs, extra_left, extra_right


def diff_paragraphs(
    left_paras: Sequence[str],
    right_paras: Sequence[str],
    section_path: str,
    left_start: int = 0,
    right_start: int = 0,
) -> Tuple[List[DiffItem], List[int], List[int]]:
    """Compute paragraph-level diff of two section bodies.

    `left_start` / `right_start` are the global paragraph offsets of each
    section so para_index_left/right reference the full document array.

    Returns (items, matched_left_idx, matched_right_idx) where the index lists
    hold the original paragraph indices aligned 1:1 with each DiffItem.
    """
    items: List[DiffItem] = []
    left_idx: List[int] = []
    right_idx: List[int] = []
    l_norm = [normalize(p) for p in left_paras]
    r_norm = [normalize(p) for p in right_paras]
    sm = difflib.SequenceMatcher(a=l_norm, b=r_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue  # unchanged
        if tag == "delete":
            for k in range(i1, i2):
                text = left_paras[k]
                items.append(
                    DiffItem(
                        op=DiffOp.DELETE,
                        section=section_path,
                        para_index_left=left_start + k,
                        text_left=text,
                        text_right=None,
                        summary=_build_summary(DiffOp.DELETE, text, ""),
                    )
                )
                left_idx.append(left_start + k)
                right_idx.append(None)  # type: ignore[arg-type]
        elif tag == "insert":
            for k in range(j1, j2):
                text = right_paras[k]
                items.append(
                    DiffItem(
                        op=DiffOp.ADD,
                        section=section_path,
                        para_index_left=None,
                        para_index_right=right_start + k,
                        text_left=None,
                        text_right=text,
                        summary=_build_summary(DiffOp.ADD, "", text),
                    )
                )
                left_idx.append(None)  # type: ignore[arg-type]
                right_idx.append(right_start + k)
        else:  # replace
            pairs, extra_left, extra_right = _pair_replace(
                left_paras[i1:i2], right_paras[j1:j2]
            )
            for pos, (l_txt, r_txt) in enumerate(pairs):
                if normalize(l_txt) == normalize(r_txt):
                    continue
                items.append(
                    DiffItem(
                        op=DiffOp.MODIFY,
                        section=section_path,
                        para_index_left=left_start + i1 + pos,
                        para_index_right=right_start + j1 + pos,
                        text_left=l_txt,
                        text_right=r_txt,
                        summary=_build_summary(DiffOp.MODIFY, l_txt, r_txt),
                    )
                )
                left_idx.append(left_start + i1 + pos)
                right_idx.append(right_start + j1 + pos)
            for k, l_txt in enumerate(extra_left):
                items.append(
                    DiffItem(
                        op=DiffOp.DELETE,
                        section=section_path,
                        para_index_left=left_start + i1 + len(pairs) + k,
                        text_left=l_txt,
                        text_right=None,
                        summary=_build_summary(DiffOp.DELETE, l_txt, ""),
                    )
                )
                left_idx.append(left_start + i1 + len(pairs) + k)
                right_idx.append(None)  # type: ignore[arg-type]
            for k, r_txt in enumerate(extra_right):
                items.append(
                    DiffItem(
                        op=DiffOp.ADD,
                        section=section_path,
                        para_index_right=right_start + j1 + len(pairs) + k,
                        text_left=None,
                        text_right=r_txt,
                        summary=_build_summary(DiffOp.ADD, "", r_txt),
                    )
                )
                left_idx.append(None)  # type: ignore[arg-type]
                right_idx.append(right_start + j1 + len(pairs) + k)
    return items, left_idx, right_idx


def _match_sections(
    secs_l: Sequence[_Section], secs_r: Sequence[_Section]
) -> List[Tuple[_Section | None, _Section | None]]:
    """Section pairing that preserves order.

    Uses a longest-common-subsequence on the *text signature* of each heading
    (number stripped + casefolded), falling back to positional pairing for the
    unmatched spans — this pairs renamed/renumbered sections correctly while
    emitting pure add/delete sections for genuinely new/removed ones.
    """
    sig = lambda s: re.sub(r"^\s*\d+(\.\d+)*\s*[-.:]?\s*", "", s.strip()).lower() or s.lower()
    a = [sig(s.heading) for s in secs_l]
    b = [sig(s.heading) for s in secs_r]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    pairs: List[Tuple[_Section | None, _Section | None]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs.append((secs_l[i1 + k], secs_r[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                pairs.append((secs_l[k], None))
        elif tag == "insert":
            for k in range(j1, j2):
                pairs.append((None, secs_r[k]))
        else:  # replace: pair 1:1 by position, extras become add/delete.
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                l_sec = secs_l[i1 + k] if k < i2 - i1 else None
                r_sec = secs_r[j1 + k] if k < j2 - j1 else None
                pairs.append((l_sec, r_sec))
    return pairs


def build_diff_tree(
    paragraphs_left: Sequence[str],
    paragraphs_right: Sequence[str],
    document_left: str,
    document_right: str,
) -> DiffReport:
    secs_l = split_sections(paragraphs_left)
    secs_r = split_sections(paragraphs_right)

    root = DiffNode(label="document")
    stats = DiffStats(additions=0, deletions=0, modifications=0)

    for sec_l, sec_r in _match_sections(secs_l, secs_r):
        label = (sec_l.heading if sec_l else None) or (
            sec_r.heading if sec_r else None
        ) or "Preamble"
        _diff_section_into(
            root,
            sec_l or _Section(),
            sec_r or _Section(),
            label,
            stats,
        )

    return DiffReport(
        document_left=document_left,
        document_right=document_right,
        root=root,
        stats=stats,
        summary=_report_summary(stats),
    )


def _diff_section_into(
    root: DiffNode,
    sec_l: _Section,
    sec_r: _Section,
    label: str,
    stats: DiffStats,
) -> DiffNode:
    items, _, _ = diff_paragraphs(
        list(sec_l.paras or []),
        list(sec_r.paras or []),
        label,
        left_start=sec_l.start,
        right_start=sec_r.start,
    )
    for it in items:
        if it.op is DiffOp.ADD:
            stats.additions += 1
        elif it.op is DiffOp.DELETE:
            stats.deletions += 1
        else:
            stats.modifications += 1
    node = DiffNode(label=label, items=items)
    root.children.append(node)
    return node


def _report_summary(stats: DiffStats) -> str:
    return (
        f"Found {stats.additions} added, {stats.deletions} removed and "
        f"{stats.modifications} modified paragraph(s) between the two documents."
    )


# ---------------------------------------------------------------------------
# Convenience API used by the REST layer and reports
# ---------------------------------------------------------------------------
def diff_texts(
    text_left: str,
    text_right: str,
    document_left: str,
    document_right: str,
) -> DiffReport:
    """Diff two plain-text documents at paragraph level."""
    from lawrisk.textutil import split_paragraphs

    return build_diff_tree(
        split_paragraphs(text_left),
        split_paragraphs(text_right),
        document_left,
        document_right,
    )
