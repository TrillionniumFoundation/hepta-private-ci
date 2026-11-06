//! OwnerDrained is a distinct signed retirement of an actual drained task.
//! It does not rewrite a non-STOP observation or qualify terminal evaluation.

use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::RECORDS;
use super::config;
use super::cost;
use super::request;
use super::super::types::CurrentHead;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::NeuronGenerationUpdateReadbackV1;

#[path = "neuron_generation_drained_test_support.rs"]
mod support;

use support::Case;
use support::append_advanced;
use support::deliver;

#[test]
fn retirement_requires_both_settled_request_and_actual_output_ack() -> anyhow::Result<()> {
    let fixture = Fixture::new(config()?)?;
    let selected = fixture.selection()?;
    let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
    let mut old = fixture.old_journal()?;
    let request = request(&old, &fixture.old_config, "pending-retirement")?;
    old.admit(request, /*now_micros*/ 10)?;
    old.drain()?;
    assert!(!old.is_drained()?);
    assert!(old.pending_request()?.is_some());
    let before = fixture.bytes("current.json")?;
    assert!(fixture.current.prepare_drained_retirement(
        &old, "premature-retirement".into(), binding.clone(), &selected,
    ).is_err());
    assert_eq!(fixture.bytes("current.json")?, before);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    drop(old);
    let old = fixture.old_journal()?;
    assert!(old.pending_request()?.is_some());
    assert!(!old.is_drained()?);
    assert!(fixture.current.prepare_drained_retirement(
        &old, "cold-pending-retirement".into(), binding, &selected,
    ).is_err());
    drop(old);

    let fixture = Fixture::new(config()?)?;
    let selected = fixture.selection()?;
    let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
    let mut old = fixture.old_journal()?;
    append_advanced(&fixture, &mut old)?;
    old.drain()?;
    let chunk = old.pending_output()?.cloned();
    assert!(chunk.is_some());
    assert!(!old.snapshot()?.stopped);
    assert!(!old.is_drained()?);
    let before = fixture.bytes("current.json")?;
    assert!(fixture.current.prepare_drained_retirement(
        &old, "unacknowledged-retirement".into(), binding.clone(), &selected,
    ).is_err());
    assert_eq!(old.pending_output()?.cloned(), chunk);
    assert_eq!(fixture.bytes("current.json")?, before);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    deliver(&fixture, &mut old)?;
    assert!(old.is_drained()?);
    assert!(!old.observe_generation()?.is_terminal());
    assert!(!old.snapshot()?.stopped);
    assert!(fixture.current.prepare(
        &old, "strict-still-requires-stop".into(), binding.clone(), &selected,
    ).is_err());
    let snapshot = old.snapshot()?.clone();
    let costs = old.task_cost()?.clone();
    let bytes = (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?);
    let prepared = fixture.current.prepare_drained_retirement(
        &old, "acknowledged-retirement".into(), binding, &selected,
    )?;
    assert_eq!(prepared.completion(), NeuronGenerationPredecessorCompletionV1::OwnerDrained);
    assert_eq!(old.snapshot()?, &snapshot);
    assert_eq!(old.task_cost()?, &costs);
    assert_eq!((fixture.bytes("old-journal")?, fixture.bytes("old-witness")?), bytes);
    Ok(())
}

#[test]
fn strict_legacy_bytes_and_retirement_signatures_cannot_be_substituted() -> anyhow::Result<()> {
    let mut strict = Case::new(true, NeuronGenerationPredecessorCompletionV1::ModelStopped)?;
    let mut retired = Case::new(true, NeuronGenerationPredecessorCompletionV1::OwnerDrained)?;
    let strict_bytes = strict.fixture.bytes("current.json")?;
    let legacy: serde_json::Value = serde_json::from_slice(&strict_bytes)?;
    assert!(legacy["prepared"].get("completion").is_none());
    assert!(legacy.get("initial").is_none());
    let parsed: CurrentHead = serde_json::from_slice(&strict_bytes)?;
    assert_eq!(serde_json::to_vec(&parsed)?, strict_bytes);
    let recovered = strict.fixture.reopen_current()?.recover_operation(
        "replace-completion", strict.prepared.intent_digest(),
    )?;
    assert_eq!(recovered.completion(), NeuronGenerationPredecessorCompletionV1::ModelStopped);
    assert_eq!(recovered.final_use_binding(), strict.prepared.final_use_binding());
    assert_eq!(strict.prepared.final_use_binding().destination_id, "agentd.cell-generation.replace");
    assert_eq!(retired.prepared.final_use_binding().destination_id, "agentd.cell-generation.replace-drained");
    assert_ne!(strict.prepared.intent_digest(), retired.prepared.intent_digest());
    let retired_bytes = retired.fixture.bytes("current.json")?;
    std::mem::swap(&mut strict.signed, &mut retired.signed);
    assert!(strict.publish().is_err());
    assert!(retired.publish().is_err());
    assert_eq!(strict.fixture.authority.capacity()?.used_nonces, 0);
    assert_eq!(retired.fixture.authority.capacity()?.used_nonces, 0);
    assert_eq!(strict.fixture.bytes("current.json")?, strict_bytes);
    assert_eq!(retired.fixture.bytes("current.json")?, retired_bytes);
    Ok(())
}

#[test]
fn resumed_or_changed_drained_cut_rejects_the_original_retirement_signature() -> anyhow::Result<()> {
    for change in ["resume", "cost"] {
        let mut case = Case::new(false, NeuronGenerationPredecessorCompletionV1::OwnerDrained)?;
        let before = case.fixture.bytes("current.json")?;
        let target = case.fixture.bytes("target-journal")?;
        if change == "resume" {
            case.old.resume()?;
            assert!(!case.old.is_drained()?);
            assert!(case.publish().is_err());
            case.old.drain()?;
        } else {
            let measurement = cost(&case.fixture.old_config, "later-host-work", CellCostStageV2::Queue)?;
            case.old.record_cost(measurement.entries()[0].clone())?;
        }
        assert!(case.old.is_drained()?);
        assert!(!case.old.snapshot()?.stopped);
        assert!(case.publish().is_err(), "{change} changed the frozen observed cut");
        assert_eq!(case.fixture.bytes("current.json")?, before);
        assert_eq!(case.fixture.bytes("target-journal")?, target);
        assert_eq!(case.fixture.authority.capacity()?.used_nonces, 0);
    }
    Ok(())
}

#[test]
fn forward_retirement_preserves_mode_and_fences_the_unchanged_non_stop_predecessor()
-> anyhow::Result<()> {
    let mut case = Case::new(false, NeuronGenerationPredecessorCompletionV1::OwnerDrained)?;
    let old_snapshot = case.old.snapshot()?.clone();
    let old_cost = case.old.task_cost()?.clone();
    let old_bytes = (case.fixture.bytes("old-journal")?, case.fixture.bytes("old-witness")?);
    assert!(!old_snapshot.stopped);
    assert!(!case.old.observe_generation()?.is_terminal());
    case.fixture.reject_publication_write();
    assert!(case.publish().is_err());
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 1);
    let current = case.fixture.reopen_current()?;
    let original = current.recover_operation("replace-completion", case.prepared.intent_digest())?;
    assert_eq!(current.read_operation(&original)?, NeuronGenerationUpdateReadbackV1::Prepared);
    let forward = current.prepare_forward_recovery(
        &original, &case.old, &case.new, "retirement-forward".into(),
    )?;
    assert_eq!(forward.completion(), NeuronGenerationPredecessorCompletionV1::OwnerDrained);
    assert_eq!(forward.final_use_binding().destination_id, "agentd.cell-generation.replace-drained");
    let retained = current.recover_operation("retirement-forward", forward.intent_digest())?;
    assert_eq!(retained.completion(), forward.completion());
    assert_eq!(retained.final_use_binding(), forward.final_use_binding());
    case.prepared = forward;
    assert!(case.publish().is_err());
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 1);
    case.signed = case.fixture.sign(case.prepared.final_use_binding())?;
    let actual = case.publish()?;
    assert_eq!(actual.completion(), NeuronGenerationPredecessorCompletionV1::OwnerDrained);
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 2);
    assert_eq!(case.old.resume(), Err(CellGenerationErrorV2::InvalidBinding));
    assert_eq!(case.new.snapshot()?, &case.fixture.target_config.initial);
    assert!(!old_snapshot.stopped);
    assert!(!old_cost.entries().is_empty());
    assert_eq!((case.fixture.bytes("old-journal")?, case.fixture.bytes("old-witness")?), old_bytes);
    drop(case.old);
    assert_eq!(CellGenerationJournalV2::open_guarded(
        case.fixture.file("old-journal")?,
        case.fixture.witness("old-witness", &case.fixture.old_config)?,
        case.fixture.old_config.clone(), RECORDS, current,
    ).err(), Some(CellGenerationErrorV2::InvalidBinding));
    assert_eq!((case.fixture.bytes("old-journal")?, case.fixture.bytes("old-witness")?), old_bytes);
    Ok(())
}
