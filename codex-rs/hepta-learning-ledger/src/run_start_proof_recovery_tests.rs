//! Proof lifecycle on the existing owner journal, including frozen legacy bytes.
use super::*;

fn stored(record: RunStartRecordV1, sequence: u64, predecessor: Digest32) -> StoredRunStart {
    let record_digest = Digest32::of_bytes(&encode_record(&record));
    StoredRunStart {
        sequence,
        predecessor_chain_digest: predecessor,
        record_digest,
        chain_digest: digest_chain(predecessor, sequence, record_digest),
        record: StoredRunStartRecord::Run(Box::new(record)),
    }
}

#[test]
fn mixed_versions_recover_without_synthesizing_proof_or_rewriting_identity() {
    let fixture = Fixture::new();
    drop(fixture.create());
    let mut predecessor = Digest32::ZERO;
    let mut originals = Vec::new();
    for version in 1..=3 {
        let mut value = record(&format!("run.version.{version}"), b"frozen semantic bytes");
        if version < 3 {
            value.admission.objective_admission_proof = None;
        }
        if version == 1 {
            value.objective_function_v1_digest = Digest32::ZERO;
            value.objective_function_v1_bytes.clear();
        }
        let encoded = encode_record(&value);
        assert!(encoded.starts_with(match version {
            1 => RECORD_DOMAIN_V1,
            2 => RECORD_DOMAIN_V2,
            _ => RECORD_DOMAIN,
        }));
        assert_eq!(encode_record(&must(decode_record(&encoded))), encoded);
        let frame = stored(value.clone(), version, predecessor);
        predecessor = frame.chain_digest;
        let mut file = fixture.file();
        must(file.seek(SeekFrom::End(0)));
        must(file.write_all(&must(encode_frame(&frame))));
        must(file.sync_all());
        originals.push(value);
    }
    let before = must(fs::read(fixture.path()));
    let mut reopened = must(
        fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: 3,
            chain_digest: predecessor,
        })),
    );
    assert_eq!(
        must(reopened.records()),
        originals.iter().collect::<Vec<_>>()
    );
    assert_eq!(must(fs::read(fixture.path())), before);
    for legacy in &originals[..2] {
        assert!(reopened.append(predecessor, legacy.clone()).is_err());
    }
    assert_eq!(must(fs::read(fixture.path())), before);
    let replay = must(reopened.append(predecessor, originals[2].clone()));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
}

#[test]
fn missing_and_cross_bound_proof_are_rejected_before_any_write() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let before = must(fs::read(fixture.path()));
    let valid = record("run.proof", b"semantic");
    let mut missing = valid.clone();
    missing.admission.objective_admission_proof = None;
    let mut profile_drift = valid.clone();
    profile_drift.admission.profile_digest = digest("another-profile");
    let mut source_drift = valid;
    source_drift.admission.admitted_source_digest = digest("another-source");
    for value in [missing, profile_drift, source_drift] {
        assert!(journal.append(Digest32::ZERO, value).is_err());
        assert_eq!(must(fs::read(fixture.path())), before);
    }
    let mut conflict = conflict_record("run.conflict", b"conflict");
    conflict.admission.objective_admission_proof = None;
    let legacy = encode_conflict_record(&conflict);
    assert!(legacy.starts_with(CONFLICT_RECORD_DOMAIN_V1));
    assert_eq!(
        encode_conflict_record(&must(decode_conflict_record(&legacy))),
        legacy
    );
    assert!(journal.append_conflict(Digest32::ZERO, conflict).is_err());
    assert_eq!(must(fs::read(fixture.path())), before);
}

#[test]
fn admission_context_proof_drift_conflicts_after_acknowledged_restart() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("run.proof-drift", b"semantic");
    let receipt = must(journal.append(Digest32::ZERO, original.clone()));
    drop(journal);
    let mut reopened = must(
        fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: receipt.sequence,
            chain_digest: receipt.chain_digest,
        })),
    );
    let mut changed = original;
    let proof = changed
        .admission
        .objective_admission_proof
        .as_ref()
        .unwrap_or_else(|| panic!("fixture proof"));
    let mut bytes = proof.canonical_bytes().to_vec();
    // Keep profile and admitted source unchanged; only the historical context differs.
    let context_start = b"hepta.objective.admission-proof.v1".len() + 64;
    bytes[context_start] ^= 1;
    changed.admission.objective_admission_proof = Some(must(
        RunStartAdmissionProofV1::from_canonical_bytes(&bytes, Digest32::of_bytes(&bytes)),
    ));
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        reopened.append(receipt.chain_digest, changed),
        Err(RunStartStoreError::Conflict)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
}

#[test]
fn rewritten_proof_and_recomputed_chain_cannot_replace_acknowledged_history() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("run.rewritten-proof", b"semantic");
    let receipt = must(journal.append(Digest32::ZERO, original.clone()));
    drop(journal);
    let full = must(fs::read(fixture.path()));
    let mut changed = original;
    let proof = changed
        .admission
        .objective_admission_proof
        .as_ref()
        .unwrap_or_else(|| panic!("fixture proof"));
    let mut bytes = proof.canonical_bytes().to_vec();
    bytes[b"hepta.objective.admission-proof.v1".len()] ^= 1;
    changed.admission.objective_admission_proof = Some(must(
        RunStartAdmissionProofV1::from_canonical_bytes(&bytes, Digest32::of_bytes(&bytes)),
    ));
    let mut forged = full[..HEADER_V2].to_vec();
    forged.extend_from_slice(&must(encode_frame(&stored(changed, 1, Digest32::ZERO))));
    must(fs::write(fixture.path(), &forged));
    assert!(
        fixture
            .recover(RunStartRecovery::Acknowledged(RunStartAnchor {
                sequence: receipt.sequence,
                chain_digest: receipt.chain_digest,
            }))
            .is_err()
    );
    assert_eq!(must(fs::read(fixture.path())), forged);
}
