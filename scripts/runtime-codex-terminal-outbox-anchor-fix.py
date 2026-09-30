#!/usr/bin/env python3
"""Repair the terminal-outbox migration anchor after nonce hardening.

The maintainer follow-up intentionally replaces the live-process nonce buffer
and `RngCore::fill_bytes` call with `rand::random()`.  The following terminal
outbox migration used the pre-hardening method body as an exact structural
anchor, so the ordered migration chain stopped before materializing the outbox.
This one-shot construction fix updates both the legacy anchor and replacement
body to the hardened form.  It is deleted together with all source-writing
migrations from the immutable ordinary-source candidate.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/runtime-codex-terminal-outbox-migration.py"

OLD = '''        let mut abort_nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut abort_nonce);
'''
NEW = '''        // Generated for each live process; never a source-embedded cryptographic value.
        let abort_nonce: [u8; 32] = rand::random();
'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count == 0:
        if text.count(NEW) >= 2:
            return
        raise RuntimeError("terminal-outbox nonce anchor is neither legacy nor hardened")
    if count != 2:
        raise RuntimeError(f"expected two terminal-outbox nonce blocks, found {count}")
    TARGET.write_text(text.replace(OLD, NEW), encoding="utf-8")


if __name__ == "__main__":
    main()
