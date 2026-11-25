//! One synchronous fixed read and response inside the four-record boundary.
//! The entered tombstone precedes all material bytes and is never cleared.
use super::*;
use crate::authority_host_service::OriginalHumanLifetime;
use crate::paired_preparation::material_protocol::FRAME_BOUND;
use crate::paired_preparation::material_protocol::PairedTrainingReadRequest;
use crate::paired_preparation::material_protocol::PairedTrainingReadResponse;
use base64::Engine as _;
use codex_hepta_contracts::HostAuthorityPeerResponse;

impl RegisteredRootPaired {
    pub(crate) fn install_fixed_training_materials(
        &mut self,
        manifest: PairedTrainingMaterialManifestV1,
        failure: File,
        correction: File,
        owner_uid: u32,
    ) -> io::Result<()> {
        // SAFETY: reads the existing effective kernel credential only.
        if unsafe { libc::geteuid() } != 0 || self.training_materials.is_some() {
            return Err(denied(
                "fixed paired materials require their one original Root installation",
            ));
        }
        self.observe()?;
        self.training_materials = Some(FixedTrainingMaterials::capture(
            &self.registration,
            manifest,
            failure,
            correction,
            owner_uid,
        )?);
        Ok(())
    }

    pub(crate) fn read_fixed_training_once(
        &self,
        identity: &AgentdIdentity,
        request: &PairedTrainingReadRequest,
        held: &OriginalHumanLifetime<'_>,
        response: &HostAuthorityPeerResponse<'_>,
    ) -> io::Result<()> {
        let peer = response.current();
        let materials = self
            .training_materials
            .as_ref()
            .ok_or_else(|| denied("original fixed paired materials are not installed"))?;
        materials.manifest.matches(&self.registration)?;
        let semantic = request.verify_registered(&self.registration, &self.writer, &self.proof)?;
        let inspection = PairedRootInspection::OriginalHuman {
            identity,
            ingress: request.ingress(),
            held,
        };
        let pinned = self
            .issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("original protected issuer missing"))?;
        let verifier = self.registry.verifier();
        let token = |lease: &AuthorityLease| {
            verifier
                .verify_use(&lease.lease_id, lease.revision, &lease.binding)
                .map_err(root::lease_error)
        };
        pinned
            .verifier
            .with_pinned_issuer_paired_dispatch_boundary(
                pinned.identity(),
                (
                    token(&self.writer.authority_lease)?,
                    &self.writer.authority_lease.binding,
                ),
                (token(&self.effect)?, &self.effect.binding),
                (token(&self.enrollment)?, &self.enrollment.binding),
                |issuer, writer, effect, enrollment, entered_now, _revision| {
                    if writer != &self.writer.authority_lease
                        || effect != &self.effect
                        || enrollment != &self.enrollment
                        || effect.expires_at_unix_ms > issuer.expires_at_unix_ms
                    {
                        return Err(denied("original paired dependency record changed"));
                    }
                    // Registry -> request lock. No await or full human verifier;
                    // the same loaded-state predicate never reacquires either lock.
                    let _guard = self
                        .issuer
                        .request_lock
                        .lock()
                        .map_err(|_| denied("issuer fenced"))?;
                    let check = |state: &IssuerState, floor: u64| -> io::Result<u64> {
                        peer.recheck_original_exchange().map_err(io::Error::other)?;
                        if self
                            .issuer
                            .store
                            .load(STATE_OWNER)
                            .map_err(io::Error::other)?
                            != *state
                            || self.issuer.retained_writer_authorization(&self.writer)?
                                != self.proof
                            || state
                                .policies
                                .iter()
                                .filter(|p| p.destination_id == self.policy.destination_id)
                                .collect::<Vec<_>>()
                                != vec![&self.policy]
                        {
                            return Err(denied("original paired issuer state or policy changed"));
                        }
                        let now = inspection.verify(self, state, floor)?;
                        if [issuer, writer, effect, enrollment]
                            .iter()
                            .any(|lease| now >= lease.expires_at_unix_ms)
                            || now >= self.registration.human_expires_at_ms
                        {
                            return Err(denied(
                                "paired material authorization expired at the read boundary",
                            ));
                        }
                        peer.recheck_original_exchange().map_err(io::Error::other)?;
                        let after_peer =
                            self.issuer.clock.now_unix_ms().map_err(io::Error::other)?;
                        if after_peer < now
                            || [issuer, writer, effect, enrollment]
                                .iter()
                                .any(|lease| after_peer >= lease.expires_at_unix_ms)
                            || after_peer >= self.registration.human_expires_at_ms
                            || after_peer >= request.ingress().expires_at_ms
                        {
                            return Err(denied(
                                "paired authorization expired during final peer observation",
                            ));
                        }
                        Ok(after_peer)
                    };
                    let state = self
                        .issuer
                        .store
                        .load(STATE_OWNER)
                        .map_err(io::Error::other)?;
                    let now = check(&state, entered_now)?;
                    let retained = match self.retain_material_entry(&state, semantic, now)? {
                        PreparedMaterialEntry::Fresh { retained_state } => retained_state,
                        PreparedMaterialEntry::Retained(_) => {
                            let encoded = serde_json::to_vec(
                                &PairedTrainingReadResponse::RetainedReadOnly {
                                    original_delivery: self
                                        .registration
                                        .request
                                        .original
                                        .delivery_id
                                        .to_string(),
                                },
                            )?;
                            let mut now = now;
                            return response
                                .write_response(&encoded, || {
                                    now = check(&state, now).map_err(|_| {
                                        codex_hepta_contracts::HostIssuerTransportError::Unavailable
                                    })?;
                                    Ok(())
                                })
                                .map_err(io::Error::other);
                        }
                    };
                    // No first byte may precede the successful Entered CAS. A CAS
                    // error, crash, lost reply or any subsequent refusal is retained
                    // as uncertain; retry cannot reach this call a second time.
                    let mut now = check(&retained, now)?;
                    let bytes = materials.read_after_entry(peer.deadline(), &mut || {
                        now = check(&retained, now)?;
                        Ok(())
                    })?;
                    let mut now = check(&retained, now)?;
                    let committed = self.commit_material_read(&retained, semantic)?;
                    let encoded = serde_json::to_vec(&PairedTrainingReadResponse::FreshRead {
                        original_delivery: self
                            .registration
                            .request
                            .original
                            .delivery_id
                            .to_string(),
                        materials_sha256: materials.manifest.commitment()?.to_string(),
                        failure_base64: base64::engine::general_purpose::STANDARD
                            .encode(bytes.failure),
                        correction_base64: base64::engine::general_purpose::STANDARD
                            .encode(bytes.correction),
                    })?;
                    if encoded.len() > FRAME_BOUND {
                        return Err(denied("paired material response exceeds its fixed bound"));
                    }
                    // Complete content and encoding are validated before the
                    // prefix. Registry and request locks stay held while the same
                    // private fence runs after every writable wait and before each
                    // actual write. Partial sends and lost replies stay consumed;
                    // ReadCommitted is not receipt, adoption or FinalUse evidence.
                    response
                        .write_response(&encoded, || {
                            now = check(&committed, now).map_err(|_| {
                                codex_hepta_contracts::HostIssuerTransportError::Unavailable
                            })?;
                            Ok(())
                        })
                        .map_err(io::Error::other)
                },
            )
            .map_err(root::lease_error)?
    }
}
