//! Canonical data-codec checks against real files. No transport reply, Root
//! capability or independent retention is supplied by these component fixtures.

use super::*;
use crate::decode_readonly_ledger_data_v1;
use crate::encode_readonly_ledger_data_v1;

#[test]
fn ledger_read_data_roundtrip_is_identical_to_the_actual_writer_image() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let view = fixture.observe()?;
    let observed = view.observe()?;
    let bytes = encode_readonly_ledger_data_v1(fixture.binding, snapshot.records())?;
    assert_eq!(bytes, fixture.bytes("ledger")?);
    assert_eq!(
        decode_readonly_ledger_data_v1(&bytes, observed.cut, LIMIT)?,
        snapshot
    );
    assert_eq!(view.observe()?, observed);
    Ok(())
}

#[test]
fn ledger_read_data_rejects_even_rehashed_partial_or_unwitnessed_suffixes() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let observed = fixture.observe()?.observe()?;
    let mut partial = fixture.bytes("ledger")?;
    partial.extend_from_slice(&[0; 4]);
    let mut cut = observed.cut;
    cut.ledger_length = partial.len() as u64;
    cut.ledger_digest = Digest32::of_bytes(&partial);
    assert!(matches!(
        decode_readonly_ledger_data_v1(&partial, cut, LIMIT),
        Err(DurableLedgerError::IncompleteTail)
    ));
    let mut core = LearningLedger::from_snapshot(snapshot)?;
    core.append(LedgerEvent::Revocation(crate::Revocation {
        record_id: StableId::new("codec-revocation")?,
        target_record_id: StableId::new("observation")?,
        authority_id: StableId::new("untrusted-codec-metadata")?,
        reason_digest: Digest32::of_bytes(b"codec-reason"),
    }))?;
    let trailing = encode_readonly_ledger_data_v1(fixture.binding, core.records())?;
    cut.ledger_length = trailing.len() as u64;
    cut.ledger_digest = Digest32::of_bytes(&trailing);
    assert!(matches!(
        decode_readonly_ledger_data_v1(&trailing, cut, LIMIT),
        Err(DurableLedgerError::UnwitnessedTail)
    ));
    Ok(())
}

#[test]
fn ledger_read_data_rejects_forged_records_bad_binding_and_changed_frames() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let mut records = snapshot.records().to_vec();
    records[0].event_digest = Digest32::of_bytes(b"forged");
    assert!(encode_readonly_ledger_data_v1(fixture.binding, &records).is_err());
    let observed = fixture.observe()?.observe()?;
    let mut bytes = fixture.bytes("ledger")?;
    let mut cut = observed.cut;
    cut.binding = Digest32::of_bytes(b"another-binding");
    assert!(decode_readonly_ledger_data_v1(&bytes, cut, LIMIT).is_err());
    bytes[72] ^= 1;
    cut = observed.cut;
    cut.ledger_digest = Digest32::of_bytes(&bytes);
    assert!(decode_readonly_ledger_data_v1(&bytes, cut, LIMIT).is_err());
    cut = observed.cut;
    cut.frontier.sealed = true;
    assert!(decode_readonly_ledger_data_v1(&fixture.bytes("ledger")?, cut, LIMIT).is_err());
    Ok(())
}
