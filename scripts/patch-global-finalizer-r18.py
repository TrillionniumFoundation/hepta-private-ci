#!/usr/bin/env python3
"""Teach r7 to distinguish a recovered stale-lock probe from a final failure."""
from __future__ import annotations

from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if marker in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r18 patch precondition drift for {marker!r}: count={count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")

    old_normalize = '''def normalize_lockfile() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metadata, first = cargo_metadata(locked=True)
    receipts = [first]
    if metadata is not None:
        return metadata, receipts
    metadata, unlocked = cargo_metadata(locked=False)
    receipts.append(unlocked)
    if metadata is None:
        return None, receipts
    metadata, locked_again = cargo_metadata(locked=True)
    receipts.append(locked_again)
    return metadata, receipts
'''
    new_normalize = '''def normalize_lockfile() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metadata, first = cargo_metadata(locked=True)
    receipts = [first]
    if metadata is not None:
        return metadata, receipts
    metadata, unlocked = cargo_metadata(locked=False)
    receipts.append(unlocked)
    if metadata is None:
        return None, receipts
    metadata, locked_again = cargo_metadata(locked=True)
    receipts.append(locked_again)
    if metadata is not None and locked_again.get("returnCode") == 0:
        first["expectedFailure"] = "stale_lockfile_regeneration_probe"
        first["recoveredBy"] = {
            "unlockedMetadataOutputSha256": unlocked.get("outputSha256"),
            "lockedRecheckOutputSha256": locked_again.get("outputSha256"),
        }
    return metadata, receipts
'''
    text = replace_once(
        text,
        old_normalize,
        new_normalize,
        'first["expectedFailure"] = "stale_lockfile_regeneration_probe"',
    )

    old_helper = '''def command_receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(
        "skipped" in receipt or receipt.get("returnCode") == 0 for receipt in receipts
    )


def prepare(args: argparse.Namespace) -> int:
'''
    new_helper = '''def command_receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(
        "skipped" in receipt or receipt.get("returnCode") == 0 for receipt in receipts
    )


def lock_receipts_pass(receipts: Iterable[dict[str, Any]]) -> bool:
    return all(
        receipt.get("returnCode") == 0
        or receipt.get("expectedFailure") == "stale_lockfile_regeneration_probe"
        for receipt in receipts
    )


def prepare(args: argparse.Namespace) -> int:
'''
    text = replace_once(
        text,
        old_helper,
        new_helper,
        "def lock_receipts_pass(",
    )

    text = replace_once(
        text,
        "        and command_receipts_pass(lock_receipts)\n",
        "        and lock_receipts_pass(lock_receipts)\n",
        "and lock_receipts_pass(lock_receipts)",
    )

    required = (
        'first["expectedFailure"] = "stale_lockfile_regeneration_probe"',
        '"lockedRecheckOutputSha256": locked_again.get("outputSha256")',
        "def lock_receipts_pass(",
        'receipt.get("expectedFailure") == "stale_lockfile_regeneration_probe"',
        "and lock_receipts_pass(lock_receipts)",
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"r18 output missing required phrase: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
