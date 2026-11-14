//! Synthetic signed receipts; real socket/pidfd I/O is not an experiment or
//! evidence that production signers have independent operators or key custody.

use super::*;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;

pub(super) struct Fixture {
    pub initial: LearningIterationSnapshotV1,
    pub receipt: LearningIterationReceiptV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub signature: SignedLearningEvidenceV1,
}

#[cfg(test)]
impl Fixture {
    pub fn new() -> anyhow::Result<Self> {
        let (_, _, source) =
            crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
        let mut initial = source.snapshot().clone();
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
        initial.request.envelope.expiry_unix_seconds = now + 600;
        let key = SigningKey::from_bytes(&[71; 32]);
        let verifying_key = key.verifying_key().to_bytes();
        let scope_digest = Digest32::of_bytes(b"external-evidence-fixture");
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest,
            objective_digest: initial.request.envelope.objective_digest,
            authority_epoch: 1,
            signers: vec![TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: initial.owners.experience.clone(),
                    credential_chain_digest: Digest32::of_bytes(b"fixture-credential"),
                    signing_key_digest: Digest32::of_bytes(&verifying_key),
                    scope_digest,
                    authority_epoch: 1,
                    authenticated_at: now - 60,
                    expires_at: now + 600,
                },
                controller_id: StableId::new("fixture-controller")?,
                verifying_key,
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            }],
        })?;
        initial.owners.evidence_trust_digest = verifier.trust_digest();
        initial = LearningIterationCoordinatorV1::new(initial.request, initial.owners)?
            .snapshot()
            .clone();
        let receipt = LearningIterationReceiptV1 {
            operation_id: initial.request.operation_id.clone(),
            predecessor: initial.head_digest,
            actor_id: initial.owners.experience.clone(),
            evidence_digest: Digest32::of_bytes(b"fixture-owner-result"),
            observed_unix_seconds: now,
            observation: LearningIterationObservationV1::Experience {
                episode_digest: Digest32::of_bytes(b"fixture-episode"),
                completed_task_receipt: initial.request.completed_task_receipt,
            },
        };
        let mut signature = SignedLearningEvidenceV1 {
            evidence_id: StableId::new("fixture-attestation")?,
            principal_id: receipt.actor_id.clone(),
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: verifier.trust_digest(),
            scope_digest,
            objective_digest: verifier.objective_digest(),
            authority_epoch: 1,
            issued_at: now,
            expires_at: now + 600,
            payload_digest: Digest32::of_bytes(&learning_iteration_receipt_signing_bytes_v1(
                &receipt,
            )?),
            signature: [0; 64],
        };
        signature.signature = key.sign(&signature.signing_bytes()).to_bytes();
        Ok(Self {
            initial,
            receipt,
            verifier,
            signature,
        })
    }

    /// Private same-UID mechanism fixture. The public constructor forbids it;
    /// a separately selected actual-Root test exercises that constructor.
    pub fn client(&self) -> anyhow::Result<(LearningIterationEvidenceClientV1, UnixStream)> {
        let (stream, server) = UnixStream::pair()?;
        let peer = identity(std::process::id())?;
        // SAFETY: this only reads the fixture process's current UID.
        let uid = unsafe { libc::geteuid() };
        let transport = RootObservationStream::from_stream_for_uid(
            stream,
            peer,
            pidfd(std::process::id())?,
            Duration::from_millis(500),
            Duration::from_secs(5),
            uid,
        )?;
        Ok((
            LearningIterationEvidenceClientV1 {
                channel: Mutex::new(Some(Channel {
                    transport,
                    next_request_id: 1,
                })),
                initial: self.initial.clone(),
                actor_id: self.receipt.actor_id.clone(),
                verifier: self.verifier.clone(),
            },
            server,
        ))
    }

    pub fn evidence(&self) -> wire::Evidence {
        let evidence = &self.signature;
        wire::Evidence {
            evidence_id: evidence.evidence_id.to_string(),
            principal_id: evidence.principal_id.to_string(),
            role: match evidence.role {
                LearningEvidenceRoleV1::Generator => "generator",
                LearningEvidenceRoleV1::Observer => "observer",
                LearningEvidenceRoleV1::Evaluator => "evaluator",
                // Preserve non-stage roles; the stage wire decoder rejects them.
                LearningEvidenceRoleV1::CreditAllocator => "credit_allocator",
                LearningEvidenceRoleV1::UnlearningAuthority => "unlearning_authority",
                LearningEvidenceRoleV1::Selector => "selector",
            }
            .into(),
            trust_digest: evidence.trust_digest.to_string(),
            scope_digest: evidence.scope_digest.to_string(),
            objective_digest: evidence.objective_digest.to_string(),
            authority_epoch: evidence.authority_epoch,
            issued_at: evidence.issued_at,
            expires_at: evidence.expires_at,
            payload_digest: evidence.payload_digest.to_string(),
            signature: STANDARD_NO_PAD.encode(evidence.signature),
        }
    }
}

pub(super) fn identity(pid: u32) -> anyhow::Result<AgentdRootAuthorityPeer> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("missing stat fields"))?
            .1
            .split_whitespace()
            .nth(19)
            .ok_or_else(|| anyhow::anyhow!("missing process start"))?
            .parse()?,
    })
}

pub(super) fn pidfd(pid: u32) -> anyhow::Result<OwnedFd> {
    // SAFETY: pin one live fixture process and exclusively own the returned FD.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    anyhow::ensure!(fd >= 0, "{}", std::io::Error::last_os_error());
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

pub(super) fn read_request(server: &mut UnixStream) -> anyhow::Result<wire::Request> {
    server.set_read_timeout(Some(Duration::from_secs(2)))?;
    let mut prefix = [0; 4];
    server.read_exact(&mut prefix)?;
    let length = u32::from_be_bytes(prefix) as usize;
    anyhow::ensure!(length > 0 && length <= 16_384);
    let mut bytes = vec![0; length];
    server.read_exact(&mut bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}

pub(super) fn response(request: wire::Request, evidence: wire::Evidence) -> wire::Response {
    wire::Response {
        schema: 1,
        operation: request.operation,
        request_id: request.request_id,
        binding: request.binding,
        snapshot_head: request.snapshot_head,
        receipt_digest: request.receipt_digest,
        evidence,
    }
}

pub(super) fn reply(server: &mut UnixStream, response: &wire::Response) -> anyhow::Result<()> {
    let bytes = serde_json::to_vec(response)?;
    server.write_all(&(bytes.len() as u32).to_be_bytes())?;
    server.write_all(&bytes)?;
    Ok(())
}
