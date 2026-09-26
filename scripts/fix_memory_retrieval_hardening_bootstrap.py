#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

path = Path(__file__).with_name("apply_memory_retrieval_hardening.py")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r'''replace_once\(\n    GB,\n    """            if !is_strictly_sorted_unique\(&entry\.contradiction_evidence\).*?\n\)\n(?=replace_once\(\n    GB,\n    """            push_len\(&mut bytes, entry\.contradiction_evidence\.len\(\)\);)''',
    re.S,
)
replacement = r'''regex_once(
    GB,
    r"""            if\s+!is_strictly_sorted_unique\(&entry\.contradiction_evidence\)\s*
                \|\|\s*entry\s*
                    \.contradiction_evidence\s*
                    \.iter\(\)\s*
                    \.any\(\|digest\|\s*digest\.is_zero\(\)\)\s*
            \{\s*
                return Err\(RecallErrorV1::NonCanonicalCollection\(\s*
                    "union_contradiction_groups",\s*
                \)\);\s*
            \}""",
    """            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
            {
                return Err(RecallErrorV1::NonCanonicalCollection(
                    "union_contradiction_evidence",
                ));
            }""",
)
'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"failed to rewrite strict union contradiction bootstrap block: {count}")
path.write_text(text, encoding="utf-8")
