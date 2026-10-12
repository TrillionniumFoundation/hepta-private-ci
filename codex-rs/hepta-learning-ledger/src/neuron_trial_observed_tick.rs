//! Independent Observer correlation of one Agentd Neuron tick to a native
//! durable Decision/terminal Outcome. No inference, private label, selection,
//! runtime route or production final-use authority is issued here.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DatasetFreezePlanV2;
use crate::DatasetSnapshotReceiptV3;
use crate::LearningEvidenceRoleV1;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::LedgerWriter;
use crate::NeuronTrialLedgerSourceV1;
use crate::NeuronTrialSourceError;
use crate::NeuronTrialTerminalJoinV1;
use crate::SignedLearningEvidenceV1;

const LINK_DOMAIN: &[u8] = b"hepta.learning-ledger.neuron.observer-tick-episode.v1\0";
const RECEIPT_DOMAIN: &[u8] = b"hepta.learning-ledger.neuron.observer-tick-receipt.v1\0";

/// Only the actual ledger owner can validate the native cohort underlying
/// this observation. The signature is independently verified at read time.
/// This struct's digest alone is NOT a portable proof of production execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTrialObservedTickLinkV1 {
    pub episode_id: StableId,
    pub frozen_dataset_digest: Digest32,
    pub decision_event_digest: Digest32,
    pub outcome_event_digest: Digest32,
    pub tick_observation_digest: Digest32,
    pub tick_generation: Generation,
    pub observer_principal_id: StableId,
    pub observer_controller_id: StableId,
    pub observer_trust_digest: Digest32,
    pub observer_signature_digest: Digest32,
    pub observer_signed_at: u64,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronTrialObservedTickLinkV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = RECEIPT_DOMAIN.to_vec();
        push_id(&mut bytes, &self.episode_id);
        for digest in [
            self.frozen_dataset_digest,
            self.decision_event_digest,
            self.outcome_event_digest,
            self.tick_observation_digest,
            self.observer_trust_digest,
            self.observer_signature_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.tick_generation.get().to_be_bytes());
        push_id(&mut bytes, &self.observer_principal_id);
        push_id(&mut bytes, &self.observer_controller_id);
        bytes.extend_from_slice(&self.observer_signed_at.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    /// This detects field corruption, not signer/clock/currentness authority.
    /// The original signed link and live owner must be reverified at final use.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.frozen_dataset_digest.is_zero()
            && !self.decision_event_digest.is_zero()
            && !self.outcome_event_digest.is_zero()
            && !self.tick_observation_digest.is_zero()
            && !self.observer_trust_digest.is_zero()
            && !self.observer_signature_digest.is_zero()
            && self.observer_signed_at != 0
            && self.diagnostic_digest == self.computed_digest()
    }
}

/// Canonical payload handed to an independently operated Observer signer.
/// Caller-side preparation is never admission: the Ledger owner rebuilds
/// and checks the *entire* native source on signed-use validation.
pub fn neuron_trial_observer_tick_link_payload_v1(
    source: &NeuronTrialLedgerSourceV1,
    pair: &NeuronTrialTerminalJoinV1,
    tick_observation_digest: Digest32,
    tick_objective_digest: Digest32,
    tick_generation: Generation,
) -> Result<Vec<u8>, NeuronTrialSourceError> {
    if !source.validate_integrity()
        || !source.terminal_joins.contains(pair)
        || source.pending_episodes != 0
        || source.censored_episodes != 0
        || tick_observation_digest.is_zero()
        || tick_objective_digest.is_zero()
    {
        return Err(NeuronTrialSourceError::Invalid(
            "invalid observer tick source",
        ));
    }
    let mut bytes = LINK_DOMAIN.to_vec();
    bytes.extend_from_slice(source.frozen_dataset_digest.as_array());
    bytes.extend_from_slice(source.diagnostic_digest.as_array());
    push_id(&mut bytes, &pair.episode_id);
    for digest in [
        pair.decision_event_digest,
        pair.outcome_event_digest,
        pair.run_snapshot_digest,
        pair.policy_digest,
        pair.decision_support_digest,
        tick_observation_digest,
        tick_objective_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &pair.selected_candidate_id);
    bytes.extend_from_slice(&tick_generation.get().to_be_bytes());
    Ok(bytes)
}

impl LedgerWriter {
    /// Verify that an independent Observer has signed the correlation of an
    /// already committed, witness-acknowledged tick digest to the exact native
    /// Decision and terminal Outcome from the currently eligible frozen cohort.
    ///
    /// The source read checks the live Ledger, trust, revocation and witness.
    /// The caller must separately prove the tick came from the actual Agentd
    /// model owner, and that its selected route and physical weights were real.
    #[allow(clippy::too_many_arguments)]
    pub fn read_observer_linked_neuron_tick_v1(
        &self,
        frozen_ledger: &LedgerSnapshot,
        plan: &DatasetFreezePlanV2,
        signed_freeze: &SignedLearningEvidenceV1,
        dataset: &DatasetSnapshotReceiptV3,
        episode_id: &StableId,
        tick_observation_digest: Digest32,
        tick_objective_digest: Digest32,
        tick_generation: Generation,
        observer_link: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<NeuronTrialObservedTickLinkV1, NeuronTrialSourceError> {
        if tick_objective_digest != plan.objective_digest {
            return Err(NeuronTrialSourceError::Invalid(
                "Neuron tick objective mismatch",
            ));
        }
        let source =
            self.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?;
        let pair = source
            .terminal_joins
            .iter()
            .find(|join| &join.episode_id == episode_id)
            .ok_or(NeuronTrialSourceError::Invalid(
                "terminal episode not in native cohort",
            ))?;
        let mut native_decision = None;
        let mut finalized_at = None;
        for record in frozen_ledger.records() {
            match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value)
                    if record.event_digest == pair.decision_event_digest
                        && value.record_id == pair.decision_record_id
                        && value.episode_id == pair.episode_id =>
                {
                    native_decision = Some(value);
                }
                LedgerEvent::AuthenticatedOutcomeV2(value)
                    if record.event_digest == pair.outcome_event_digest
                        && value.record_id == pair.outcome_record_id
                        && value.episode_id == pair.episode_id =>
                {
                    finalized_at = value.finalized_at;
                }
                _ => {}
            }
        }
        let decision = native_decision.ok_or(NeuronTrialSourceError::Invalid(
            "native generator Decision absent",
        ))?;
        let finalized_at = finalized_at.ok_or(NeuronTrialSourceError::Invalid(
            "native terminal finalization absent",
        ))?;
        if observer_link.issued_at < finalized_at {
            return Err(NeuronTrialSourceError::Invalid(
                "Observer signed before terminal outcome was finalized",
            ));
        }
        let payload = neuron_trial_observer_tick_link_payload_v1(
            &source,
            pair,
            tick_observation_digest,
            tick_objective_digest,
            tick_generation,
        )?;
        let verified = self.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            observer_link,
            &payload,
            now,
        )?;
        if verified.principal().principal_id == decision.generator_id
            || verified.controller_id() == &decision.generator_controller_id
            || verified.principal().credential_chain_digest
                == decision.generator_credential_chain_digest
            || verified.principal().signing_key_digest == decision.generator_signing_key_digest
        {
            return Err(NeuronTrialSourceError::Invalid(
                "Observer shares generator authority",
            ));
        }
        // No yield or asynchronous owner mutation occurs here. Nonetheless,
        // re-read the source after verifying the independent signature so a
        // corrected/withdrawn lineage cannot pass merely on a stale digest.
        if self.read_neuron_trial_source_v1(frozen_ledger, plan, signed_freeze, dataset, now)?
            != source
        {
            return Err(NeuronTrialSourceError::Invalid(
                "native Ledger cohort changed during Observer validation",
            ));
        }
        let mut signature_bytes = observer_link.signing_bytes();
        signature_bytes.extend_from_slice(&observer_link.signature);
        let mut link = NeuronTrialObservedTickLinkV1 {
            episode_id: episode_id.clone(),
            frozen_dataset_digest: source.frozen_dataset_digest,
            decision_event_digest: pair.decision_event_digest,
            outcome_event_digest: pair.outcome_event_digest,
            tick_observation_digest,
            tick_generation,
            observer_principal_id: verified.principal().principal_id.clone(),
            observer_controller_id: verified.controller_id().clone(),
            observer_trust_digest: verified.trust_digest(),
            observer_signature_digest: Digest32::of_bytes(&signature_bytes),
            observer_signed_at: observer_link.issued_at,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        link.diagnostic_digest = link.computed_digest();
        Ok(link)
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
