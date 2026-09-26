#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one fixup match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "codex-rs/hepta-control-plane/src/planner_tests.rs",
    '''#[test]
fn extra_owner_summary_is_rejected_instead_of_poisoning_required_snapshot() {
    let mut request = snapshot_request();
    let required = request.required_owner_ids[0].clone();
    let mut summaries = vec![owner_summary(required)];
    summaries.push(owner_summary(StableId::new("unexpected-owner").expect("owner")));
    assert!(matches!(
        collect_snapshot(request, summaries),
        Err(PlannerError::UnexpectedOwner(owner)) if owner == "unexpected-owner"
    ));
}

#[test]
fn duplicate_final_payload_digest_is_rejected_not_silently_normalized() {
    let snapshot = coherent_snapshot();
    let mut request = planning_request();
    let payload = Digest32::of_bytes(b"duplicate-payload");
    request.candidates[0].final_payload_digests = vec![payload, payload];
    assert!(matches!(
        prepare_plan(&snapshot, request),
        Err(PlannerError::DuplicatePayloadDigest(_))
    ));
}
''',
    '''#[test]
fn extra_owner_summary_is_rejected_instead_of_poisoning_required_snapshot() {
    let request = snapshot_request();
    let mut unexpected = summary(OwnerReadinessV1::Ready, 950, 1_800);
    unexpected.owner_id = id("unexpected-owner");
    assert!(matches!(
        collect_snapshot(
            request,
            vec![summary(OwnerReadinessV1::Ready, 950, 1_800), unexpected]
        ),
        Err(PlannerError::UnexpectedOwner(owner)) if owner == "unexpected-owner"
    ));
}

#[test]
fn duplicate_final_payload_digest_is_rejected_not_silently_normalized() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let mut request = planning_request(1);
    let payload = digest("duplicate-payload");
    request.candidates[0].final_payload_digests = vec![payload, payload];
    assert!(matches!(
        prepare_plan(&snapshot, request),
        Err(PlannerError::DuplicatePayloadDigest(_))
    ));
}
''',
)

# Keep frame sequence checking overflow-safe under strict Clippy.
replace_once(
    "codex-rs/hepta-control-plane/src/planner_store.rs",
    '''        let expected_sequence = records
            .last()
            .map_or(sequence, |record: &PlannerStoreRecordV1| record.sequence + 1);
        if sequence == 0 || sequence != expected_sequence {
''',
    '''        let expected_sequence = records.last().map_or(Ok(sequence), |record: &PlannerStoreRecordV1| {
            record
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::LengthOverflow)
        })?;
        if sequence == 0 || sequence != expected_sequence {
''',
)

print("control.runtime static fixups applied")
