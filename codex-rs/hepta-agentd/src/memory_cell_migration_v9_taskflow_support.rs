//! Qualification uses explicit fixture authority keys; production callers must
//! supply their own current grant/fence. This is the actual durable owner API.

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_paths::HeptaAgentLayout;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::process_support::DESTINATION;
use crate::MemoryCellMigrationProviderV9;

pub(super) struct Effect {
    pub store: AutomationStore,
    pub fence: TaskFlowFence,
    pub intent: AuthorizedEffectIntent,
    record_command_id: String,
    authority: FinalUseAuthority,
    pub signed: SignedFinalUseGrant,
    pub binding: FinalUseBinding,
    pub directory: tempfile::TempDir,
}

pub(super) fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis()
        .try_into()
        .expect("bounded clock")
}

impl Effect {
    pub async fn prepare(layout: &HeptaAgentLayout, run: &str, payload: &[u8]) -> Self {
        let store = AutomationStore::open(layout)
            .await
            .expect("real TaskFlow store");
        let fence = TaskFlowFence::new(
            layout.agent_id().clone(),
            "memory-migration-owner",
            1,
            1,
            "memory-v9-fence",
        )
        .expect("owner fence");
        let definition = TaskFlowDefinition::new(
            "memory-migration-v9",
            1,
            "transfer",
            vec![
                TaskFlowNodeSpec::effect("transfer", "memory.migrate", "memory-migration-v9"),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("transfer", "success"),
                TaskFlowEdgeSpec::new("transfer", "failure"),
            ],
            vec!["memory.migrate".into()],
            Sha256Digest::for_bytes(b"memory-migration-v9-policy"),
        )
        .expect("effect graph");
        store
            .register_taskflow_definition(&definition, &fence, now_ms())
            .await
            .expect("registered graph");
        store
            .create_taskflow_run(
                run,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "migration-thread",
                now_ms(),
            )
            .await
            .expect("run");
        let claimed = store
            .claim_taskflow_run(run, &fence, now_ms(), 240_000)
            .await
            .expect("claim run");
        store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    run,
                    format!("{run}:start"),
                    fence.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    now_ms(),
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        let intent = AuthorizedEffectIntent {
            run_id: run.into(),
            step_id: "transfer".into(),
            attempt: 1,
            operation_id: "memory.migrate".into(),
            subject_id: layout.agent_id().as_str().into(),
            destination_id: DESTINATION.into(),
            payload_digest: Sha256Digest::for_bytes(payload),
            final_use_scope_digest: Sha256Digest::for_bytes(b"memory-migration-v9-exact-image"),
            policy_generation: 1,
            expected_predecessor_digest: None,
            dependencies: Vec::new(),
            compensation_for: None,
        };
        let digest = intent.digest().expect("effect digest");
        // TaskFlow command IDs are unique across this owner, not just one run.
        // Bind the observation to the exact intent and retain it across retries.
        let record_command_id = format!("memory-migration-v9:record:{}", digest.as_str());
        store
            .prepare_taskflow_step(
                run,
                &intent.step_id,
                1,
                &fence,
                &digest,
                &intent.payload_digest,
                &format!("{run}:prepare"),
                now_ms(),
            )
            .await
            .expect("prepare durable step");
        store
            .claim_taskflow_step(
                run,
                &intent.step_id,
                1,
                &fence,
                &digest,
                &intent.payload_digest,
                &format!("{run}:claim"),
                now_ms(),
            )
            .await
            .expect("claim durable step");
        let binding = intent.final_use_binding().expect("owner-derived binding");
        let issuer = SigningKey::from_bytes(&[83; 32]);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "memory-migration-security-fixture".into(),
            authority_epoch: 1,
            grant_id: format!("{run}:grant"),
            nonce: *codex_hepta_types::Digest32::of_bytes(
                format!("{run}:{}:{}", std::process::id(), now_ms()).as_bytes(),
            )
            .as_array(),
            binding: binding.clone(),
            not_before_unix_ms: now_ms().saturating_sub(1_000),
            expires_at_unix_ms: now_ms() + 120_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().expect("grant bytes"))
            .to_bytes()
            .to_vec();
        let directory = tempfile::tempdir().expect("authority root");
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private authority root");
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "memory-migration-security-fixture".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("durable final-use authority");
        Self {
            store,
            fence,
            intent,
            record_command_id,
            authority,
            signed: SignedFinalUseGrant { grant, signature },
            binding,
            directory,
        }
    }

    pub async fn reject_invalid_grant(
        &self,
        driver: &mut ProviderEffectTaskFlowDriver<MemoryCellMigrationProviderV9>,
        payload: &[u8],
    ) {
        let mut invalid = self.signed.clone();
        invalid.signature[0] ^= 1;
        let before = driver.adapter().traffic().expect("traffic");
        assert!(
            self.store
                .execute_authorized_taskflow_effect_async(
                    &self.authority,
                    driver,
                    &self.intent,
                    payload,
                    &self.fence,
                    &invalid,
                    &self.binding,
                    &self.record_command_id,
                    now_ms()
                )
                .await
                .is_err()
        );
        assert_eq!(
            before,
            driver
                .adapter()
                .traffic()
                .expect("no provider contact without valid authority")
        );
    }

    pub async fn execute<D: AsyncAuthorizedEffectDriver>(
        &self,
        driver: &mut D,
        payload: &[u8],
    ) -> TaskFlowStepReceipt {
        self.store
            .execute_authorized_taskflow_effect_async(
                &self.authority,
                driver,
                &self.intent,
                payload,
                &self.fence,
                &self.signed,
                &self.binding,
                &self.record_command_id,
                now_ms(),
            )
            .await
            .expect("authorized transfer observation")
    }

    pub async fn reject_ambiguous_retry(
        &self,
        driver: &mut ProviderEffectTaskFlowDriver<MemoryCellMigrationProviderV9>,
        payload: &[u8],
    ) {
        let before = driver.adapter().traffic().expect("traffic");
        assert!(
            self.store
                .execute_authorized_taskflow_effect_async(
                    &self.authority,
                    driver,
                    &self.intent,
                    payload,
                    &self.fence,
                    &self.signed,
                    &self.binding,
                    &self.record_command_id,
                    now_ms()
                )
                .await
                .is_err()
        );
        assert_eq!(
            before,
            driver
                .adapter()
                .traffic()
                .expect("uncertainty never blindly redispatches")
        );
    }

    pub async fn recover(
        &self,
        driver: &ProviderEffectTaskFlowDriver<MemoryCellMigrationProviderV9>,
    ) -> AuthorizedEffectRecoveryResult {
        let pending = self
            .store
            .authorized_taskflow_effect_attempt(&self.intent.run_id, &self.intent.step_id, 1)
            .await
            .expect("pending lookup")
            .expect("durable attempt");
        let AuthorizedProviderEffectLookup::Observed(receipt) = driver.lookup(&pending).await
        else {
            panic!("provider-owned completion required")
        };
        self.store
            .recover_authorized_taskflow_effect(
                &self.intent.run_id,
                &self.intent.step_id,
                1,
                &self.fence,
                AuthorizedEffectRecovery::Observed(receipt),
                now_ms(),
            )
            .await
            .expect("durable TaskFlow reconciliation")
    }
}

#[cfg(test)]
#[path = "memory_cell_migration_v9_taskflow_tests.rs"]
mod tests;
