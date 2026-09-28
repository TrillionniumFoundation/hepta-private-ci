#!/usr/bin/env python3
"""Run the blob-pinned publication/Vector transformer without its redundant CLI assertion."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    root = Path.cwd().resolve()
    source = root / "scripts/hepta_memory_retrieval_publication_vector.py"
    name = "hepta_memory_retrieval_publication_vector_impl"
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise SystemExit("unable to load publication/vector transformer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    changed = module.apply(root)
    expected = set(module.EXPECTED_BLOBS)
    if len(changed) != len(expected) or set(changed) != expected:
        raise SystemExit(
            f"transformation inventory mismatch: expected {sorted(expected)}, got {sorted(changed)}"
        )
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
