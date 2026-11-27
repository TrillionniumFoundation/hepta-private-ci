use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::CellGenerationRequestV2;
use pretty_assertions::assert_eq;

use super::NeuronGenerationUpdatePublicationV1;
use super::NeuronGenerationUpdateReadbackV1;
use super::PreparedNeuronGenerationUpdateV1;
use super::PublishedNeuronGenerationUpdateV1;
use super::test_support::Fixture;
use super::test_support::Journal;
use super::test_support::RECORDS;
use super::test_support::config;
use crate::AgentdError;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::recover_agentd_generation_update_v1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

struct PreparedCase {
    fixture: Fixture,
    old: Journal,
    new: Journal,
    selected: AgentdSelectedGenerationV1,
    prepared: PreparedNeuronGenerationUpdateV1,
    signed: SignedFinalUseGrant,
}

impl PreparedCase {
    fn new() -> anyhow::Result<Self> {
        let fixture = Fixture::new(config()?)?;
        let old = fixture.stopped_old()?;
        let selected = fixture.selection()?;
        let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
        let prepared = fixture
            .current
            .prepare(&old, "replace-task".into(), binding, &selected)?;
        let target = fixture.target_create()?;
        let new = CellGenerationJournalV2::open_guarded(
            target.file,
            target.witness,
            target.config,
            target.max_records,
            fixture.current.clone(),
        )?;
        let signed = fixture.sign(prepared.final_use_binding())?;
        Ok(Self {
            fixture,
            old,
            new,
            selected,
            prepared,
            signed,
        })
    }

    fn publish(&mut self) -> Result<PublishedNeuronGenerationUpdateV1, AgentdError> {
        let mut artifacts = self
            .fixture
            .artifacts
            .lock()
            .map_err(|_| AgentdError::Invalid("artifact lock poisoned".into()))?;
        self.fixture.current.publish(
            &self.prepared,
            &self.old,
            &self.new,
            &mut self.selected,
            NeuronGenerationUpdatePublicationV1 {
                artifacts: &mut artifacts,
                authority: &self.fixture.authority,
                signed: &self.signed,
                clock: self.fixture.clock.as_ref(),
            },
        )
    }
}

#[test]
fn prepared_target_is_durable_but_cannot_dispatch_or_resume() -> anyhow::Result<()> {
    let mut case = PreparedCase::new()?;
    let bytes = case.fixture.bytes("target-journal")?;
    let witness = case.fixture.bytes("target-witness")?;
    assert_eq!(&bytes[..8], b"HPTACG03");
    assert_eq!(bytes.len(), 40);
    let actual = case.new.prepared_checkpoint()?;
    assert_eq!(actual.binding(), case.prepared.target());
    assert_eq!(
        actual.checkpoint(),
        case.prepared.target().genesis_checkpoint()
    );
    assert_eq!(
        case.fixture.current.check_open(case.prepared.target())?,
        CellGenerationOpenModeV1::Preparing
    );
    assert_eq!(case.new.snapshot(), Err(CellGenerationErrorV2::Pending));
    let request = CellGenerationRequestV2 {
        operation_id: "premature-step".into(),
        task_digest: case.fixture.target_config.task_digest,
        source_frontier: case.fixture.target_config.source_frontier,
        predecessor: case.fixture.target_config.initial.clone(),
        input: vec![1],
        admitted_at_micros: 10,
        deadline_micros: 100,
    };
    assert_eq!(
        case.new.admit(request, /*now_micros*/ 10),
        Err(CellGenerationErrorV2::Pending)
    );
    assert_eq!(case.new.resume(), Err(CellGenerationErrorV2::Pending));
    let replay = case.fixture.current.prepare(
        &case.old,
        "replace-task".into(),
        case.prepared.target().clone(),
        &case.selected,
    )?;
    assert_eq!(replay.intent_digest(), case.prepared.intent_digest());
    assert_eq!(case.fixture.bytes("target-journal")?, bytes);
    assert_eq!(case.fixture.bytes("target-witness")?, witness);
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}

#[test]
fn lost_publication_ack_cold_reads_original_and_fences_old_guarded_bytes() -> anyhow::Result<()> {
    let mut case = PreparedCase::new()?;
    let old_bytes = case.fixture.bytes("old-journal")?;
    let old_witness = case.fixture.bytes("old-witness")?;
    let intent = case.prepared.intent_digest();
    case.fixture.lose_publication_ack();
    assert!(case.publish().is_err());
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 1);
    let claims = case.fixture.bytes("final-use/authority.claims")?;
    let current_bytes = case.fixture.bytes("current.json")?;
    assert_eq!(
        case.old.resume(),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    let PreparedCase {
        fixture, old, new, ..
    } = case;
    drop(old);
    drop(new);

    let current = fixture.reopen_current()?;
    let recovered = current.recover_operation("replace-task", intent)?;
    let NeuronGenerationUpdateReadbackV1::Published(original) =
        current.read_operation(&recovered)?
    else {
        anyhow::bail!("committed CAS was incorrectly treated as not applied");
    };
    assert_eq!(original.intent_digest(), intent);
    assert_eq!(
        original.target(),
        &CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?
    );
    let ready = recover_agentd_generation_update_v1(
        current.clone(),
        fixture.authorities()?,
        fixture.selection()?,
        fixture.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "replace-task".into(),
            intent_digest: intent,
        },
    )?;
    drop(ready);
    assert_eq!(
        current.read_operation(&recovered)?,
        NeuronGenerationUpdateReadbackV1::Published(original)
    );
    assert_eq!(fixture.bytes("current.json")?, current_bytes);
    assert_eq!(fixture.bytes("final-use/authority.claims")?, claims);
    assert_eq!(fixture.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        CellGenerationJournalV2::open(
            fixture.file("old-journal")?,
            fixture.witness("old-witness", &fixture.old_config)?,
            fixture.old_config.clone(),
            RECORDS
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        CellGenerationJournalV2::open_guarded(
            fixture.file("old-journal")?,
            fixture.witness("old-witness", &fixture.old_config)?,
            fixture.old_config.clone(),
            RECORDS,
            current
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(fixture.bytes("old-journal")?, old_bytes);
    assert_eq!(fixture.bytes("old-witness")?, old_witness);
    Ok(())
}

#[test]
fn consumed_nonce_with_rejected_cas_stays_pending_until_new_signed_forward_operation()
-> anyhow::Result<()> {
    let mut case = PreparedCase::new()?;
    let prepared_bytes = case.fixture.bytes("current.json")?;
    case.fixture.reject_publication_write();
    assert!(case.publish().is_err());
    assert_eq!(
        case.fixture.current.read_operation(&case.prepared)?,
        NeuronGenerationUpdateReadbackV1::Prepared
    );
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 1);
    let claims = case.fixture.bytes("final-use/authority.claims")?;
    let current = case.fixture.reopen_current()?;
    let cold = current.recover_operation("replace-task", case.prepared.intent_digest())?;
    assert_eq!(
        current.read_operation(&cold)?,
        NeuronGenerationUpdateReadbackV1::Prepared
    );
    assert_eq!(case.new.snapshot(), Err(CellGenerationErrorV2::Pending));
    assert_eq!(case.fixture.bytes("current.json")?, prepared_bytes);
    assert_eq!(case.fixture.bytes("final-use/authority.claims")?, claims);

    let forward = current.prepare_forward_recovery(
        &cold,
        &case.old,
        &case.new,
        "replace-task-forward".into(),
    )?;
    assert_ne!(forward.intent_digest(), cold.intent_digest());
    assert_ne!(forward.final_use_binding(), cold.final_use_binding());
    case.prepared = forward;
    // The old signature cannot authorize the distinct forward operation.
    assert!(case.publish().is_err());
    assert_eq!(case.fixture.bytes("final-use/authority.claims")?, claims);
    case.signed = case.fixture.sign(case.prepared.final_use_binding())?;
    let receipt = case.publish()?;
    assert_eq!(receipt.intent_digest(), case.prepared.intent_digest());
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 2);
    assert_eq!(case.new.snapshot()?, &case.fixture.target_config.initial);
    Ok(())
}

#[test]
fn selection_expiry_after_real_nonce_claim_blocks_final_control_cas() -> anyhow::Result<()> {
    let mut case = PreparedCase::new()?;
    let control = case.fixture.bytes("current.json")?;
    let target = case.fixture.bytes("target-journal")?;
    case.fixture.expire_selection_after_claim()?;
    assert!(case.publish().is_err());
    // The independently persisted nonce proves the first checks passed. The
    // still-valid FinalUse grant cannot bypass the later selection recheck.
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        case.fixture.current.read_operation(&case.prepared)?,
        NeuronGenerationUpdateReadbackV1::Prepared
    );
    assert_eq!(case.fixture.bytes("current.json")?, control);
    assert_eq!(case.fixture.bytes("target-journal")?, target);
    assert_eq!(case.new.snapshot(), Err(CellGenerationErrorV2::Pending));
    Ok(())
}

#[test]
fn actual_new_current_or_withdrawal_cut_rejects_stale_selection_before_claim() -> anyhow::Result<()>
{
    let mut changed_current = PreparedCase::new()?;
    let before = changed_current.fixture.bytes("current.json")?;
    changed_current.fixture.advance_artifact_current()?;
    assert!(changed_current.publish().is_err());
    assert_eq!(changed_current.fixture.bytes("current.json")?, before);
    assert_eq!(changed_current.fixture.authority.capacity()?.used_nonces, 0);

    let mut withdrawn = PreparedCase::new()?;
    let before = withdrawn.fixture.bytes("current.json")?;
    withdrawn.fixture.withdraw()?;
    assert!(withdrawn.publish().is_err());
    assert_eq!(withdrawn.fixture.bytes("current.json")?, before);
    assert_eq!(withdrawn.fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}

#[test]
fn bad_signature_and_wrong_effect_binding_never_advance_current_or_nonce() -> anyhow::Result<()> {
    let mut case = PreparedCase::new()?;
    let before = case.fixture.bytes("current.json")?;
    case.signed.signature[0] ^= 1;
    assert!(case.publish().is_err());
    let mut wrong = case.prepared.final_use_binding().clone();
    wrong.payload_sha256 = [199; 32];
    case.signed = case.fixture.sign(&wrong)?;
    assert!(case.publish().is_err());
    assert_eq!(case.fixture.bytes("current.json")?, before);
    assert_eq!(case.fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}
