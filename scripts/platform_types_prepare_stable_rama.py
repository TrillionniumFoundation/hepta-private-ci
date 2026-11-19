#!/usr/bin/env python3
"""Read-only compatibility entrypoint for the retired Rama repair.

The one-shot source/lock mutation has already been replaced by exact manifest
constraints, a reviewed lock graph, and a fail-closed guard.  Retaining this
filename avoids breaking operator bookmarks, but invoking it can no longer
rewrite source, manifests, documentation, or Cargo.lock.
"""

from __future__ import annotations

from pathlib import Path

from platform_types_rama_lock_guard import validate


def main() -> None:
    validate(
        Path("codex-rs/network-proxy/Cargo.toml"),
        Path("codex-rs/Cargo.lock"),
    )
    print("platform.types Rama preparation: retired; reviewed graph verified read-only")


if __name__ == "__main__":
    main()
