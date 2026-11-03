//! Real preparation and original-journal reopen tests. The RunStart fixture
//! below isolates storage/correlation; signed AuthBus admission is qualified
//! separately by the original Objective integration suite. No process-kill or
//! production Queue-origin claim is inferred from a cold coordinator here.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use anyhow::{Context as _, Result};
use codex_hepta_learning_ledger::{DurableRunStartJournal, RunPreparedRecordV1, RunStartAdmissionBindingV1,
    RunStartAuthenticationV1, RunStartObjectiveDispositionV1, RunStartRecordV1, RunStartRecovery, RunStartSnapshotV1};
use codex_hepta_objective::canonical_native_objective_semantic_bytes_v1;
use crate::canonical_queued_input::{CanonicalQueuedInputV1, CanonicalQueuedRunV1};

struct StoredFixture {
    _directory: tempfile::TempDir,
    journal_path: PathBuf,
    authority_path: PathBuf,
    original: RunStartRecordV1,
    encoded: RunPreparedRecordV1,
    expected: crate::RunReceipt,
    context: Vec<serde_json::Value>,
    composition: RuntimeComposition,
}

fn open_existing(path: &std::path::Path) -> Result<std::fs::File> {
    Ok(std::fs::OpenOptions::new().read(true).write(true).open(path)?)
}

impl StoredFixture {
    async fn create() -> Result<Self> {
        let directory = tempfile::tempdir()?;
        let authority_path = directory.path().join("authority.json");
        let journal_path = directory.path().join("original-journal.bin");
        let mut value = fixture();
        let bytes = b"The actual originally selected evidence bytes.".to_vec();
        let material = NativeContextMaterialV1 { item_id: id("retained.evidence"), source_digest: digest("original.source"), content: bytes.clone() };
        value.inputs.context_request.items = vec![ContextItem { item_id: material.item_id.clone(), role: ContextRole::UntrustedEvidence,
            content_digest: Digest32::of_bytes(&bytes), source_digest: material.source_digest, token_count: 4, contains_secret: false }];
        let objective = admit_and_compile_objective_v1(&value.inputs.objective_envelope, &value.inputs.objective_profile,
            &value.inputs.objective_context)?.compile_result
            .map_err(|error| anyhow::anyhow!("fixture compiled objective: {error:?}"))?;
        let (value, trust) = signed::sign_fixture(value);
        write_authority_file(&authority_path, &value.owners, value.request.snapshot.revocation_frontier_digest());
        let runner = AgentdIntelligenceProductRunnerV1::new(authority_path.clone(), authority_verifier())?.with_evaluation_trust(trust)?;
        let composition = RuntimeComposition { agent_id: "agent.product".to_owned(), supervisor_generation: 1, agentd_generation: 7,
            configuration_digest: digest("runtime-config").to_string(), ports_digest: digest("runtime-ports").to_string(), max_active_runs: 8 };
        let mut coordinator = AgentRunCoordinator::compose_runtime(composition.clone())
            .map_err(|error| anyhow::anyhow!("fixture coordinator: {error:?}"))?;
        let AgentdIntelligenceAdmittedOutcomeV1::Ready { prepared, run_receipt: expected } = runner
            .prepare_and_admit(&mut coordinator, value.request, value.inputs).await? else { anyhow::bail!("fixture did not complete real owners"); };
        let context = prepared.bind_native_context(vec![material.clone()])?.context().to_vec();
        let now = wall_clock_ms()?;
        let semantic = canonical_native_objective_semantic_bytes_v1(&objective.objective);
        let protocol = b"{\"fixture\":\"original objective protocol\"}".to_vec();
        let original = RunStartRecordV1 { authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.fixture"), key_epoch: 1, message_id: id("message.fixture"), sequence: 1,
            expires_at_ms: expected.deadline_ms + 10_000, scope_digest: digest("scope"), signed_body_digest: digest("signed.body"), signature: [7; 64],
        }, authenticated_payload: None, admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.fixture"), profile_revision: 1, profile_digest: digest("profile"), supplied_source_digest: digest("source"),
            intent_digest: digest("intent"), admitted_source_digest: digest("admitted"), observed_at_unix_micros: now * 1_000,
            deadline_unix_micros: (expected.deadline_ms + 5_000) * 1_000, authority: AuthorityPosture::DENY_ALL,
        }, disposition: RunStartObjectiveDispositionV1::Compiled, snapshot: RunStartSnapshotV1 {
            run_id: id(&expected.run_id), objective_digest: objective.objective.semantic_digest,
            hard_constraint_digest: objective.objective.hard_constraint_digest, preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model.tuple"), prompt_registry_digest: digest("prompt.registry"), artifact_set_digest: digest("ingress.artifact.set"),
            authority_epoch: expected.authority_epoch, generation: expected.generation, fence_digest: expected.fence_digest.parse()?,
        }, runtime_body_digest: digest("ingress.runtime.body"), objective_semantic_bytes: semantic,
            objective_function_v1_digest: Digest32::of_bytes(&protocol), objective_function_v1_bytes: protocol };
        let file = std::fs::OpenOptions::new().create_new(true).read(true).write(true).open(&journal_path)?;
        let mut journal = DurableRunStartJournal::create(file, digest("original.owner.scope"), /*max_records*/ 16)?;
        let start = journal.append(Digest32::ZERO, original.clone())?;
        let encoded = prepared.prepared_record(start.record_digest, &expected, vec![material])?;
        journal.append_prepared(journal.head_digest(), encoded.clone())?;
        // Return only durable files and comparison data. No Prepared, binding,
        // live coordinator, journal handle or evaluator trust survives.
        drop(journal); drop(coordinator); drop(prepared); drop(runner);
        Ok(Self { _directory: directory, journal_path, authority_path, original, encoded, expected, context, composition })
    }

    fn reopen(&self) -> Result<DurableRunStartJournal> {
        Ok(DurableRunStartJournal::recover(open_existing(&self.journal_path)?, digest("original.owner.scope"),
            /*max_records*/ 16, RunStartRecovery::Unacknowledged)?)
    }

    fn read_only_runner(&self) -> Result<AgentdIntelligenceProductRunnerV1> {
        // No ActivatedLearningTrust is installed: any attempt to rerun the
        // signed evaluation stage would fail instead of passing this recovery.
        Ok(AgentdIntelligenceProductRunnerV1::new(self.authority_path.clone(), authority_verifier())?)
    }

    fn correlation(&self) -> CanonicalQueuedInputV1 {
        CanonicalQueuedInputV1 { thread_id: "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_owned(),
            client_user_message_id: "fixture.original.client".to_owned(), input_payload_sha256: digest("fixture.input").to_string(),
            text: "The actual originally selected evidence bytes.".to_owned(), run_id: self.expected.run_id.clone(),
            signed_body_digest: self.original.authentication.signed_body_digest }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_journal_reopen_restores_exact_prepared_state_into_a_cold_coordinator() -> Result<()> {
    let fixture = StoredFixture::create().await?;
    let journal = fixture.reopen()?;
    let committed = journal.prepared(&fixture.original.snapshot.run_id)?.context("original prepared record")?;
    assert_eq!(committed.record(), &fixture.encoded);
    let runner = fixture.read_only_runner()?;
    let restored = runner.restore_canonical_handoff(&committed, fixture.expected.generation, wall_clock_ms()?)?;
    assert_eq!(restored.attached_run_receipt(), fixture.expected,
        "the read-only view must retain the exact original attachment revision and identity");
    assert_eq!(restored.context().context(), fixture.context);
    assert_ne!(restored.context().original_run_snapshot().body_digest, fixture.original.runtime_body_digest.to_string());
    assert_ne!(restored.context().original_run_snapshot().artifact_set_digest, fixture.original.snapshot.artifact_set_digest.to_string());
    let mut cold = AgentRunCoordinator::compose_runtime(fixture.composition.clone())
        .map_err(|error| anyhow::anyhow!("cold coordinator: {error:?}"))?;
    let queued = CanonicalQueuedRunV1 { input: fixture.correlation(), context: restored.context().clone() };
    let now = wall_clock_ms()?;
    let receipt = cold.restore_context_attached_prepared(now, &restored, queued.clone())
        .map_err(|error| anyhow::anyhow!("cold original context: {error:?}"))?;
    assert_eq!(receipt, fixture.expected);
    assert_eq!(cold.restore_context_attached_prepared(now, &restored, queued.clone()), Ok(fixture.expected.clone()));
    let dispatched = cold.mark_dispatched(now, &receipt.run_id, receipt.revision)
        .map_err(|error| anyhow::anyhow!("original dispatch: {error:?}"))?;
    assert_eq!(cold.restore_context_attached_prepared(now, &restored, queued), Err(crate::AgentRunError::InvalidTransition));
    assert_eq!(cold.run(&receipt.run_id), Some(dispatched));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn restored_handoff_requires_current_generation_deadline_and_seven_owner_keys() -> Result<()> {
    let fixture = StoredFixture::create().await?;
    let journal = fixture.reopen()?;
    let committed = journal.prepared(&fixture.original.snapshot.run_id)?.context("committed")?;
    let runner = fixture.read_only_runner()?;
    assert!(runner.restore_canonical_handoff(&committed, fixture.expected.generation + 1, wall_clock_ms()?).is_err());
    let expired = runner.restore_canonical_handoff(&committed, fixture.expected.generation, fixture.expected.deadline_ms);
    assert!(expired.is_err_and(|error| error.to_string().contains("compiled canonical prepared generation or deadline")));
    let mut authority: IntelligenceAuthorityFileV1 = serde_json::from_slice(&std::fs::read(&fixture.authority_path)?)?;
    authority.owners[0].key_epoch += 1;
    authority.signature = authority_signing_key().sign(&authority_signing_payload(&authority)?).to_bytes().to_vec();
    std::fs::write(&fixture.authority_path, serde_json::to_vec(&authority)?)?;
    let stale = runner.restore_canonical_handoff(&committed, fixture.expected.generation, wall_clock_ms()?);
    assert!(stale.is_err_and(|error| error.to_string().contains("KeyDrift")));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rehashed_dto_without_original_journal_publication_cannot_import_a_handoff() -> Result<()> {
    let fixture = StoredFixture::create().await?;
    let raw: serde_json::Value = serde_json::from_slice(&fixture.encoded.payload)?;
    assert!(raw.is_object());
    assert_eq!(Digest32::of_bytes(&fixture.encoded.payload), fixture.encoded.payload_digest);
    let path = fixture._directory.path().join("run-start-only.bin");
    let file = std::fs::OpenOptions::new().create_new(true).read(true).write(true).open(path)?;
    let mut original = DurableRunStartJournal::create(file, digest("original.owner.scope"), /*max_records*/ 16)?;
    let start = original.append(Digest32::ZERO, fixture.original.clone())?;
    assert_eq!(start.record_digest, fixture.encoded.run_start_record_digest);
    // Matching every byte/hash does not create the opaque committed read
    // required by restore_canonical_handoff. No fallback accepts raw DTOs.
    assert_eq!(original.prepared(&fixture.original.snapshot.run_id)?, None);
    assert_eq!(original.records()?.len(), 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn self_consistent_outer_hash_does_not_hide_changed_original_trace_or_material() -> Result<()> {
    let fixture = StoredFixture::create().await?;
    let runner = fixture.read_only_runner()?;
    for field in ["trace", "material", "compiled_snapshot"] {
        let raw = std::str::from_utf8(&fixture.encoded.payload)?;
        let (needle, replacement) = match field {
            "trace" => (format!("\"output_digest\":\"{}\"", fixture.original.snapshot.objective_digest),
                format!("\"output_digest\":\"{}\"", digest("changed.trace"))),
            "material" => ("\"content\":[84,".to_owned(), "\"content\":[0,".to_owned()),
            "compiled_snapshot" => (format!("\"run\":{{\"run_id\":\"{}\",\"request_digest\":", fixture.expected.run_id),
                format!("\"run\":{{\"run_id\":\"{}\",\"request_digest\":", "run:changed")),
            _ => unreachable!(),
        };
        assert!(raw.contains(&needle));
        // Preserve the exact typed field ordering, so rejection exercises
        // retained semantic/material checks, not merely JSON canonicalization.
        let bytes = raw.replacen(&needle, &replacement, 1).into_bytes();
        let path = fixture._directory.path().join(format!("changed-{field}.bin"));
        let file = std::fs::OpenOptions::new().create_new(true).read(true).write(true).open(path)?;
        let mut original = DurableRunStartJournal::create(file, digest("original.owner.scope"), /*max_records*/ 16)?;
        let start = original.append(Digest32::ZERO, fixture.original.clone())?;
        original.append_prepared(original.head_digest(), RunPreparedRecordV1 { run_id: fixture.original.snapshot.run_id.clone(),
            run_start_record_digest: start.record_digest, payload_digest: Digest32::of_bytes(&bytes), payload: bytes })?;
        let committed = original.prepared(&fixture.original.snapshot.run_id)?.context("changed durable record")?;
        assert!(runner.restore_canonical_handoff(&committed, fixture.expected.generation, wall_clock_ms()?).is_err(), "{field}");
    }
    Ok(())
}
