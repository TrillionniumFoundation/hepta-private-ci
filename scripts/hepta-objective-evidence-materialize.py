#!/usr/bin/env python3
"""One-shot objective.compiler golden-vector and backpressure test materializer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def append_once(path: str, marker: str, text: str) -> None:
    target = ROOT / path
    value = target.read_text(encoding="utf-8")
    if marker in value:
        raise SystemExit(f"{path}: marker already exists: {marker}")
    target.write_text(value.rstrip() + "\n\n" + text.strip() + "\n", encoding="utf-8")


append_once(
    "codex-rs/hepta-learning-ledger/src/run_start_tests.rs",
    "capacity_backpressure_does_not_mutate_the_journal",
    r'''
#[test]
fn capacity_backpressure_does_not_mutate_the_journal() {
    let fixture = Fixture::new();
    let mut journal = must(DurableRunStartJournal::create(fixture.file(), binding(), 1));
    let first = must(journal.append(Digest32::ZERO, record("run-capacity-1", b"one")));
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        journal.append(
            first.chain_digest,
            record("run-capacity-2", b"two"),
        ),
        Err(RunStartStoreError::Capacity)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
    assert_eq!(must(journal.records()).len(), 1);
}
''',
)

append_once(
    "codex-rs/hepta-intelligence/src/objective_run_tests.rs",
    "publication_capacity_is_fail_closed",
    r'''
#[test]
fn publication_capacity_is_fail_closed() {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(
        fixture.file(),
        digest("principal-run-start-scope"),
        1,
    )
    .expect("journal");
    let profile = profile();
    let envelope = envelope();
    let admission_context = context(&profile, &envelope);
    let first = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &admission_context,
        bindings("run-capacity-1", Digest32::ZERO),
        &mut journal,
    )
    .expect("first publication");
    let second = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &admission_context,
        bindings("run-capacity-2", first.publication.chain_digest),
        &mut journal,
    );
    assert!(matches!(
        second,
        Err(ObjectiveRunError::RunStart(
            codex_hepta_learning_ledger::RunStartStoreError::Capacity
        ))
    ));
    assert_eq!(journal.records().expect("records").len(), 1);
}

fn objective_end_to_end_golden_line_v1() -> String {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(
        fixture.file(),
        digest("principal-run-start-scope"),
        16,
    )
    .expect("journal");
    let profile = profile();
    let envelope = envelope();
    let admission_context = context(&profile, &envelope);
    let receipt = compile_and_publish_objective_run_v1(
        &envelope,
        &profile,
        &admission_context,
        bindings("run-golden-v1", Digest32::ZERO),
        &mut journal,
    )
    .expect("golden publication");
    format!(
        concat!(
            "schema=hepta.objective-e2e-golden.v1\n",
            "sourceProvenanceDigest={}\n",
            "intentDigest={}\n",
            "profileDigest={}\n",
            "admissionProofDigest={}\n",
            "admittedSourceDigest={}\n",
            "objectiveSemanticDigest={}\n",
            "objectiveProtocolDigest={}\n",
            "runStartRecordDigest={}\n",
            "journalChainDigest={}\n"
        ),
        envelope.structured_intent.provenance.source_digest,
        envelope.intent_digest,
        profile.digest().expect("profile digest"),
        receipt.objective_admission_proof_digest,
        receipt.admission.admitted_source_digest,
        receipt.run_start.objective_digest,
        receipt.objective_function_v1_digest,
        receipt.publication.record_digest,
        receipt.publication.chain_digest,
    )
}

#[test]
fn objective_end_to_end_golden_vector_v1_is_stable() {
    assert_eq!(
        include_str!("../tests/fixtures/objective_end_to_end_v1.txt"),
        objective_end_to_end_golden_line_v1()
    );
}

#[test]
#[ignore = "one-shot golden vector recorder"]
fn update_objective_end_to_end_golden_vector_v1() {
    let output = std::env::var("HEPTA_OBJECTIVE_GOLDEN_OUTPUT")
        .expect("HEPTA_OBJECTIVE_GOLDEN_OUTPUT");
    std::fs::write(output, objective_end_to_end_golden_line_v1())
        .expect("write golden vector");
}
''',
)

fixture = ROOT / "codex-rs/hepta-intelligence/tests/fixtures/objective_end_to_end_v1.txt"
fixture.parent.mkdir(parents=True, exist_ok=True)
if fixture.exists():
    raise SystemExit(f"{fixture.relative_to(ROOT)} already exists")
fixture.write_text("", encoding="utf-8")
print("objective compiler evidence materialization applied")
