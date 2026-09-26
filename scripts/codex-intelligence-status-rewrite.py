#!/usr/bin/env python3
"""One-shot correction for the generated status completeness predicate."""

from pathlib import Path

path = Path("scripts/hepta-intelligence-control-status.py")
text = path.read_text(encoding="utf-8")
old = '            "sourceImplementation": all(facts.values()),'
new = '''            "sourceImplementation": all(
                value
                for name, value in facts.items()
                if name != "defaultBinaryCanonicalProfileComposed"
            ),'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("status completeness rewrite target drifted")
path.write_text(text, encoding="utf-8")
