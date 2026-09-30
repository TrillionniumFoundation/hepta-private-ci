#!/usr/bin/env python3
"""Move rusty_v8 preparation behind source-only qualification gates.

Lane-B truth, helper compilation and rustfmt do not require V8. Keeping those
checks ahead of the external artifact step makes source failures observable even
when the release service is unavailable. Cargo lanes still consume the exact
verified/cached V8 artifact through the repository composite action.

This helper is removed after ordinary-source materialization.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".github/workflows/runtime-codex-qualification.yml"

SETUP = '''      - uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
'''
EXACT_ANCHOR = '''      - name: Agent protocol
'''
MERGE_ANCHOR = '''      - name: Compile merge candidate
'''
EXACT_SETUP = '''      - name: Prepare verified rusty_v8 for Cargo lanes
        uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Agent protocol
'''
MERGE_SETUP = '''      - name: Prepare verified rusty_v8 for merge Cargo lanes
        uses: ./.github/actions/setup-rusty-v8
        with:
          target: x86_64-unknown-linux-gnu
      - name: Compile merge candidate
'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "Prepare verified rusty_v8 for Cargo lanes" in text:
        return
    count = text.count(SETUP)
    if count != 2:
        raise RuntimeError(f"expected two early rusty_v8 setup blocks, found {count}")
    text = text.replace(SETUP, "")
    if text.count(EXACT_ANCHOR) != 1 or text.count(MERGE_ANCHOR) != 1:
        raise RuntimeError("qualification Cargo anchors are ambiguous or absent")
    text = text.replace(EXACT_ANCHOR, EXACT_SETUP, 1)
    text = text.replace(MERGE_ANCHOR, MERGE_SETUP, 1)
    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
