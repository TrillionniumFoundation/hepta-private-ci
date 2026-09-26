#!/usr/bin/env python3
"""Repair exact Decision observation against the persisted V2 ledger shape."""

from pathlib import Path


PATH = Path("codex-rs/hepta-agentd/src/intelligence_learning.rs")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"{PATH}: expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;",
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;\nuse codex_hepta_learning_ledger::validate_candidate_set_completeness;",
        "completeness import",
    )
    text = replace_once(
        text,
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(completeness_digest) = validate_candidate_set_completeness(&completeness)
            else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        "completeness digest",
    )
    text = replace_once(
        text,
        "                        && value.completeness == completeness",
        "                        && value.candidate_completeness_digest == completeness_digest",
        "persisted completeness comparison",
    )
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
