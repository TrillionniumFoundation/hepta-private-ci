//! Original host producer for the separate sealed MaterialSource purpose.
//! Both Material signatures must already be completed. This path cannot claim
//! the first Experience/Dataset, sign, fit or publish any result.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::super::OriginalCellQ24MaterialEvidenceErrorV1;
use super::super::OriginalCellQ24MaterialEvidenceOwnerV1;
use super::Error;
use super::evidence_wire;
use super::now;
use super::wire;
use crate::OriginalCellQ24DatasetV1;
use crate::OriginalCellQ24MaterialReceiptOwnersV1;
use crate::OriginalCellQ24MaterialReceiptSourcesV1;

impl<EW: AnchorWitnessStore, DW: AnchorWitnessStore, SW: AnchorWitnessStore>
    OriginalCellQ24MaterialEvidenceOwnerV1<EW, DW, SW>
{
    /// Host-selected, already connected purpose channel. The original pair,
    /// Source and unique Ledger remain in this host and no key is returned.
    /// There is one fixed peer lifetime and one bounded complete frame deadline.
    pub fn serve_material_source(
        &self,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        original_consumer_pidfd: OwnedFd,
    ) -> Result<(), Error> {
        // SAFETY: observe only this process's current credentials.
        let same_uid = policy.peer.uid == unsafe { libc::getuid() }
            || policy.peer.uid == unsafe { libc::geteuid() };
        if same_uid
            || policy.peer.pid == std::process::id()
            || policy.timeout.is_zero()
            || policy.timeout > Duration::from_millis(500)
            || policy.lifetime.is_zero()
            || policy.lifetime > Duration::from_secs(300)
        {
            return Err(Error::Binding("original distinct Material consumer"));
        }
        policy.request_bound = 16 * 1024;
        policy.response_bound = 16 * 1024;
        let mut channel =
            HostAuthorityPeerChannel::from_stream(stream, policy, original_consumer_pidfd)?;
        let mut next_request_id = 1_u64;
        loop {
            let mut failure = None;
            let exchanged = channel.exchange(|bytes| {
                self.respond_material(&mut next_request_id, bytes)
                    .map_err(|error| {
                        failure = Some(error);
                        HostIssuerTransportError::Unavailable
                    })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(()),
                Err(error) => {
                    return Err(match failure {
                        Some(failure) => failure,
                        None => Error::Transport(error),
                    });
                }
            }
        }
    }

    pub(super) fn respond_material(
        &self,
        next_request_id: &mut u64,
        bytes: &[u8],
    ) -> Result<Vec<u8>, Error> {
        let started_at = now()?;
        let request: wire::Request = serde_json::from_slice(bytes)?;
        if request.schema != 1
            || request.operation != wire::OPERATION
            || request.request_id != *next_request_id
            || request.binding != self.config.initial.head_digest.to_string()
            || request.scope != self.config.scope.binding().to_string()
            || request.operation_id != self.config.initial.request.operation_id.as_str()
        {
            return Err(Error::Binding("fixed original Material source request"));
        }
        let next = (*next_request_id)
            .checked_add(1)
            .ok_or(Error::Binding("Material request id overflow"))?;
        let requested_head: Digest32 = request
            .dataset_head
            .parse()
            .map_err(|_| Error::Binding("Material Dataset head"))?;
        if requested_head.to_string() != request.dataset_head {
            return Err(Error::Binding("canonical Material Dataset head"));
        }
        // One original pair supplies both retained signatures. Its Dataset
        // authenticator still performs the two complete Source/Ledger reads
        // and the final physical reread of both journals.
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| Error::Owner(OriginalCellQ24MaterialEvidenceErrorV1::Unavailable))?;
        let mut ledger = self
            .ledger
            .try_lock()
            .map_err(|_| Error::Owner(OriginalCellQ24MaterialEvidenceErrorV1::Unavailable))?;
        let original: &mut OriginalCellQ24MaterialReceiptOwnersV1<EW, DW> = &mut owners;
        let (experience, dataset) =
            OriginalCellQ24MaterialReceiptOwnersV1::readback_material_pair(
                original,
                OriginalCellQ24MaterialReceiptSourcesV1 {
                    snapshot: &self.config.initial,
                    source: &self.source,
                    identity: &self.identity,
                    ledger: &mut ledger,
                    baseline: &self.baseline,
                },
            )
            .map_err(OriginalCellQ24MaterialEvidenceErrorV1::Material)?;
        // No wire encoding or socket I/O occurs under either original lock.
        drop(ledger);
        drop(owners);
        let mut cut = LearningIterationCoordinatorV1::from_snapshot(self.config.initial.clone())?;
        cut.record(
            experience.receipt.clone(),
            experience.receipt.observed_unix_seconds,
        )?;
        cut.record(
            dataset.receipt.clone(),
            dataset.receipt.observed_unix_seconds,
        )?;
        let experience_payload = learning_iteration_receipt_signing_bytes_v1(&experience.receipt)?;
        let dataset_payload = learning_iteration_receipt_signing_bytes_v1(&dataset.receipt)?;
        if cut.snapshot().head_digest != requested_head
            || request.experience_receipt != Digest32::of_bytes(&experience_payload).to_string()
            || request.dataset_receipt != Digest32::of_bytes(&dataset_payload).to_string()
            || experience.material.provenance_digest() != dataset.material.provenance_digest()
            || experience.material.receipt() != dataset.material.receipt()
            || experience.material.batch().encoded() != dataset.material.batch().encoded()
            || experience.receipt.evidence_digest != dataset.material.provenance_digest()
            || dataset.receipt.evidence_digest != dataset.material.provenance_digest()
        {
            return Err(Error::Binding("same original completed Material pair"));
        }
        let fresh_now = now()?;
        if fresh_now < started_at
            || fresh_now < self.config.freeze_evidence.issued_at
            || fresh_now >= self.config.freeze_evidence.expires_at
        {
            return Err(Error::Binding("fresh original Material source window"));
        }
        for (completed, payload, signer) in [
            (
                &experience,
                &experience_payload,
                &self.config.experience_signer,
            ),
            (&dataset, &dataset_payload, &self.config.dataset_signer),
        ] {
            let verified = self.config.verifier.verify(
                LearningEvidenceRoleV1::Observer,
                &completed.attestation,
                payload,
                fresh_now,
            )?;
            if verified.principal() != &signer.principal
                || verified.controller_id() != &signer.controller_id
                || completed.attestation.principal_id != completed.receipt.actor_id
                || completed.attestation.issued_at != completed.receipt.observed_unix_seconds
            {
                return Err(Error::Binding("current original Material signer"));
            }
        }
        let material: &OriginalCellQ24DatasetV1 = &dataset.material;
        let response = wire::Response {
            schema: request.schema,
            operation: request.operation,
            request_id: request.request_id,
            binding: request.binding,
            scope: request.scope,
            operation_id: request.operation_id,
            dataset_head: request.dataset_head,
            experience_receipt: request.experience_receipt,
            dataset_receipt: request.dataset_receipt,
            material: material.original_material_wire(),
            experience: evidence_wire::Evidence::from_original(&experience.attestation),
            dataset: evidence_wire::Evidence::from_original(&dataset.attestation),
        };
        let encoded = serde_json::to_vec(&response)?;
        if encoded.is_empty() || encoded.len() > 16 * 1024 {
            return Err(Error::Binding("bounded original Material source response"));
        }
        *next_request_id = next;
        Ok(encoded)
    }
}
