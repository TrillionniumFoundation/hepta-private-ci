//! Typed inference.control -> inference.worker production composition seam.
//!
//! Planning remains authority-free. This port accepts a kernel-owned
//! FinalUseAuthority and independently signed grant at execution time, then
//! delegates the exact fresh request to the worker's final-use-gated path.

#![forbid(unsafe_code)]

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use sha2::Digest;
use sha2::Sha256;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeRunOutput;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use tokio_util::sync::CancellationToken;

pub type WorkerPortResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeUsageReconciliation {
    pub request_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub model_provider: String,
    pub observed_output_tokens: u64,
    pub evidence_digest: String,
}

/// Source-composed implementation of
/// `ModulePort::inference.control::inference.worker`.
///
/// This type does not issue grants, widen authority, or own inference state.
/// Durable reservation/dispatch/settlement remains in DurableInferenceControl;
/// final-use verification remains in kernel.authority; execution remains in
/// inference.worker.
pub struct NativeWorkerPort {
    driver: AppServerModelDriver,
}

impl NativeWorkerPort {
    pub fn new(config: NativeWorkerConfig) -> WorkerPortResult<Self> {
        Ok(Self {
            driver: AppServerModelDriver::new(config)?,
        })
    }

    /// Return the exact binding an external authority owner must sign for a
    /// fresh provider dispatch through this port.
    pub fn final_use_binding(
        &self,
        request_id: &str,
        prompt: &str,
    ) -> WorkerPortResult<FinalUseBinding> {
        self.driver.provider_final_use_binding(request_id, prompt)
    }

    /// Build the exact final-use binding for independently observed provider
    /// usage. Terminal output alone is not billing/resource-settlement authority.
    pub fn usage_reconciliation_binding(
        &self,
        control: &DurableInferenceControl,
        usage: &NativeUsageReconciliation,
    ) -> WorkerPortResult<FinalUseBinding> {
        validate_digest(&usage.evidence_digest)?;
        let record = control
            .native_record(&usage.request_id)
            .ok_or("native request not found")?;
        let dispatch = record
            .dispatch
            .as_ref()
            .ok_or("native request has no provider dispatch")?;
        let output = record
            .observation
            .as_ref()
            .ok_or("native request has no provider observation")?;
        if !output.terminal_observed
            || record.turn_id.as_deref() != Some(usage.turn_id.as_str())
            || dispatch.thread_id != usage.thread_id
            || dispatch.model_provider != usage.model_provider
            || output.thread_id != usage.thread_id
            || output.turn_id != usage.turn_id
            || output.model_provider != usage.model_provider
        {
            return Err("usage reconciliation identity does not match terminal provider truth".into());
        }
        if output
            .observed_output_tokens
            .is_some_and(|observed| observed != usage.observed_output_tokens)
        {
            return Err("authoritative usage conflicts with provider-observed usage".into());
        }
        Ok(FinalUseBinding {
            subject_id: record.request.principal_id.clone(),
            destination_id: "inference:usage-reconciliation".to_string(),
            request_sha256: digest_json(&(
                "hepta.inference.usage-reconciliation.request.v1",
                &usage.request_id,
                &usage.thread_id,
                &usage.turn_id,
                &usage.model_provider,
            ))?,
            scope_sha256: digest_json(&(
                "hepta.inference.usage-reconciliation.scope.v1",
                record.request.worker_generation,
                &record.request.model,
            ))?,
            payload_sha256: digest_json(&(
                "hepta.inference.usage-reconciliation.payload.v1",
                usage.observed_output_tokens,
                &usage.evidence_digest,
            ))?,
        })
    }

    /// Consume independently signed final-use authority and durably refine
    /// missing exact-turn usage in the canonical inference.control journal.
    pub fn reconcile_usage(
        &self,
        control: &mut DurableInferenceControl,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        usage: NativeUsageReconciliation,
    ) -> WorkerPortResult<()> {
        let binding = self.usage_reconciliation_binding(control, &usage)?;
        let token = authority.claim(signed, &binding)?;
        authority.with_verified_use(token, &binding, || {
            control.reconcile_native_usage(
                &usage.request_id,
                usage.observed_output_tokens,
                usage.evidence_digest.clone(),
            )
        })??;
        Ok(())
    }

    /// Consume already-established authority and execute one exact request.
    ///
    /// The worker claims the signed final-use grant only for a fresh Reserved
    /// request immediately before durable dispatch intent. Restart recovery
    /// never claims a second grant and never submits a replacement turn.
    pub async fn execute(
        &self,
        control: &mut DurableInferenceControl,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        admission: NativeAdmission,
        prompt: String,
        cancellation: &CancellationToken,
    ) -> WorkerPortResult<NativeRunOutput> {
        self.driver
            .run_authorized(control, authority, signed, admission, prompt, cancellation)
            .await
    }
}

fn validate_digest(value: &str) -> WorkerPortResult<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("usage evidence digest must be canonical lowercase sha256".into());
    }
    Ok(())
}

fn digest_json(value: &impl serde::Serialize) -> WorkerPortResult<[u8; 32]> {
    Ok(Sha256::digest(serde_json::to_vec(value)?).into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::AgentId;
    use std::path::PathBuf;
    use std::time::Duration;

    fn port() -> NativeWorkerPort {
        NativeWorkerPort::new(NativeWorkerConfig {
            agentd_socket: PathBuf::from("/tmp/hepta-agentd-test.sock"),
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
                .expect("fixed agent id"),
            generation: 7,
            model: "model.exact".to_string(),
            timeout: Duration::from_secs(30),
        })
        .expect("port")
    }

    #[cfg(unix)]
    #[test]
    fn independently_signed_usage_reconciliation_is_durable_and_single_use() {
        use codex_hepta_contracts::FinalUseGrant;
        use codex_hepta_contracts::FinalUseRevocations;
        use codex_hepta_infer_core::durable_control::native::NativeDispatch;
        use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
        use codex_hepta_infer_core::durable_control::native::NativeRequest;
        use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
        use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
        use ed25519_dalek::Signer as _;
        use ed25519_dalek::SigningKey;
        use std::collections::BTreeSet;
        use std::os::unix::fs::PermissionsExt;
        use std::time::SystemTime;
        use std::time::UNIX_EPOCH;

        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-worker-port-usage-{}-{nonce}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let mut permissions = std::fs::metadata(&root).unwrap().permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&root, permissions).unwrap();

        let journal = root.join("inference.journal");
        let mut control = DurableInferenceControl::open(&journal, 8).unwrap();
        let request_id = "request.usage.1".to_string();
        control
            .reserve_native(
                NativeRequest {
                    request_id: request_id.clone(),
                    principal_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string(),
                    worker_generation: 7,
                    model: "model.exact".to_string(),
                    payload_digest: "a".repeat(64),
                },
                1,
            )
            .unwrap();
        control
            .dispatch_native(
                &request_id,
                NativeDispatch {
                    thread_id: "thread-usage-1".to_string(),
                    model_provider: "provider.exact".to_string(),
                    context_digest: "b".repeat(64),
                    client_user_message_id: Some(request_id.clone()),
                    input_payload_sha256: Some("c".repeat(64)),
                },
            )
            .unwrap();
        control
            .native_started(&request_id, "turn-usage-1".to_string())
            .unwrap();
        control
            .settle_native(
                &request_id,
                NativeRunOutput {
                    thread_id: "thread-usage-1".to_string(),
                    turn_id: "turn-usage-1".to_string(),
                    model: "model.exact".to_string(),
                    model_provider: "provider.exact".to_string(),
                    status: NativeRunStatus::Completed,
                    output: "terminal".to_string(),
                    observed_output_tokens: None,
                    terminal_observed: true,
                    stop_reason: None,
                    owner_authority: NativeOwnerAuthority::ObservedReady,
                },
            )
            .unwrap();

        let usage = NativeUsageReconciliation {
            request_id: request_id.clone(),
            thread_id: "thread-usage-1".to_string(),
            turn_id: "turn-usage-1".to_string(),
            model_provider: "provider.exact".to_string(),
            observed_output_tokens: 41,
            evidence_digest: "d".repeat(64),
        };
        let port = port();
        let binding = port
            .usage_reconciliation_binding(&control, &usage)
            .expect("usage binding");
        assert_eq!(
            binding.destination_id,
            "inference:usage-reconciliation"
        );

        let signing = SigningKey::from_bytes(&[23_u8; 32]);
        let authority_dir = root.join("usage-authority");
        std::fs::create_dir_all(&authority_dir).unwrap();
        let mut permissions = std::fs::metadata(&authority_dir).unwrap().permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&authority_dir, permissions).unwrap();
        let authority = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "usage-authority".to_string(),
            signing.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .unwrap();
        let now_ms = u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_millis(),
        )
        .unwrap();
        let proposal = FinalUseGrant {
            schema_version: 1,
            signer_id: "usage-authority".to_string(),
            authority_epoch: 9,
            grant_id: "usage-proof.1".to_string(),
            nonce: [17_u8; 32],
            binding,
            not_before_unix_ms: now_ms.saturating_sub(1000),
            expires_at_unix_ms: now_ms + 60_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signing
                .sign(&proposal.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant: proposal,
        };
        port.reconcile_usage(&mut control, &authority, &signed, usage)
            .expect("signed usage reconciliation");
        let expected = control.native_record(&request_id).unwrap().clone();
        assert_eq!(expected.usage_evidence_digest, Some("d".repeat(64)));
        assert_eq!(
            expected
                .observation
                .as_ref()
                .unwrap()
                .observed_output_tokens,
            Some(41)
        );

        assert!(
            port.reconcile_usage(
                &mut control,
                &authority,
                &signed,
                NativeUsageReconciliation {
                    request_id: request_id.clone(),
                    thread_id: "thread-usage-1".to_string(),
                    turn_id: "turn-usage-1".to_string(),
                    model_provider: "provider.exact".to_string(),
                    observed_output_tokens: 41,
                    evidence_digest: "d".repeat(64),
                },
            )
            .is_err(),
            "signed nonce must not be reusable"
        );
        drop(control);
        drop(authority);
        let reopened = DurableInferenceControl::open(&journal, 8).unwrap();
        assert_eq!(reopened.native_record(&request_id), Some(&expected));
        drop(reopened);
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn final_use_binding_is_exact_stable_and_payload_sensitive() {
        let port = port();
        let first = port
            .final_use_binding("request.1", "hello")
            .expect("first binding");
        let same = port
            .final_use_binding("request.1", "hello")
            .expect("same binding");
        let changed = port
            .final_use_binding("request.1", "hello!")
            .expect("changed binding");

        assert_eq!(first, same);
        assert_eq!(first.subject_id, "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12");
        assert_eq!(first.destination_id, "provider:codex-app-server");
        assert_ne!(first.request_sha256, [0; 32]);
        assert_ne!(first.scope_sha256, [0; 32]);
        assert_ne!(first.payload_sha256, [0; 32]);
        assert_ne!(first.payload_sha256, changed.payload_sha256);
        assert_ne!(first.request_sha256, changed.request_sha256);
        assert_eq!(first.scope_sha256, changed.scope_sha256);
    }
}
