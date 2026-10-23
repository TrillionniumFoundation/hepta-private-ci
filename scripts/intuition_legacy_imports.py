#!/usr/bin/env python3
"""Move replay-only intuition calls off the default crate-root product surface."""

from pathlib import Path


REPLACEMENTS = {
    "codex-rs/hepta-intelligence/src/evaluated_shadow.rs": (
        "use codex_hepta_intuition::decide_calibrated_v2;\n",
        "use codex_hepta_intuition::calibrated::decide_calibrated_v2;\n",
    ),
    "codex-rs/hepta-intelligence/src/intuition_qualification.rs": (
        "use codex_hepta_intuition::decide_calibrated_v2;\n",
        "use codex_hepta_intuition::calibrated::decide_calibrated_v2;\n",
    ),
    "codex-rs/hepta-intelligence/tests/lane_f_shadow_vertical.rs": (
        "use codex_hepta_intuition::decide_calibrated;\n",
        "use codex_hepta_intuition::calibrated::decide_calibrated;\n",
    ),
}


def main() -> None:
    for name, (old, new) in REPLACEMENTS.items():
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        if old in text:
            if text.count(old) != 1:
                raise SystemExit(f"{name}: duplicate legacy import")
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
        elif new not in text:
            raise SystemExit(f"{name}: legacy import anchor missing")


if __name__ == "__main__":
    main()
