//! Versioned full-packet transport into the existing authorized effect owner.
//! The legacy inline route retains its original size and authentication checks.

use super::*;
use codex_hepta_contracts::FinalUseAuthenticationProfile;

pub(super) enum EffectWire<'a> {
    Inline(&'a [u8]),
    Packet(&'a crate::control_packet::AdmittedEffectPacketV1),
}

impl AgentdAutomationEffectHost {
    pub(crate) fn supports_packet_v1(&self) -> bool {
        matches!(&self.adapter, AgentdProviderEffectAdapter::Pon(_))
            && self.pq.is_some()
            && self.authority.authentication_profile() == FinalUseAuthenticationProfile::MlDsa65V2
    }

    pub(crate) async fn execute_packet_v1(
        &self,
        store: &AutomationStore,
        intent: &AuthorizedEffectIntent,
        packet: &crate::control_packet::AdmittedEffectPacketV1,
        signed_grant: &SignedFinalUseGrant,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AgentdError> {
        self.execute_wire(
            store,
            intent,
            EffectWire::Packet(packet),
            signed_grant,
            command_id,
            now_ms,
        )
        .await
    }
}

impl PonLocalProviderEffectAdapter {
    pub(super) fn invoke_until(
        &self,
        operation: &str,
        wire_payload: &[u8],
        deadline: Instant,
        execution: Option<&crate::NeuralCognitiveExecutionV1>,
    ) -> PonInvocation {
        if wire_payload.len() > 1024 * 1024 || self.validate_paths().is_err() {
            return PonInvocation::BeforeStart;
        }
        let Ok(executable) = pon_executable::PinnedExecutable::prepare(
            &self.binary,
            self.binary_sha256.as_str(),
            deadline,
        ) else {
            return PonInvocation::BeforeStart;
        };
        if execution.is_some_and(|execution| execution.check().is_err()) {
            return PonInvocation::BeforeStart;
        }
        let Ok(runtime) = tokio::runtime::Handle::try_current() else {
            return PonInvocation::BeforeStart;
        };
        // Provider methods enter here via their existing spawn_blocking scope.
        // Hash/path verification is not preemptible, but no child may start if
        // it consumed the original deadline. The entire pipe exchange uses the
        // same deadline; stdout and stderr limits are equally authoritative.
        let command = self.command(operation, executable.path());
        let outcome = runtime.block_on(async {
            match execution {
                Some(execution) => {
                    pon_process::run_packet(
                        command,
                        wire_payload,
                        deadline,
                        MAX_PON_PROCESS_OUTPUT_BYTES,
                        execution,
                    )
                    .await
                }
                None => {
                    pon_process::run(
                        command,
                        wire_payload,
                        deadline,
                        MAX_PON_PROCESS_OUTPUT_BYTES,
                    )
                    .await
                }
            }
        });
        match outcome {
            pon_process::Outcome::BeforeStart => PonInvocation::BeforeStart,
            pon_process::Outcome::Unknown => PonInvocation::Unknown,
            pon_process::Outcome::Complete(stdout) => match serde_json::from_slice(&stdout) {
                Ok(value) => PonInvocation::Value(value),
                Err(_) => PonInvocation::Unknown,
            },
        }
    }

    pub(super) async fn dispatch_packet(
        &self,
        intent: ProviderEffectIntent,
        wire_payload: Vec<u8>,
        execution: crate::NeuralCognitiveExecutionV1,
    ) -> ProviderEffectDispatch {
        if wire_payload.is_empty()
            || wire_payload.len() > crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES
        {
            return ProviderEffectDispatch::NotDispatched {
                reason_code: "pon_packet_v1_length_invalid".to_string(),
            };
        }
        let adapter = self.clone();
        tokio::task::spawn_blocking(move || {
            if execution.check().is_err()
                || Sha256Digest::for_bytes(&wire_payload) != intent.payload_sha256
            {
                return ProviderEffectDispatch::NotDispatched {
                    reason_code: "pon_packet_execution_expired_or_binding_invalid".to_string(),
                };
            }
            let Some(provider_deadline) = Instant::now().checked_add(adapter.timeout) else {
                return ProviderEffectDispatch::NotDispatched {
                    reason_code: "pon_packet_deadline_invalid".to_string(),
                };
            };
            let outcome = adapter.invoke_until(
                "submit",
                &wire_payload,
                provider_deadline.min(execution.deadline()),
                Some(&execution),
            );
            Self::dispatch_outcome(intent, outcome)
        })
        .await
        .unwrap_or(ProviderEffectDispatch::Unknown)
    }
}
