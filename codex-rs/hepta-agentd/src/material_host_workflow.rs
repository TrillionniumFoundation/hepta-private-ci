//! Four fixed data exchanges with the preheld actual Root supervisor. This
//! protocol never deserializes a Source/Receipt owner or grants signing rights.
//! Each whole frame is bounded; oversized complete inputs fail without paging,
//! truncation, retry or a second Source allowance.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::{HostAuthorityPeerChannel, HostAuthorityPeerPolicy,
    HostIssuerPeer, HostIssuerTransportError};
use codex_hepta_learning_artifacts::{FrozenLearningScopeV2, LearningIterationCoordinatorV1,
    LearningIterationSnapshotV1, LearningIterationStageV1, LearningUpdateScopeV2};
use codex_hepta_learning_ledger::{DatasetFreezePlanV2, LearningEvidenceRoleV1, LedgerSnapshot,
    LedgerWriter, dataset_freeze_signing_payload_v2};
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::{Value, json};
use crate::{AgentdError, CellQ24DatasetRuleV1, CircuitTaskSourcePublicationV1,
    LoadedCellQ24ModelV1, OriginalCellQ24MaterialReceiptConfigV1, OriginalCircuitPrefreezeSourceV1};
use super::{OriginalMaterialChannelFilesV1, config::{self, Configuration, Operation, UpdateScope},
    files, intake, invalid, trust::{self, Evidence, OriginalMaterialTrust}};

const PURPOSE: &str = "hepta.original-material-workflow.v1";
const BOUND: usize = 65_536;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32, purpose: String, binding: String,
    nonce: [u8; 16], request_id: u64, action: Action,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Observe,
    Prepare { initial_snapshot: String, experience: Experience },
    Freeze { evidence: Evidence },
    Ready,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Experience {
    Append { signed: intake::SignedExperience },
    ReadExisting,
}

pub(super) struct PendingReady {
    channel: Workflow,
    initial_head: Digest32,
    scope_binding: Digest32,
    operation: Operation,
}

struct Workflow {
    original: HostAuthorityPeerChannel,
    binding: Digest32,
    nonce: [u8; 16],
    next: u64,
    end: Instant,
    last_wall: u64,
}

struct Prepared {
    initial: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    rule: CellQ24DatasetRuleV1,
    plan: DatasetFreezePlanV2,
    snapshot: LedgerSnapshot,
    payload: Vec<u8>,
}

pub(super) fn complete_original_material(
    cfg: &Configuration, trusted: &OriginalMaterialTrust,
    source: &mut OriginalCircuitPrefreezeSourceV1, ledger: &Arc<Mutex<LedgerWriter>>,
    baseline: &LoadedCellQ24ModelV1, channel: OriginalMaterialChannelFilesV1, end: Instant,
) -> Result<(OriginalCellQ24MaterialReceiptConfigV1, PendingReady), AgentdError> {
    files::require_peer(&channel.stream, &channel.original_peer_pidfd,
        &cfg.workflow_root, 0, cfg.workflow_root_gid)?;
    let source_request = Configuration::original_source_request(cfg, trusted)?;
    let binding = Digest32::of_parts(&[b"hepta.original-material-workflow.v1\0",
        &crate::OriginalCircuitPrefreezeSourceRequestV1::signing_payload(&source_request).map_err(invalid)?]);
    let original = HostAuthorityPeerChannel::from_stream(channel.stream, HostAuthorityPeerPolicy {
        peer: HostIssuerPeer { uid: 0, pid: cfg.workflow_root.pid },
        timeout: Duration::from_millis(500), lifetime: files::remaining(end)?,
        request_bound: BOUND, response_bound: BOUND,
    }, channel.original_peer_pidfd).map_err(invalid)?;
    let mut workflow = Workflow { original, binding, nonce: cfg.nonce, next: 1, end, last_wall: files::now()? };

    let observed = workflow.exchange(|action, deadline| {
        if !matches!(action, Action::Observe) { return Err(invalid("expected the original Source observation request")); }
        trusted.require_window(files::now()?)?;
        files::remaining(deadline)?;
        let observed = OriginalCircuitPrefreezeSourceV1::read_original_publication(source).map_err(invalid)?;
        files::remaining(deadline)?;
        let body = intake::publication(&observed);
        trusted.require_window(files::now()?)?;
        Ok((observed, body))
    })?;

    let prepared = workflow.exchange(|action, deadline| {
        let Action::Prepare { initial_snapshot, experience } = action else {
            return Err(invalid("expected original signed experience and initial snapshot"));
        };
        trusted.require_window(files::now()?)?;
        require_source(source, &observed, deadline)?;
        let bytes = trust::decode(&initial_snapshot, 8192)?;
        let initial = crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1(&bytes).map_err(invalid)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone()).map_err(invalid)?;
        if !initial.receipts.is_empty() || coordinator.next_stage() != Some(LearningIterationStageV1::Experience)
            || initial.owners.evidence_trust_digest != trusted.activation().verifier().trust_digest()
            || initial.owners.experience != config::id(&cfg.experience_actor)?
            || initial.owners.dataset != config::id(&cfg.dataset_actor)?
            || LoadedCellQ24ModelV1::components(baseline) != &initial.request.selected_bundle.components
        { return Err(invalid("original Material initial snapshot, enrolled pair or full baseline differs")); }
        crate::cell_q24_dataset::require_source(&Configuration::original_identity(cfg)?, &observed, &initial.request).map_err(invalid)?;
        let rule = Configuration::rule(cfg)?;
        let head = match rule.head { crate::CellQ24PrivateHeadV1::Drive { index }
            | crate::CellQ24PrivateHeadV1::Prediction { index } => index };
        if usize::from(head) >= LoadedCellQ24ModelV1::output_width(baseline) {
            return Err(invalid("original private head is outside the actual model"));
        }
        let scope = FrozenLearningScopeV2::freeze(&initial.request, &initial.owners,
            match cfg.update_scope { UpdateScope::Cell => LearningUpdateScopeV2::Cell,
                UpdateScope::Organ => LearningUpdateScopeV2::Organ }, config::digest(&cfg.update_rule)?).map_err(invalid)?;
        FrozenLearningScopeV2::validate_snapshot(&scope, &initial).map_err(invalid)?;
        let plan = DatasetFreezePlanV2 { snapshot_id: config::id(&cfg.snapshot_id)?,
            objective_digest: initial.request.envelope.objective_digest,
            inclusion_policy_digest: CellQ24DatasetRuleV1::inclusion_policy_digest(&rule, &initial).map_err(invalid)? };
        match (cfg.operation, experience) {
            (Operation::Create, Experience::Append { signed }) => {
                if files::now()? >= initial.request.envelope.expiry_unix_seconds {
                    return Err(invalid("original new-work deadline ended before experience intake"));
                }
                // The original function authenticates the real Source first,
                // then Generator and independent Observer, then performs its
                // two witnessed appends. Any error may leave original effects.
                let signed = intake::SignedExperience::original(signed)?;
                files::remaining(deadline)?;
                OriginalCircuitPrefreezeSourceV1::append_original_experience_v2(source, &signed).map_err(invalid)?;
                files::remaining(deadline)?;
            }
            (Operation::Recover, Experience::ReadExisting) => {},
            _ => return Err(invalid("recovery cannot append new experience and creation cannot skip its original input")),
        }
        require_source(source, &observed, deadline)?;
        let snapshot = {
            let mut original = ledger.try_lock().map_err(|_| invalid("original Material ledger is busy"))?;
            files::remaining(deadline)?;
            LedgerWriter::read_current_durable_snapshot(&mut original).map_err(invalid)?
        };
        files::remaining(deadline)?;
        let payload = dataset_freeze_signing_payload_v2(&snapshot, &plan).map_err(invalid)?;
        if payload.len() > BOUND { return Err(invalid("complete original freeze payload exceeds the fixed frame")); }
        let body = json!({"initial_head":initial.head_digest.to_string(),"scope_binding":scope.binding().to_string(),
            "ledger_head":snapshot.head_digest.to_string(),"snapshot_id":plan.snapshot_id.as_str(),
            "objective_digest":plan.objective_digest.to_string(),"inclusion_policy_digest":plan.inclusion_policy_digest.to_string(),
            "freeze_signing_payload":STANDARD_NO_PAD.encode(&payload)});
        trusted.require_window(files::now()?)?;
        Ok((Prepared { initial, scope, rule, plan, snapshot, payload }, body))
    })?;

    let config = workflow.exchange(|action, deadline| {
        let Action::Freeze { evidence } = action else { return Err(invalid("expected the original Evaluator freeze signature")); };
        trusted.require_window(files::now()?)?;
        require_source(source, &observed, deadline)?;
        let evidence = Evidence::original(&evidence)?;
        let now = files::now()?;
        {
            let mut original = ledger.try_lock().map_err(|_| invalid("original Material ledger is busy"))?;
            files::remaining(deadline)?;
            let before = LedgerWriter::read_current_durable_snapshot(&mut original).map_err(invalid)?;
            files::remaining(deadline)?;
            if before != prepared.snapshot || dataset_freeze_signing_payload_v2(&before, &prepared.plan).map_err(invalid)? != prepared.payload {
                return Err(invalid("original freeze cut changed while its real Evaluator signed"));
            }
            let receipt = LedgerWriter::freeze_dataset(&original, prepared.plan.clone(), &evidence, now).map_err(invalid)?;
            files::remaining(deadline)?;
            if receipt.snapshot.ledger_head_digest != before.head_digest {
                return Err(invalid("original freeze receipt is not the physically re-read ledger"));
            }
            LedgerWriter::read_dataset_records(&original, &receipt, now).map_err(invalid)?;
            files::remaining(deadline)?;
            if LedgerWriter::read_current_durable_snapshot(&mut original).map_err(invalid)? != before {
                return Err(invalid("original ledger/witness changed during freeze verification"));
            }
        }
        require_source(source, &observed, deadline)?;
        trusted.require_window(files::now()?)?;
        let config = OriginalCellQ24MaterialReceiptConfigV1 {
            initial: prepared.initial, scope: prepared.scope, rule: prepared.rule,
            freeze_plan: prepared.plan, freeze_evidence: evidence,
            experience_signer: trusted.signer(&config::id(&cfg.experience_actor)?, LearningEvidenceRoleV1::Observer, files::now()?)?,
            dataset_signer: trusted.signer(&config::id(&cfg.dataset_actor)?, LearningEvidenceRoleV1::Observer, files::now()?)?,
            verifier: trusted.activation().verifier().clone(),
            maximum_signature_lifetime_seconds: cfg.maximum_signature_lifetime_seconds,
        };
        Ok((config, json!({"status":"original_freeze_verified"})))
    })?;
    let ready = PendingReady { initial_head: config.initial.head_digest,
        scope_binding: FrozenLearningScopeV2::binding(&config.scope), operation: cfg.operation, channel: workflow };
    Ok((config, ready))
}

impl PendingReady {
    /// Called only after the concrete pair was created/recovered and consumed
    /// with the same Source/ledger. This is not Adopt, C or proof that all five
    /// service loops subsequently succeeded. A lost ACK is not permission to
    /// recreate or resend the original pair.
    pub(super) fn acknowledge_original_pair(mut self, trust: &OriginalMaterialTrust) -> Result<(), AgentdError> {
        let initial_head = self.initial_head;
        let scope_binding = self.scope_binding;
        let operation = self.operation;
        self.channel.exchange(|action, deadline| {
            if !matches!(action, Action::Ready) { return Err(invalid("expected original pair readiness request")); }
            trust.require_window(files::now()?)?;
            files::remaining(deadline)?;
            Ok(((), json!({"status":"original_pair_ready","initial_head":initial_head.to_string(),
                "scope_binding":scope_binding.to_string(),"mode":match operation {
                    Operation::Create => "created", Operation::Recover => "recovered_readback_only" }})))
        })
    }
}

impl Workflow {
    fn exchange<T>(&mut self, handle: impl FnOnce(Action, Instant) -> Result<(T, Value), AgentdError>) -> Result<T, AgentdError> {
        if !(1..=4).contains(&self.next) { return Err(invalid("original Material workflow has no further exchange")); }
        files::remaining(self.end)?;
        let mut result = None;
        let mut failure = None;
        let mut observed_wall = self.last_wall;
        let binding = self.binding;
        let nonce = self.nonce;
        let next = self.next;
        let end = self.end;
        let previous_wall = self.last_wall;
        let exchanged = self.original.exchange(|bytes| {
            let response = (|| {
                let deadline = (Instant::now() + Duration::from_millis(500)).min(end);
                files::remaining(deadline)?;
                let at = files::now()?;
                if at < previous_wall { return Err(invalid("original workflow clock moved backwards")); }
                let request: Request = serde_json::from_slice(bytes).map_err(invalid)?;
                if request.schema_version != 1 || request.purpose != PURPOSE || request.request_id != next
                    || request.nonce != nonce || config::digest(&request.binding)? != binding
                { return Err(invalid("fixed Material workflow binding/order differs")); }
                let (value, body) = handle(request.action, deadline)?;
                observed_wall = files::now()?;
                if observed_wall < at { return Err(invalid("original workflow clock moved backwards during owner I/O")); }
                let encoded = serde_json::to_vec(&json!({"schema_version":1,"purpose":PURPOSE,
                    "binding":binding.to_string(),"nonce":nonce,"request_id":next,"body":body})).map_err(invalid)?;
                if encoded.is_empty() || encoded.len() > BOUND { return Err(invalid("complete Material response exceeds the fixed frame")); }
                files::remaining(deadline)?;
                result = Some(value);
                Ok(encoded)
            })();
            response.map_err(|error| { failure = Some(error); HostIssuerTransportError::InvalidRequest })
        });
        match exchanged {
            Ok(true) => {},
            Ok(false) => return Err(invalid("original Material workflow closed before its required exchange")),
            Err(error) => return Err(failure.unwrap_or_else(|| invalid(error))),
        }
        files::remaining(end)?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.original).map_err(invalid)?;
        self.next += 1;
        self.last_wall = observed_wall;
        result.ok_or_else(|| invalid("original Material workflow has no completed response"))
    }
}

fn require_source(source: &OriginalCircuitPrefreezeSourceV1, expected: &CircuitTaskSourcePublicationV1, deadline: Instant) -> Result<(), AgentdError> {
    files::remaining(deadline)?;
    if OriginalCircuitPrefreezeSourceV1::read_original_publication(source).map_err(invalid)? != *expected {
        return Err(invalid("actual original Source/Cell publication changed"));
    }
    files::remaining(deadline)?;
    Ok(())
}
