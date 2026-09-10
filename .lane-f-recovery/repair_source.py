#!/usr/bin/env python3
"""Apply deterministic, hash-pinned repairs to recovered Lane F source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PATH = Path("codex-rs/hepta-intuition/src/calibrated.rs")
RAW_SHA256 = "168aa033fc0eeeb2c4ff4bcc99782f39dcf514b9e26fe8add8b6b441fe7aa8e5"
REPAIRED_SHA256 = "d0afe648d436deffbecdf816372e5fd95a2947bc9507246e44c46b3dd1d988d7"

CALL_MARKER = """        eligible.push(candidate);
    }

    let disposition = if request.risk_class == RiskClass::High {
"""
CALL_REPLACEMENT = """        eligible.push(candidate);
    }

    validate_assignment(&request, &eligible)?;

    let disposition = if request.risk_class == RiskClass::High {
"""

SELECT_MARKER = """fn select(
    request: &CalibratedDecisionRequestV1,
    eligible: &[&CalibratedActionCandidateV1],
) -> Result<CalibratedDispositionV1, CalibratedError> {
"""
VALIDATOR = """fn validate_assignment(
    request: &CalibratedDecisionRequestV1,
    eligible: &[&CalibratedActionCandidateV1],
) -> Result<(), CalibratedError> {
    let AssignmentModeV1::CounterBased {
        random_stream_digest,
        draw,
        abstain_probability,
    } = &request.assignment
    else {
        return Ok(());
    };

    if random_stream_digest.is_zero() {
        return Err(CalibratedError::EmptyDigest("random stream"));
    }
    if *draw == ProbabilityQ32::ONE {
        return Err(CalibratedError::RandomDrawOutOfRange);
    }
    let eligible_ids = eligible
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<BTreeSet<_>>();
    let mut total = u128::from(abstain_probability.raw());
    for candidate in &request.candidates {
        if !eligible_ids.contains(&candidate.candidate_id)
            && candidate.assignment_probability != ProbabilityQ32::ZERO
        {
            return Err(CalibratedError::ProbabilityForIneligibleCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        total = total
            .checked_add(u128::from(candidate.assignment_probability.raw()))
            .ok_or(CalibratedError::Arithmetic)?;
    }
    if total != u128::from(ProbabilityQ32::ONE.raw()) {
        return Err(CalibratedError::ProbabilityNotNormalized);
    }
    Ok(())
}

"""


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def repair(root: Path, check: bool) -> dict[str, object]:
    target = root / PATH
    if not target.is_file():
        raise ValueError(f"missing recovered source: {PATH}")
    before = target.read_bytes()
    before_sha = digest(before)

    if check:
        if before_sha != REPAIRED_SHA256:
            raise ValueError(
                f"repaired source digest mismatch for {PATH}: "
                f"expected {REPAIRED_SHA256}, got {before_sha}"
            )
        return {
            "schema": "hepta.lane-f-source-repair-receipt.v1",
            "status": "PASS_LANE_F_SOURCE_REPAIR",
            "mode": "check",
            "path": str(PATH),
            "rawSha256": RAW_SHA256,
            "repairedSha256": REPAIRED_SHA256,
        }

    if before_sha != RAW_SHA256:
        raise ValueError(
            f"raw recovered source digest mismatch for {PATH}: "
            f"expected {RAW_SHA256}, got {before_sha}"
        )
    text = before.decode("utf-8")
    if text.count(CALL_MARKER) != 1:
        raise ValueError("unexpected calibrated decision call marker")
    if text.count(SELECT_MARKER) != 1:
        raise ValueError("unexpected calibrated select marker")
    text = text.replace(CALL_MARKER, CALL_REPLACEMENT, 1)
    text = text.replace(SELECT_MARKER, VALIDATOR + SELECT_MARKER, 1)
    after = text.encode("utf-8")
    after_sha = digest(after)
    if after_sha != REPAIRED_SHA256:
        raise ValueError(
            f"deterministic repair digest mismatch: expected {REPAIRED_SHA256}, got {after_sha}"
        )
    target.write_bytes(after)
    return {
        "schema": "hepta.lane-f-source-repair-receipt.v1",
        "status": "PASS_LANE_F_SOURCE_REPAIR",
        "mode": "materialize",
        "path": str(PATH),
        "rawSha256": RAW_SHA256,
        "repairedSha256": REPAIRED_SHA256,
        "invariant": "counter-based assignment is validated before any slow-path disposition",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = repair(args.root.resolve(), args.check)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
