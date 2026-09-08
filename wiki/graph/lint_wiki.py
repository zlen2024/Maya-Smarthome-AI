#!/usr/bin/env python3
"""Lint the wiki: broken links, broken anchors, orphan pages.

Run:  python wiki/graph/lint_wiki.py       (exit 1 if anything is wrong)

Anchor slugs follow GitHub's rule: lowercase, drop characters that are not
word/space/hyphen, then map each remaining space to one hyphen. Note both
subtleties -- `_` is a WORD character and must survive, and an em-dash between
spaces leaves TWO spaces and therefore TWO hyphens.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r'[`*\[\]()]', '', s)      # markdown noise -- NOT underscore
    s = re.sub(r'[^\w\s-]', '', s)        # drop punctuation, keep _ (in \w)
    return s.replace(' ', '-').strip('-')  # each space -> one hyphen


def main() -> int:
    pages = sorted(ROOT.rglob("*.md"))
    files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    heads = {
        p.relative_to(ROOT).as_posix(): {
            slug(h) for h in re.findall(r'^#+\s+(.*)$', p.read_text(encoding='utf-8'), re.M)
        }
        for p in pages
    }
    broken, bad_anchor = [], []
    inbound = {p.relative_to(ROOT).as_posix(): 0 for p in pages}

    for p in pages:
        rel = p.relative_to(ROOT).as_posix()
        for _, tgt in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', p.read_text(encoding='utf-8')):
            if tgt.startswith(('http://', 'https://', 'mailto:')):
                continue
            path, _, anchor = tgt.partition('#')
            if not path:
                if anchor and anchor not in heads[rel]:
                    bad_anchor.append(f"{rel}: #{anchor}")
                continue
            try:
                r = (p.parent / path).resolve().relative_to(ROOT).as_posix()
            except ValueError:
                r = None
            if r is None or r not in files:
                broken.append(f"{rel} -> {tgt}")
                continue
            if r in inbound and r != rel:
                inbound[r] += 1
            if anchor and r in heads and anchor not in heads[r]:
                bad_anchor.append(f"{rel} -> {r}#{anchor}")

    orphans = [k for k, v in inbound.items() if v == 0 and k not in ("index.md", "CLAUDE.md")]
    for label, items in (("broken links", broken), ("broken anchors", bad_anchor),
                         ("orphan pages", orphans)):
        print(f"{label}: {len(items)}")
        for i in items:
            print(f"  - {i}")
    return 1 if (broken or bad_anchor or orphans) else 0


if __name__ == "__main__":
    raise SystemExit(main())
