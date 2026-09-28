#!/usr/bin/env python3
"""One-shot source authoring, kept ONLY on the operations branch.

This program is never copied to the product branch or run by qualification.
It edits reviewed, exact-anchored source before a conventional source commit.
"""
from pathlib import Path
import hashlib
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
EXPECTED = "6c83671014ee5f65e6e6a61f4df5d714d904c0be"
if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != EXPECTED:
    raise SystemExit("authoring source changed; refusing to apply")

def replace(path, old, new):
    target = root / path
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one reviewed anchor, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1))

runtime = "codex-rs/hepta-agentd/src/prompt_runtime.rs"
raw = (root / runtime).read_bytes()
if hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != "f56d601244a7f4787675e2465ff7d34491c80d1e":
    raise SystemExit("runtime blob drifted")
replace(runtime, "use crate::prompt_final_use::PromptFinalUseLeaseError;", """use crate::prompt_final_use::PromptFinalUseBoundaryV1;
use crate::prompt_final_use::PromptFinalUseLeaseError;
use crate::prompt_final_use::PromptFinalUseMetrics;
use crate::prompt_final_use::PromptFinalUseValidator;""")
replace(runtime, "    final_use: Arc<PromptFinalUseLeaseStore>,", """    final_use: Arc<PromptFinalUseLeaseStore>,
    final_use_validator: PromptFinalUseValidator,""")
replace(runtime, "            final_use: Arc::new(final_use),", """            final_use: Arc::new(final_use),
            final_use_validator: PromptFinalUseValidator::default(),""")
replace(runtime, "    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {", """    pub fn final_use_metrics(&self) -> PromptFinalUseMetrics {
        self.final_use_validator.metrics()
    }

    #[must_use]
    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {""")
replace(runtime, """        lease.validate_shape().map_err(final_use_lease_host_error)?;
        if lease.compilation_id != attachment.compilation_id
            || lease.context_attachment_digest != attachment.context_attachment_digest
            || lease.context_payload_digest != attachment.context_payload_digest
        {
            return Err(PromptRuntimeHostError::new(
                "agentd_prompt_final_use_binding_mismatch",
                "staged prompt context does not match its durable final-use lease",
            ));
        }
        Ok(Some(attachment))""", """        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        self.final_use_validator.validate(
            &lease,
            &registry,
            &PromptFinalUseBoundaryV1 {
                compilation_id: &attachment.compilation_id,
                context_attachment_digest: attachment.context_attachment_digest,
                context_payload_digest: attachment.context_payload_digest,
                now_unix_ms: prompt_host_now_unix_ms()?,
            },
        ).map_err(final_use_lease_host_error)?;
        Ok(Some(attachment))""")
replace(runtime, """        if lease.compilation_id != record.compilation_id
            || lease.context_attachment_digest != record.context_attachment_digest
            || lease.context_payload_digest != record.context_payload_digest
        {
            return Err(PromptRuntimeHostError::new(
                "agentd_prompt_final_use_binding_mismatch",
                "provider dispatch does not match its prompt final-use lease",
            ));
        }
        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        lease
            .validate_current(&registry, record.dispatched_unix_ms)
            .map_err(final_use_lease_host_error)?;
        self.runtime.record_dispatch(record)""", """        let registry = self.registry.lock().map_err(|_| {
            PromptRuntimeHostError::new(
                "agentd_prompt_registry_state_poisoned",
                "prompt registry owner lock is poisoned",
            )
        })?;
        let now_unix_ms = prompt_host_now_unix_ms()?;
        if record.dispatched_unix_ms > now_unix_ms
            || record.dispatched_unix_ms < lease.issued_unix_ms
        {
            return Err(final_use_lease_host_error(PromptFinalUseLeaseError::Expired));
        }
        self.final_use_validator.validate(
            &lease,
            &registry,
            &PromptFinalUseBoundaryV1 {
                compilation_id: &record.compilation_id,
                context_attachment_digest: record.context_attachment_digest,
                context_payload_digest: record.context_payload_digest,
                now_unix_ms,
            },
        ).map_err(final_use_lease_host_error)?;
        // Keep the owner guard through the durable dispatch claim. The provider
        // terminal is still a separate observed fact, not a fabricated success.
        self.runtime.record_dispatch(record)""")
replace(runtime, "fn final_use_store_host_error(error:", """fn prompt_host_now_unix_ms() -> Result<u64, PromptRuntimeHostError> {
    let elapsed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| PromptRuntimeHostError::new("prompt_final_use_clock_unavailable", "trusted host clock is unavailable"))?;
    u64::try_from(elapsed.as_millis()).map_err(|_| {
        PromptRuntimeHostError::new("prompt_final_use_clock_unavailable", "trusted host clock is out of range")
    })
}

fn final_use_store_host_error(error:""")
replace(runtime,
    '    PromptRuntimeHostError::new("agentd_prompt_final_use_lease_error", error.to_string())',
    '    PromptRuntimeHostError::new(error.code(), error.to_string())')

# A cached attachment is never current-use evidence. Reconsult the same host;
# never silently replace an already injected attachment with a different one.
extension = "codex-rs/ext/hepta-prompt/src/lib.rs"
replace(extension, """        if let Some(value) = resolved.as_ref() {
            return value.clone();
        }
        let value = match self""", """        let previous = resolved.as_ref().cloned();
        if let Some(value) = previous.as_ref()
            && !matches!(value, ResolvedAttachment::Ready(_))
        {
            return value.clone();
        }
        let value = match self""")
replace(extension, """        *resolved = Some(value.clone());
        value""", """        let value = match (previous, value) {
            (Some(ResolvedAttachment::Ready(previous)), ResolvedAttachment::Ready(current))
                if previous != current => ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                    "prompt_runtime_cached_binding_changed",
                    "an injected attachment changed; recompile in a fresh turn",
                )),
            (Some(ResolvedAttachment::Ready(_)), ResolvedAttachment::None) =>
                ResolvedAttachment::Failed(PromptRuntimeHostError::new(
                    "prompt_runtime_cached_attachment_removed",
                    "the owner no longer exposes the injected attachment",
                )),
            (_, value) => value,
        };
        *resolved = Some(value.clone());
        value""")
ext_tests = "codex-rs/ext/hepta-prompt/src/lib_tests.rs"
replace(ext_tests, """    PromptRuntimeHost::new(
        "prompt-runtime-test",
        |_request| {
            let attachment = attachment();""", """    let prepared_attachment = attachment();
    PromptRuntimeHost::new(
        "prompt-runtime-test",
        move |_request| {
            let attachment = prepared_attachment.clone();""")
with (root / ext_tests).open("a") as output:
    output.write(r'''

#[tokio::test]
async fn cached_prompt_revalidates_owner_withdrawal_before_provider_begin() {
    let withdrawn = Arc::new(AtomicBool::new(false));
    let dispatch_count = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let prepared = attachment();
    let flag = Arc::clone(&withdrawn);
    let counter = Arc::clone(&dispatch_count);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-cache-withdrawal",
        move |_| {
            let result = if flag.load(Ordering::Acquire) {
                Err(PromptRuntimeHostError::new("prompt_final_use_revoked", "selection revoked"))
            } else {
                Ok(Some(prepared.clone()))
            };
            Box::pin(std::future::ready(result))
        },
        move |_| {
            counter.fetch_add(1, Ordering::Relaxed);
            Box::pin(std::future::ready(Ok(())))
        },
        |_| Box::pin(std::future::ready(Ok(()))),
    ).unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id = ThreadId::from_string(thread_store.level_id())
        .unwrap_or_else(|error| panic!("thread: {error}"));
    assert_eq!(extension.contribute_turn_context(TurnContextContributionInput {
        thread_id, turn_id: turn_store.level_id(), session_store: &session_store,
        thread_store: &thread_store, turn_store: &turn_store, model_context_window: Some(128_000),
    }).await.len(), 1);
    withdrawn.store(true, Ordering::Release);
    let provider_config = provider_digest("config");
    let endpoint = provider_digest("endpoint");
    let logical = provider_digest("logical");
    let wire = provider_digest("wire");
    let result = extension.begin(ModelProviderInvocationInput {
        schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
        session_store: &session_store, thread_store: &thread_store, turn_store: &turn_store,
        attempt_id: "provider-attempt:cache", request_binding_id: "provider-request:cache",
        thread_id: thread_store.level_id(), turn_id: turn_store.level_id(),
        request_kind: ModelProviderRequestKind::Turn, provider_id: "test-provider",
        provider_config_sha256: &provider_config, model: "gpt-test", transport: ModelProviderTransport::Http,
        endpoint_sha256: &endpoint, logical_request_sha256: &logical, wire_semantic_sha256: &wire,
        ephemeral_input_sha256: None, ephemeral_input_witness_sha256: None,
        previous_response_id_sha256: None, generate: true,
    }).await;
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("withdrawn cached context must block provider begin"),
    };
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    assert_eq!(dispatch_count.load(Ordering::Relaxed), 0);
}

#[tokio::test]
async fn cached_prompt_never_silently_switches_injected_payload() {
    let changed = Arc::new(AtomicBool::new(false));
    let initial = attachment();
    let mut replacement = initial.clone();
    replacement.developer_fragments = vec![PromptRuntimeDeveloperFragmentV1::new("different reviewed material")
        .unwrap_or_else(|error| panic!("fragment: {error}"))];
    replacement.source_binding_digest = replacement.compute_binding_digest();
    let flag = Arc::clone(&changed);
    let host = PromptRuntimeHost::new("prompt-runtime-cache-drift", move |_| {
        let value = if flag.load(Ordering::Acquire) { replacement.clone() } else { initial.clone() };
        Box::pin(std::future::ready(Ok(Some(value))))
    }, |_| Box::pin(std::future::ready(Ok(()))), |_| Box::pin(std::future::ready(Ok(()))))
        .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (_, thread_store, turn_store) = stores();
    assert!(matches!(extension.resolve(thread_store.level_id().to_owned(), turn_store.level_id().to_owned(), None, &turn_store).await, ResolvedAttachment::Ready(_)));
    changed.store(true, Ordering::Release);
    let result = extension.resolve(thread_store.level_id().to_owned(), turn_store.level_id().to_owned(), None, &turn_store).await;
    match result {
        ResolvedAttachment::Failed(error) => assert_eq!(error.reason_code(), "prompt_runtime_cached_binding_changed"),
        _ => panic!("cached identity drift must fail closed"),
    }
}
''')

# Strengthen the existing authenticated, same-owner fixture instead of adding a
# second fake registry or bypassing the production preparation path.
tests = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
replace(tests, '    let logical_now = 100_u64;', '    let logical_now = wall_now;')
replace(tests, '    let disposition = pipeline\n        .compile_and_stage(', '    let compile_started = std::time::Instant::now();\n    let disposition = pipeline\n        .compile_and_stage(')
replace(tests, """    assert_eq!(disposition, PromptRuntimeStageDisposition::Inserted);

    let runtime = pipeline.runtime_owner();
    let staged = runtime
        .prepare(PromptRuntimePrepareRequest {""", """    assert_eq!(disposition, PromptRuntimeStageDisposition::Inserted);
    let compile_stage_nanos = compile_started.elapsed().as_nanos();

    let prepare_started = std::time::Instant::now();
    let staged = pipeline
        .prepare_final_use(PromptRuntimePrepareRequest {""")
replace(tests, """    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
}""", r'''    assert_eq!(staged.developer_fragments[0].text.as_bytes(), payload);
    let prepare_nanos = prepare_started.elapsed().as_nanos();
    let factor_id = id("factor:agentd-product");
    let actor = id("operator:agentd-revoke");
    let scope = digest("revoke-scope:agentd-product");
    let reason = digest("revoke-reason:agentd-product");
    let cutoff = prompt_host_now_unix_ms().unwrap_or_else(|error| panic!("clock: {error}"));
    {
        let mut registry = pipeline.registry.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let factor = registry.registry().unwrap_or_else(|error| panic!("registry: {error}"))
            .factor(&factor_id).cloned().unwrap_or_else(|| panic!("factor"));
        let binding = codex_hepta_prompt_registry::final_use_revoke_binding(&factor, &actor, scope, reason, cutoff)
            .unwrap_or_else(|error| panic!("revoke binding: {error}"));
        let grant = FinalUseGrant {
            schema_version: 1, signer_id: "review-authority:agentd-prompt".to_owned(),
            authority_epoch: 1, grant_id: "grant:agentd-prompt-revoke".to_owned(), nonce: [64; 32],
            binding, not_before_unix_ms: wall_now.saturating_sub(1000), expires_at_unix_ms: wall_now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signing_key.sign(&grant.signing_bytes().unwrap_or_else(|error| panic!("sign: {error}")))
                .to_bytes().to_vec(), grant,
        };
        registry.revoke_factor_final_use(&authority, &signed, &factor_id, &actor, scope, reason, cutoff)
            .unwrap_or_else(|error| panic!("revoke: {error}"));
    }
    let request = PromptRuntimePrepareRequest {
        thread_id: "thread:product".to_owned(), turn_id: "turn:product".to_owned(), model_context_window: Some(128),
    };
    let error = pipeline.prepare_final_use(request.clone()).unwrap_err();
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    let mut attempt = dispatch(&staged, "thread:product", "turn:product", "attempt:revoked", "request:revoked", digest("provider-request:revoked"));
    attempt.dispatched_unix_ms = cutoff;
    let error = pipeline.record_dispatch_final_use(attempt.clone()).unwrap_err();
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    assert!(pipeline.runtime.dispatch_record("attempt:revoked").unwrap_or_else(|error| panic!("dispatch: {error}")).is_none());
    let metrics = pipeline.final_use_metrics();
    assert!(metrics.withdrawn >= 2);
    println!("{}", serde_json::json!({
        "schema": "hepta.prompt-registry.pipeline-profile.v1",
        "realizations": 1, "compileAndStageNanos": compile_stage_nanos,
        "prepareCurrentUseNanos": prepare_nanos, "checks": metrics.checked,
        "currentUseTotalNanos": metrics.total_nanos, "currentUseMaximumNanos": metrics.maximum_nanos,
        "providerNetworkUsed": false, "productionSla": false,
    }));
    drop(pipeline);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(&registry_root, &runtime_root, 64)
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    assert_eq!(reopened.prepare_final_use(request).unwrap_err().reason_code(), "prompt_final_use_revoked");
    assert_eq!(reopened.record_dispatch_final_use(attempt).unwrap_err().reason_code(), "prompt_final_use_revoked");
    assert!(reopened.runtime.dispatch_record("attempt:revoked").unwrap_or_else(|error| panic!("dispatch: {error}")).is_none());
}''')
# Avoid introducing unwrap_err into a workspace that bans unwrap-style methods.
replace_text = (root / tests).read_text()
replace_text = replace_text.replace('.unwrap_err()', '.err().unwrap_or_else(|| panic!("expected rejection"))')
(root / tests).write_text(replace_text)
with (root / tests).open("a") as output:
    output.write('''\n#[test]\n#[ignore = "qualification pipeline latency profile; no production provider effect"]\nfn operational_pipeline_compile_stage_final_use_profile() {\n    for _ in 0..31 {\n        named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host();\n    }\n}\n''')

# Strict checkpoints cannot contain unselected bytes. Verification rejects tails
# rather than silently truncating; normal owner recovery remains a separate API.
payloads = "codex-rs/hepta-prompt-registry/src/durable_payloads.rs"
replace(payloads, 'pub(super) const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;', '''pub(super) const MAX_PAYLOAD_BYTES: u64 = 32 * 1024 * 1024;
pub(super) const MAX_PHYSICAL_PAYLOAD_FILE_BYTES: u64 = MAX_PAYLOAD_BYTES + MAGIC.len() as u64;''')
replace(payloads, '    pub fn is_initialized(&self) -> bool {', '''    pub fn selected_file_bytes(&self) -> u64 {
        self.committed_end
    }

    pub fn is_initialized(&self) -> bool {''')
maintenance = "codex-rs/hepta-prompt-registry/src/durable_maintenance.rs"
replace(maintenance, '    pub maximum_payload_bytes: u64,', '    pub maximum_payload_bytes: u64,\n    pub maximum_payload_file_bytes: u64,')
replace(maintenance, '            maximum_payload_bytes: payloads::MAX_PAYLOAD_BYTES,', '            maximum_payload_bytes: payloads::MAX_PAYLOAD_BYTES,\n            maximum_payload_file_bytes: payloads::MAX_PHYSICAL_PAYLOAD_FILE_BYTES,')
replace(maintenance, 'basis_points(physical_payload_file_bytes, quota.maximum_payload_bytes)', 'basis_points(physical_payload_file_bytes, quota.maximum_payload_file_bytes)')
replace(maintenance, 'remaining_payload_bytes: quota.maximum_payload_bytes.saturating_sub(physical_payload_file_bytes)', 'remaining_payload_bytes: quota.maximum_payload_file_bytes.saturating_sub(physical_payload_file_bytes)')
replace(maintenance, '    let result = (|| {\n        let write_started', '    let result: Result<(u128, u128, u128), PromptRegistryMaintenanceError> = (|| {\n        let write_started')
replace(maintenance, '    let registry = restore_v4(stored, maximum_records)?;', '''    let actual_payload_bytes = open_private(&root, payloads::FILE_NAME, Access::Read)?
        .metadata().map_err(|_| DurableRegistryError::Unavailable)?.len();
    if actual_payload_bytes != payloads.selected_file_bytes() {
        return Err(PromptRegistryMaintenanceError::CheckpointVerificationMismatch);
    }
    let registry = restore_v4(stored, maximum_records)?;''')
maintenance_tests = "codex-rs/hepta-prompt-registry/src/durable_maintenance_tests.rs"
replace(maintenance_tests, 'metrics.remaining_payload_bytes + metrics.physical_payload_file_bytes, metrics.quota.maximum_payload_bytes', 'metrics.remaining_payload_bytes + metrics.physical_payload_file_bytes, metrics.quota.maximum_payload_file_bytes')
with (root / maintenance_tests).open("a") as output:
    output.write(r'''

#[test]
fn operational_restore_rejects_tail_without_repair_or_mutation() {
    let temporary = tempfile::tempdir().must("tempdir");
    let owner = seeded(&temporary.path().join("source"));
    let checkpoint = temporary.path().join("checkpoint");
    let receipt = owner.export_consistent_checkpoint(&checkpoint).must("export");
    let root = open_existing_directory(&checkpoint).must("directory");
    let mut file = open_private(&root, payloads::FILE_NAME, Access::Create).must("file");
    file.seek(SeekFrom::End(0)).must("seek");
    file.write_all(b"must-not-silently-trim").must("tail");
    file.sync_all().must("sync");
    drop(file);
    let before = std::fs::read(checkpoint.join(payloads::FILE_NAME)).must("before");
    assert!(DurablePromptRegistry::verify_restore_checkpoint(&checkpoint, 64, Some(receipt.checkpoint_revision), Some(receipt.checkpoint_registry_digest)).is_err());
    assert_eq!(std::fs::read(checkpoint.join(payloads::FILE_NAME)).must("after"), before);
}
''')
print("Reviewed prompt registry source edits applied; not a qualification result")
