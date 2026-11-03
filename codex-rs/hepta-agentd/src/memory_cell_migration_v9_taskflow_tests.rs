//! Exercise the real TaskFlow store and fixture authority with an in-process
//! provider. TCP/image and process-crash behavior remain in the process suite.

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::Effect;
use super::now_ms;

#[derive(Default)]
struct ObservedProvider {
    dispatched_runs: Vec<String>,
}

impl AsyncAuthorizedEffectDriver for ObservedProvider {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            self.dispatched_runs.push(request.intent.run_id.clone());
            Ok(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(
                    request.provider_intent.key.as_str().as_bytes(),
                ),
            })
        })
    }
}

#[tokio::test]
async fn memory_cell_v9_taskflow_distinct_runs_reopen_without_command_collision_or_redispatch() {
    let temporary = tempfile::tempdir().expect("owner root");
    let root = temporary
        .path()
        .canonicalize()
        .expect("canonical owner root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("owner registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let manifest = AgentManifest::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c91").expect("owner"),
        WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let layout = registry
        .register(manifest)
        .expect("registered owner")
        .layout;
    let payload = b"same immutable migration payload";
    let runs = ["migration-received", "migration-prepared"];
    let mut provider = ObservedProvider::default();
    let mut completed = Vec::new();

    for run in runs {
        let effect = Effect::prepare(&layout, run, payload).await;
        let before = provider.dispatched_runs.clone();
        let mut invalid = effect.signed.clone();
        invalid.signature[0] ^= 1;
        let denied = effect
            .store
            .execute_authorized_taskflow_effect_async(
                &effect.authority,
                &mut provider,
                &effect.intent,
                payload,
                &effect.fence,
                &invalid,
                &effect.binding,
                &effect.record_command_id,
                now_ms(),
            )
            .await;
        assert!(matches!(denied, Err(AuthorizedEffectError::FinalUse(_))));
        assert_eq!(provider.dispatched_runs, before);

        let receipt = effect.execute(&mut provider, payload).await;
        assert_eq!(
            receipt.observation,
            Some(TaskFlowStepObservation::Succeeded)
        );
        let before = provider.dispatched_runs.clone();
        let retried = effect
            .store
            .execute_authorized_taskflow_effect_async(
                &effect.authority,
                &mut provider,
                &effect.intent,
                payload,
                &effect.fence,
                &effect.signed,
                &effect.binding,
                &effect.record_command_id,
                now_ms(),
            )
            .await;
        assert!(retried.is_err(), "settled effects require receipt readback");
        assert_eq!(provider.dispatched_runs, before);
        effect.store.close().await;
        completed.push((effect.intent, effect.record_command_id, receipt));
    }

    assert_eq!(provider.dispatched_runs, runs.map(str::to_string).to_vec());
    let store = AutomationStore::open(&layout)
        .await
        .expect("reopened owner");
    for (index, (intent, command, receipt)) in completed.iter().enumerate() {
        let restored = store
            .read_authorized_taskflow_effect_receipt(intent, command)
            .await
            .expect("same command identity after owner restart");
        assert_eq!(restored.as_ref(), Some(receipt));
        let other_command = &completed[1 - index].1;
        assert!(
            store
                .read_authorized_taskflow_effect_receipt(intent, other_command)
                .await
                .is_err(),
            "another migration's command must not address this receipt"
        );
    }
    assert_eq!(provider.dispatched_runs, runs.map(str::to_string).to_vec());
    store.close().await;
}
