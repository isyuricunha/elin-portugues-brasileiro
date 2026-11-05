#!/usr/bin/env python3
"""Validation rules for Elin PT-BR translation units.

A translation is accepted only when it preserves the game's structural
markers exactly: token multiset, newline count, and whitespace hygiene.
These checks mirror the reference mod's contract: the game reads ids and
columns in place, so content may change but structure may not.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"\{[^{}]*\}|#[A-Za-z][A-Za-z0-9_]*|#\d+|\\[nN]|[+][A-Z]+\b|(?<![A-Za-z0-9#])[A-Z]\+(?= )")


def tokens(text: str) -> list[str]:
    # '#word' is a subject placeholder: only the '#marker' is structural,
    # the word after it is translatable. '#1' and other digits are exact.
    # {topic,...} and {link,...} carry display text: the game renders the
    # content (the reference CN package translates inside them), so only the
    # directive head is structural. {if}/{endif} and the rest stay exact.
    toks = []
    for tok in TOKEN_RE.findall(text or ""):
        head = re.match(r"\{(topic|link),", tok)
        if head:
            tok = "{" + head.group(1) + ",}"
        elif re.match(r"\{pair\|", tok) or re.match(r"\{[QA]\|", tok):
            # {pair|label|description} and {Q|...}/{A|...}: display text,
            # only the directive shape is structural
            tok = "{pair||}" if tok.startswith("{pair|") else tok.split("|", 1)[0] + "|}"
        if tok in ("+D", "D+"):
            # Word_mix name patterns: the D placeholder changes position
            # with PT word order ('$god's D' -> 'D de $god')
            tok = "D"
        if tok == "A+":
            # Alias_mix article placeholder 'A+' translates to a PT article
            # (gender-unknown, masculine default); structural check skips it
            continue
        toks.append(tok)
    return sorted(re.sub(r"^#[A-Za-z][A-Za-z0-9_]*$", "#", tok) for tok in toks)


def check_unit(source: str, translation: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    warnings_list: list[str] = []
    s = str(source)
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff")
    if translation is None or not str(translation).strip():
        # CJK-verbatim sources stay empty by rule: the game falls back to EN/JP.
        if cjk * 2 >= len(s):
            return True, []
        return False, ["empty translation"]
    t = str(translation)

    if t != t.strip() and s == s.strip():
        errors.append("leading/trailing whitespace added")
    if tokens(s) != tokens(t):
        errors.append(f"token multiset differs: src={tokens(s)} pt={tokens(t)}")
    if s.count("\n") != t.count("\n"):
        errors.append(f"newline count differs: src={s.count(chr(10))} pt={t.count(chr(10))}")
    for ch in t:
        if ord(ch) < 32 and ch not in ("\n", "\t", "\r"):
            errors.append(f"control character U+{ord(ch):04X}")
            break
    ratio = len(t) / max(len(s), 1)
    # CJK sources are ~2-3x denser than Portuguese: allow a wider ratio band
    if cjk * 2 >= len(s):
        lo, hi, lo_w, hi_w = 0.15, 8.0, 0.3, 6.0
    else:
        lo, hi, lo_w, hi_w = 0.25, 3.5, 0.5, 2.5
    if len(s) >= 12 and (ratio > hi or ratio < lo):
        errors.append(f"length ratio {ratio:.2f} out of bounds")
    elif len(s) >= 12 and (ratio > hi_w or ratio < lo_w):
        warnings_list.append(f"length ratio {ratio:.2f} unusual")

    return not errors, errors + [f"warning: {w}" for w in warnings_list]


def validate_batch(queue_path: Path, batch_path: Path) -> tuple[int, int, list[str]]:
    units = {}
    with queue_path.open(encoding="utf-8") as fh:
        for line in fh:
            u = json.loads(line)
            units[u["id"]] = u
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    ok = fail = 0
    problems = []
    for uid, pt in batch.items():
        unit = units.get(uid)
        if unit is None:
            fail += 1
            problems.append(f"{uid}: unknown unit id")
            continue
        good, msgs = check_unit(unit["source"], pt)
        if good:
            ok += 1
        else:
            fail += 1
            problems.append(f"{uid}: " + "; ".join(msgs))
    return ok, fail, problems


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: validate.py <queue.jsonl> <batch.json>", file=sys.stderr)
        raise SystemExit(2)
    ok, fail, problems = validate_batch(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"ok={ok} fail={fail}")
    for p in problems[:20]:
        print("  ", p)
    raise SystemExit(1 if fail else 0)
