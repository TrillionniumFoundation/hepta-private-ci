#!/usr/bin/env python3
"""Run the reviewed cognitive.read convergence repair with newline-tolerant matching.

The authored repair intentionally rejects semantic source drift. This launcher
normalizes only the presence or absence of one terminal newline so Git's text
shape cannot turn an otherwise exact reviewed replacement into a false failure.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "scripts/repair-cognitive-read-qualification.py"


def load_repair_module():
    spec = importlib.util.spec_from_file_location(
        "cognitive_read_convergence_repair",
        REPAIR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load cognitive.read convergence repair")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once_tolerating_terminal_newline(
    path: Path,
    old: str,
    new: str,
) -> None:
    body = path.read_text(encoding="utf-8")
    new_variants = {new, new.rstrip("\n")}
    if any(variant and body.count(variant) == 1 for variant in new_variants):
        return

    candidates = (
        (old, new),
        (old.rstrip("\n"), new.rstrip("\n")),
    )
    for candidate, replacement in candidates:
        if candidate and body.count(candidate) == 1:
            path.write_text(body.replace(candidate, replacement, 1), encoding="utf-8")
            return

    raise ValueError(f"convergence source shape drift: {path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()

    module = load_repair_module()
    module.replace_once = replace_once_tolerating_terminal_newline
    sys.argv = [str(REPAIR), "--expected-sha", args.expected_sha]
    module.main()


if __name__ == "__main__":
    main()
