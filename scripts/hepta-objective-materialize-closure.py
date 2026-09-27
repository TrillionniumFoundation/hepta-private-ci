#!/usr/bin/env python3
"""One-shot source migration for objective compiler durable proof closure."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, observed {count}: {old!r}")
    write(path, text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} replacements, observed {count}: {old!r}"
        )
    write(path, text.replace(old, new))


def insert_fixture_proof(path: str, expression: str, minimum: int = 1) -> None:
    text = read(path)
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    inserted = 0
    for index, line in enumerate(lines):
        output.append(line)
        if "admitted_source_digest:" not in line:
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if "objective_admission_proof_digest:" in next_line:
            continue
        indent = line[: len(line) - len(line.lstrip())]
        output.append(f"{indent}objective_admission_proof_digest: {expression},\n")
        inserted += 1
    if inserted < minimum:
        raise SystemExit(f"{path}: inserted only {inserted} admission proof fields")
    write(path, "".join(output))


replace_once(
    ".github/workflows/hepta-objective-admission.yml",
    "          python3 scripts/hepta-implementation-maps.py verify\n",
    "          python3 scripts/hepta-implementation-maps.py verify --module objective.compiler\n"
    "          python3 scripts/hepta-objective-current-state.py verify\n",
)
replace_once(
    ".github/workflows/hepta-objective-admission.yml",
    "      - scripts/hepta-implementation-maps.py\n",
    "      - scripts/hepta-implementation-maps.py\n"
    "      - scripts/hepta-objective-current-state.py\n",
)
replace_once(
    ".github/workflows/hepta-objective-product-composition.yml",
    "      - \"scripts/hepta-objective-target-measure.py\"\n",
    "      - \"scripts/hepta-objective-target-measure.py\"\n"
    "      - \"scripts/hepta-objective-current-state.py\"\n"
    "      - \"docs/modules/objective.compiler/CURRENT_STATE.json\"\n",
)
replace_once(
    ".github/workflows/hepta-objective-product-composition.yml",
    "      - name: Contract authority drift guard\n"
    "        if: steps.execution.outputs.run_native == 'true'\n"
    "        run: python3 -m unittest -v scripts.test_hepta_objective_contracts scripts.test_hepta_objective_target_measure\n",
    "      - name: Contract authority drift guard\n"
    "        if: steps.execution.outputs.run_native == 'true'\n"
    "        run: |\n"
    "          python3 scripts/hepta-implementation-maps.py verify --module objective.compiler\n"
    "          python3 scripts/hepta-objective-current-state.py verify\n"
    "          python3 -m unittest -v scripts.test_hepta_objective_contracts scripts.test_hepta_objective_target_measure\n",
)
replace_once(
    ".github/workflows/hepta-objective-product-composition.yml",
    "        run: cargo clippy --locked -p codex-hepta-objective -p codex-hepta-learning-ledger -p codex-hepta-intelligence -p codex-hepta-agentd --all-targets -- -D warnings\n",
    "        run: cargo clippy --locked -p codex-hepta-objective -p codex-hepta-learning-ledger -p codex-hepta-intelligence -p codex-hepta-agentd --all-targets --no-deps -- -D warnings\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "use codex_hepta_objective::admit_and_compile_objective_v1;\n",
    "use codex_hepta_objective::preflight_validate_objective_v1;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        let outcome = admit_and_compile_objective_v1(&envelope, &profile, &context)\n"
    "            .map_err(|_| Self::reject(input.stage, \"objective admission\"))?;\n",
    "        let (outcome, _admission_proof) =\n"
    "            preflight_validate_objective_v1(&envelope, &profile, &context)\n"
    "                .map_err(|_| Self::reject(input.stage, \"objective preflight\"))?\n"
    "                .into_parts();\n",
)

run_start = "codex-rs/hepta-learning-ledger/src/run_start.rs"
replace_once(
    run_start,
    'const RECORD_DOMAIN_V1: &[u8] = b"hepta.run-start-record.v1";\n'
    'const RECORD_DOMAIN: &[u8] = b"hepta.run-start-record.v2";\n'
    'const CONFLICT_RECORD_DOMAIN: &[u8] = b"hepta.run-start-conflict.v1";\n',
    'const RECORD_DOMAIN_V1: &[u8] = b"hepta.run-start-record.v1";\n'
    'const RECORD_DOMAIN_V2: &[u8] = b"hepta.run-start-record.v2";\n'
    'const RECORD_DOMAIN: &[u8] = b"hepta.run-start-record.v3";\n'
    'const CONFLICT_RECORD_DOMAIN_V1: &[u8] = b"hepta.run-start-conflict.v1";\n'
    'const CONFLICT_RECORD_DOMAIN: &[u8] = b"hepta.run-start-conflict.v2";\n',
)
replace_once(
    run_start,
    "    pub admitted_source_digest: Digest32,\n"
    "    pub observed_at_unix_micros: u64,\n",
    "    pub admitted_source_digest: Digest32,\n"
    "    /// Opaque proof that binds source bytes, frozen profile, authenticated\n"
    "    /// admission context, compiler contract and admitted native source.\n"
    "    pub objective_admission_proof_digest: Digest32,\n"
    "    pub observed_at_unix_micros: u64,\n",
)
replace_once(
    run_start,
    "fn validate_record(record: &RunStartRecordV1) -> Result<(), RunStartStoreError> {\n"
    "    validate_record_compat(record, true)\n"
    "}\n\n"
    "fn validate_record_compat(\n"
    "    record: &RunStartRecordV1,\n"
    "    require_protocol: bool,\n"
    ") -> Result<(), RunStartStoreError> {\n",
    "fn validate_record(record: &RunStartRecordV1) -> Result<(), RunStartStoreError> {\n"
    "    validate_record_compat(record, true, true)\n"
    "}\n\n"
    "fn validate_record_compat(\n"
    "    record: &RunStartRecordV1,\n"
    "    require_protocol: bool,\n"
    "    require_admission_proof: bool,\n"
    ") -> Result<(), RunStartStoreError> {\n",
)
replace_once(
    run_start,
    "    if record.admission.profile_revision == 0\n"
    "        || record.admission.observed_at_unix_micros == 0\n"
    "        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros\n"
    "        || record.admission.authority.grants_any()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\"admission\"));\n"
    "    }\n"
    "    let snapshot = &record.snapshot;\n",
    "    if record.admission.profile_revision == 0\n"
    "        || record.admission.observed_at_unix_micros == 0\n"
    "        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros\n"
    "        || record.admission.authority.grants_any()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\"admission\"));\n"
    "    }\n"
    "    if require_admission_proof\n"
    "        && record.admission.objective_admission_proof_digest.is_zero()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\n"
    "            \"objectiveAdmissionProofDigest\",\n"
    "        ));\n"
    "    }\n"
    "    if !require_admission_proof\n"
    "        && !record.admission.objective_admission_proof_digest.is_zero()\n"
    "    {\n"
    "        return Err(RunStartStoreError::Corrupt);\n"
    "    }\n"
    "    let snapshot = &record.snapshot;\n",
)
replace_once(
    run_start,
    "fn validate_conflict_record(record: &RunStartConflictRecordV1) -> Result<(), RunStartStoreError> {\n"
    "    if record.authentication.key_epoch == 0\n",
    "fn validate_conflict_record(record: &RunStartConflictRecordV1) -> Result<(), RunStartStoreError> {\n"
    "    validate_conflict_record_compat(record, true)\n"
    "}\n\n"
    "fn validate_conflict_record_compat(\n"
    "    record: &RunStartConflictRecordV1,\n"
    "    require_admission_proof: bool,\n"
    ") -> Result<(), RunStartStoreError> {\n"
    "    if record.authentication.key_epoch == 0\n",
)
text = read(run_start)
needle = (
    "    if record.admission.profile_revision == 0\n"
    "        || record.admission.observed_at_unix_micros == 0\n"
    "        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros\n"
    "        || record.admission.authority.grants_any()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\"admission\"));\n"
    "    }\n"
    "    for (name, digest) in [\n"
)
replacement = (
    "    if record.admission.profile_revision == 0\n"
    "        || record.admission.observed_at_unix_micros == 0\n"
    "        || record.admission.deadline_unix_micros <= record.admission.observed_at_unix_micros\n"
    "        || record.admission.authority.grants_any()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\"admission\"));\n"
    "    }\n"
    "    if require_admission_proof\n"
    "        && record.admission.objective_admission_proof_digest.is_zero()\n"
    "    {\n"
    "        return Err(RunStartStoreError::InvalidSnapshot(\n"
    "            \"objectiveAdmissionProofDigest\",\n"
    "        ));\n"
    "    }\n"
    "    if !require_admission_proof\n"
    "        && !record.admission.objective_admission_proof_digest.is_zero()\n"
    "    {\n"
    "        return Err(RunStartStoreError::Corrupt);\n"
    "    }\n"
    "    for (name, digest) in [\n"
)
if text.count(needle) != 1:
    raise SystemExit(
        f"{run_start}: expected one conflict admission validation block, observed {text.count(needle)}"
    )
write(run_start, text.replace(needle, replacement, 1))
replace_count(
    run_start,
    "    push_digest(&mut bytes, record.admission.admitted_source_digest);\n"
    "    push_u64(&mut bytes, record.admission.observed_at_unix_micros);\n",
    "    push_digest(&mut bytes, record.admission.admitted_source_digest);\n"
    "    push_digest(\n"
    "        &mut bytes,\n"
    "        record.admission.objective_admission_proof_digest,\n"
    "    );\n"
    "    push_u64(&mut bytes, record.admission.observed_at_unix_micros);\n",
    2,
)
replace_once(
    run_start,
    "fn decode_record(input: &[u8]) -> Result<RunStartRecordV1, RunStartStoreError> {\n"
    "    let (input, require_protocol) = if let Some(value) = input.strip_prefix(RECORD_DOMAIN) {\n"
    "        (value, true)\n"
    "    } else if let Some(value) = input.strip_prefix(RECORD_DOMAIN_V1) {\n"
    "        (value, false)\n"
    "    } else {\n"
    "        return Err(RunStartStoreError::Corrupt);\n"
    "    };\n",
    "fn decode_record(input: &[u8]) -> Result<RunStartRecordV1, RunStartStoreError> {\n"
    "    let (input, require_protocol, require_admission_proof) =\n"
    "        if let Some(value) = input.strip_prefix(RECORD_DOMAIN) {\n"
    "            (value, true, true)\n"
    "        } else if let Some(value) = input.strip_prefix(RECORD_DOMAIN_V2) {\n"
    "            (value, true, false)\n"
    "        } else if let Some(value) = input.strip_prefix(RECORD_DOMAIN_V1) {\n"
    "            (value, false, false)\n"
    "        } else {\n"
    "            return Err(RunStartStoreError::Corrupt);\n"
    "        };\n",
)
replace_once(
    run_start,
    "fn decode_conflict_record(input: &[u8]) -> Result<RunStartConflictRecordV1, RunStartStoreError> {\n"
    "    let input = input\n"
    "        .strip_prefix(CONFLICT_RECORD_DOMAIN)\n"
    "        .ok_or(RunStartStoreError::Corrupt)?;\n",
    "fn decode_conflict_record(input: &[u8]) -> Result<RunStartConflictRecordV1, RunStartStoreError> {\n"
    "    let (input, require_admission_proof) =\n"
    "        if let Some(value) = input.strip_prefix(CONFLICT_RECORD_DOMAIN) {\n"
    "            (value, true)\n"
    "        } else if let Some(value) = input.strip_prefix(CONFLICT_RECORD_DOMAIN_V1) {\n"
    "            (value, false)\n"
    "        } else {\n"
    "            return Err(RunStartStoreError::Corrupt);\n"
    "        };\n",
)
replace_count(
    run_start,
    "        admitted_source_digest: reader.digest()?,\n"
    "        observed_at_unix_micros: reader.u64()?,\n",
    "        admitted_source_digest: reader.digest()?,\n"
    "        objective_admission_proof_digest: if require_admission_proof {\n"
    "            reader.digest()?\n"
    "        } else {\n"
    "            Digest32::ZERO\n"
    "        },\n"
    "        observed_at_unix_micros: reader.u64()?,\n",
    2,
)
replace_once(
    run_start,
    "    if !reader.0.is_empty() || validate_record_compat(&record, require_protocol).is_err() {\n",
    "    if !reader.0.is_empty()\n"
    "        || validate_record_compat(&record, require_protocol, require_admission_proof).is_err()\n"
    "    {\n",
)
replace_once(
    run_start,
    "    if !reader.0.is_empty() || validate_conflict_record(&record).is_err() {\n",
    "    if !reader.0.is_empty()\n"
    "        || validate_conflict_record_compat(&record, require_admission_proof).is_err()\n"
    "    {\n",
)
replace_once(
    run_start,
    "    if input.starts_with(RECORD_DOMAIN) || input.starts_with(RECORD_DOMAIN_V1) {\n",
    "    if input.starts_with(RECORD_DOMAIN)\n"
    "        || input.starts_with(RECORD_DOMAIN_V2)\n"
    "        || input.starts_with(RECORD_DOMAIN_V1)\n"
    "    {\n",
)
replace_once(
    run_start,
    "    if input.starts_with(CONFLICT_RECORD_DOMAIN) {\n",
    "    if input.starts_with(CONFLICT_RECORD_DOMAIN)\n"
    "        || input.starts_with(CONFLICT_RECORD_DOMAIN_V1)\n"
    "    {\n",
)
replace_once(
    "codex-rs/hepta-intelligence/src/objective_run.rs",
    "        admitted_source_digest: receipt.admitted_source_digest,\n"
    "        observed_at_unix_micros: receipt.observed_at_unix_micros,\n",
    "        admitted_source_digest: receipt.admitted_source_digest,\n"
    "        objective_admission_proof_digest: admission_proof.proof_digest(),\n"
    "        observed_at_unix_micros: receipt.observed_at_unix_micros,\n",
)
insert_fixture_proof(
    "codex-rs/hepta-learning-ledger/src/run_start_tests.rs",
    'digest("objective-admission-proof")',
    minimum=2,
)
insert_fixture_proof(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    'd("objective-admission-proof")',
)
insert_fixture_proof(
    "codex-rs/hepta-agentd/src/objective_runtime_tests.rs",
    'digest("objective-admission-proof")',
)
insert_fixture_proof(
    "codex-rs/hepta-agentd/src/state_isolation_tests.rs",
    'Digest32::of_bytes(b"objective-admission-proof")',
)
replace_once(
    "codex-rs/hepta-intelligence/src/objective_run_tests.rs",
    "    assert_eq!(\n"
    "        durable.admission.admitted_source_digest,\n"
    "        receipt.admission.admitted_source_digest\n"
    "    );\n",
    "    assert_eq!(\n"
    "        durable.admission.admitted_source_digest,\n"
    "        receipt.admission.admitted_source_digest\n"
    "    );\n"
    "    assert_eq!(\n"
    "        durable.admission.objective_admission_proof_digest,\n"
    "        receipt.objective_admission_proof_digest,\n"
    "        \"authoritative admission proof must be durable before return\"\n"
    "    );\n",
)
tests = read("codex-rs/hepta-learning-ledger/src/run_start_tests.rs")
marker = "\n#[test]\nfn objective_payload_digest_mismatch_rejects_before_io()"
addition = r'''
#[test]
fn admission_proof_digest_is_durable_and_idempotency_bound() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = record("run-proof", b"objective-semantic-proof");
    let expected_proof = first.admission.objective_admission_proof_digest;
    let receipt = must(journal.append(Digest32::ZERO, first.clone()));
    let anchor = RunStartAnchor {
        sequence: receipt.sequence,
        chain_digest: receipt.chain_digest,
    };
    drop(journal);

    let mut reopened = must(fixture.recover(RunStartRecovery::Acknowledged(anchor)));
    let durable = must(reopened.get(&id("run-proof"))).expect("durable record");
    assert_eq!(
        durable.admission.objective_admission_proof_digest,
        expected_proof
    );

    let mut forged = first;
    forged.admission.objective_admission_proof_digest = digest("different-proof");
    assert_eq!(
        reopened.append(receipt.chain_digest, forged),
        Err(RunStartStoreError::Conflict)
    );
}

#[test]
fn zero_admission_proof_is_rejected_before_io() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let mut invalid = record("run-zero-proof", b"objective-semantic-proof");
    invalid.admission.objective_admission_proof_digest = Digest32::ZERO;
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        journal.append(Digest32::ZERO, invalid),
        Err(RunStartStoreError::InvalidSnapshot(
            "objectiveAdmissionProofDigest"
        ))
    );
    assert_eq!(must(fs::read(fixture.path())), before);
}
'''
if tests.count(marker) != 1:
    raise SystemExit("run_start_tests.rs: insertion marker drift")
write(
    "codex-rs/hepta-learning-ledger/src/run_start_tests.rs",
    tests.replace(marker, "\n" + addition.strip() + marker, 1),
)
replace_once(
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
    "      - scripts/hepta-implementation-maps.py\n",
    "      - scripts/hepta-implementation-maps.py\n"
    "      - scripts/hepta-objective-current-state.py\n"
    "      - docs/modules/objective.compiler/CURRENT_STATE.json\n",
)
replace_once(
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
    "          python3 scripts/hepta-implementation-maps.py verify\n",
    "          python3 scripts/hepta-implementation-maps.py verify \\\n"
    "            --module objective.compiler \\\n"
    "            --module utility.ndu \\\n"
    "            --module control.runtime\n"
    "          python3 scripts/hepta-objective-current-state.py verify\n",
)
replace_once(
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
    "            --all-targets -- -D warnings\n",
    "            --all-targets --no-deps -- -D warnings\n",
)
print("objective compiler durable proof materialization applied")
