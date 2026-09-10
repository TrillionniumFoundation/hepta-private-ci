#!/usr/bin/env python3
"""Apply deterministic, hash-pinned repairs to recovered Lane F source."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Repair:
    path: str
    raw_sha256: str
    repaired_sha256: str
    replacements: tuple[tuple[str, str], ...]
    invariant: str


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

REPAIRS = (
    Repair(
        path="codex-rs/hepta-intuition/src/calibrated.rs",
        raw_sha256="168aa033fc0eeeb2c4ff4bcc99782f39dcf514b9e26fe8add8b6b441fe7aa8e5",
        repaired_sha256="d0afe648d436deffbecdf816372e5fd95a2947bc9507246e44c46b3dd1d988d7",
        replacements=(
            (CALL_MARKER, CALL_REPLACEMENT),
            (SELECT_MARKER, VALIDATOR + SELECT_MARKER),
        ),
        invariant="counter-based assignment is validated before any slow-path disposition",
    ),
    Repair(
        path="codex-rs/hepta-plasticity/src/durable_registry.rs",
        raw_sha256="7c17e0e071bb99397628c8d533132c36343c3486b1246b770fb576ef112db952",
        repaired_sha256="bb5b9fe6c7620d6938e8662d9006f457fa64903d9c0ad7b8f6660975e8d75d72",
        replacements=((
            ".insert(proposal.proposal_id.clone(), receipt.clone());",
            ".insert(proposal.proposal_id, receipt.clone());",
        ),),
        invariant="durable append transfers the final proposal identifier without a redundant clone",
    ),
    Repair(
        path="codex-rs/hepta-intelligence/src/pipeline.rs",
        raw_sha256="7938bd5f6f716552977442356848467ce84be2af35361137328de3f05f8bc2ba",
        repaired_sha256="cfa1e72aafca8a2e86059a912ab603fce78041670c02fbee9fe5915d04d153fc",
        replacements=((
            "stages.iter().any(|value| *value == 0)",
            "stages.contains(&0)",
        ),),
        invariant="budget validation uses the canonical slice membership primitive",
    ),
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def apply_repair(root: Path, repair: Repair, check: bool) -> dict[str, object]:
    target = root / repair.path
    if not target.is_file():
        raise ValueError(f"missing recovered source: {repair.path}")
    before = target.read_bytes()
    before_sha = digest(before)
    if check:
        if before_sha != repair.repaired_sha256:
            raise ValueError(
                f"repaired source digest mismatch for {repair.path}: "
                f"expected {repair.repaired_sha256}, got {before_sha}"
            )
    else:
        if before_sha != repair.raw_sha256:
            raise ValueError(
                f"raw recovered source digest mismatch for {repair.path}: "
                f"expected {repair.raw_sha256}, got {before_sha}"
            )
        text = before.decode("utf-8")
        for marker, replacement in repair.replacements:
            if text.count(marker) != 1:
                raise ValueError(f"unexpected deterministic marker in {repair.path}")
            text = text.replace(marker, replacement, 1)
        after = text.encode("utf-8")
        after_sha = digest(after)
        if after_sha != repair.repaired_sha256:
            raise ValueError(
                f"deterministic repair digest mismatch for {repair.path}: "
                f"expected {repair.repaired_sha256}, got {after_sha}"
            )
        target.write_bytes(after)
    return {
        "path": repair.path,
        "rawSha256": repair.raw_sha256,
        "repairedSha256": repair.repaired_sha256,
        "invariant": repair.invariant,
    }


def repair_all(root: Path, check: bool) -> dict[str, object]:
    rows = [apply_repair(root, repair, check) for repair in REPAIRS]
    return {
        "schema": "hepta.lane-f-source-repair-receipt.v2",
        "status": "PASS_LANE_F_SOURCE_REPAIR",
        "mode": "check" if check else "materialize",
        "repairs": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = repair_all(args.root.resolve(), args.check)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
