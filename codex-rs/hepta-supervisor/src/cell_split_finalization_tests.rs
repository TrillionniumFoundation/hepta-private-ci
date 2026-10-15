use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;

#[derive(Clone)]
struct LiveAuthority {
    cns_live: Arc<AtomicBool>,
    final_use_live: Arc<AtomicBool>,
    expected_cns_digest: Option<Digest32>,
}

impl LiveAuthority {
    fn allowed() -> Self {
        Self {
            cns_live: Arc::new(AtomicBool::new(true)),
            final_use_live: Arc::new(AtomicBool::new(true)),
            expected_cns_digest: None,
        }
    }

    fn with_cns_digest(mut self, expected: Digest32) -> Self {
        self.expected_cns_digest = Some(expected);
        self
    }
}

impl CellSplitFinalizationAuthorityV1 for LiveAuthority {
    type Error = &'static str;

    fn verify_current_route(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        let expected_cns_digest = self
            .expected_cns_digest
            .unwrap_or_else(|| digest("original signed cns cutover"));
        if self.cns_live.load(Ordering::Acquire)
            && checkpoint.phase != WriterHandoffPhaseV1::Prepared
            && binding.cns_cutover_receipt_digest == expected_cns_digest
            && binding.successor_route_digest == digest("live published successor")
        {
            Ok(())
        } else {
            Err("independent CNS owner no longer serves the original cutover")
        }
    }

    fn verify_current_final_use(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        _checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error> {
        if self.final_use_live.load(Ordering::Acquire)
            && binding.final_use_binding_digest == digest("independently verified NDU selection")
        {
            Ok(())
        } else {
            Err("independent final-use authority was revoked")
        }
    }
}

fn id(s: &str) -> StableId {
    StableId::new(s).expect("fixture ID")
}

fn digest(s: &str) -> Digest32 {
    Digest32::of_bytes(s.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn plan() -> crate::WriterHandoffPlanV1 {
    crate::WriterHandoffPlanV1 {
        operation_id: id("split-real-supervisor"),
        domain_id: id("scope.writer"),
        source_writer: id("writer.old"),
        target_writer: id("writer.new"),
        old_generation: generation(7),
        new_generation: generation(8),
        authority_epoch: 11,
        migration_plan_digest: digest("original migration plan"),
        schema_digest: digest("original state schema"),
        rollback_predecessor_digest: digest("retained rollback root"),
    }
}

fn binding() -> CellSplitFinalizationBindingV1 {
    CellSplitFinalizationBindingV1 {
        operation_id: plan().operation_id,
        domain_id: plan().domain_id,
        source_writer: plan().source_writer,
        target_writer: plan().target_writer,
        old_generation: generation(7),
        new_generation: generation(8),
        authority_epoch: 11,
        migration_plan_digest: plan().migration_plan_digest,
        schema_digest: plan().schema_digest,
        rollback_predecessor_digest: plan().rollback_predecessor_digest,
        cns_cutover_receipt_digest: digest("original signed cns cutover"),
        successor_route_digest: digest("live published successor"),
        final_use_binding_digest: digest("independently verified NDU selection"),
    }
}

fn file(root: &tempfile::TempDir) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(root.path().join("writer-handoff.log"))
        .expect("journal file")
}

fn phase(value: WriterHandoffPhaseV1, watermark: Option<u64>) -> WriterHandoffAdvanceV1 {
    WriterHandoffAdvanceV1 {
        phase: value,
        evidence_digest: digest(&format!("observed {value:?}")),
        outbox_watermark: watermark,
        unknown_effect_count: 0,
    }
}

/// Uses the existing real fsynced journal, including its parent drain and
/// predecessor result fencing phases, not an in-memory fake handoff.
fn prepare(
    root: &tempfile::TempDir,
    terminal_phase: WriterHandoffPhaseV1,
) -> WriterHandoffCheckpointV1 {
    let mut journal = DurableWriterHandoffJournalV1::create(file(root), plan()).expect("journal");
    for value in [
        WriterHandoffPhaseV1::AdmissionStopped,
        WriterHandoffPhaseV1::Drained,
        WriterHandoffPhaseV1::OldWriterFenced,
        WriterHandoffPhaseV1::Snapshotted,
        WriterHandoffPhaseV1::Migrated,
        WriterHandoffPhaseV1::Validated,
        WriterHandoffPhaseV1::NewWriterFenced,
        WriterHandoffPhaseV1::RoutePublished,
    ] {
        if value == WriterHandoffPhaseV1::RoutePublished
            && terminal_phase != WriterHandoffPhaseV1::RoutePublished
        {
            break;
        }
        let watermark = (value == WriterHandoffPhaseV1::Drained).then_some(37);
        journal
            .advance(phase(value, watermark))
            .expect("real persisted phase");
    }
    let checkpoint = journal.checkpoint().clone();
    drop(journal);
    checkpoint
}

#[test]
fn externally_tampered_open_journal_cannot_sign_a_cached_terminal_checkpoint() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        LiveAuthority::allowed(),
    )
    .expect("original fsynced handoff");
    owner.finalize_once().expect("real terminal record");

    let path = root.path().join("writer-handoff.log");
    let original = fs::read(&path).expect("original journal");
    let marker = b"\"phase\":\"prepared\"";
    let start = original
        .windows(marker.len())
        .position(|part| part == marker)
        .expect("original prepared phase");
    let mut corrupted = original.clone();
    // Preserve the byte count so a length-only check cannot hide this edit.
    corrupted[start + 9] = b'x';
    fs::write(&path, corrupted).expect("out-of-band corruption");
    assert!(matches!(
        owner.read_retired_receipt_bytes(),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::Corrupt
        )),
    ));
    fs::write(&path, original).expect("restore original journal");
    assert!(matches!(
        owner.finalize_once(),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::Poisoned
        )),
    ));
}

#[test]
fn externally_appended_uncommitted_tail_cannot_reuse_a_signed_checkpoint() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        LiveAuthority::allowed(),
    )
    .expect("original handoff");
    let path = root.path().join("writer-handoff.log");
    let mut bytes = fs::read(&path).expect("original");
    bytes.extend_from_slice(b"{\"unacknowledged\":");
    fs::write(&path, bytes).expect("interrupted external append");
    assert!(matches!(
        owner.read_retired(),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::Corrupt
        )),
    ));
    assert!(matches!(
        owner.finalize_once(),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::Poisoned
        )),
    ));
}

#[test]
fn actually_appends_retired_checkpoint_and_reopens_identical_receipt() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let auth = LiveAuthority::allowed();
    let original;
    {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            auth.clone(),
        )
        .expect("authenticated journal reopen");
        assert!(owner.read_retired().expect("route published").is_none());
        original = owner.finalize_once().expect("fsynced Retired state");
        assert_eq!(original.phase, WriterHandoffPhaseV1::Retired);
        assert_eq!(original.revision, minimum.revision + 1);
        assert_eq!(original.previous_receipt_digest, minimum.receipt_digest);
        assert_eq!(
            original.evidence_digest,
            binding().retirement_evidence_digest()
        );
        assert!(!original.old_writer_valid());
        assert!(original.new_writer_admission_open());
        assert_eq!(
            owner.read_retired().expect("real state"),
            Some(original.clone())
        );
        let original_bytes = owner
            .read_retired_receipt_bytes()
            .expect("original signed-record input")
            .expect("committed bytes");
        assert_eq!(
            original_bytes,
            original.canonical_receipt_bytes_v1().expect("record")
        );
        let journal_file = fs::read(root.path().join("writer-handoff.log")).expect("disk");
        let raw_last = journal_file
            .split(|byte| *byte == b'\n')
            .rev()
            .find(|record| !record.is_empty())
            .expect("last durable record");
        assert_eq!(original_bytes.as_slice(), raw_last);
        assert_eq!(
            owner.finalize_once().expect("one original commit"),
            original
        );
    }
    let mut recovered = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        auth,
    )
    .expect("journal recovery after process shutdown");
    assert_eq!(
        recovered.read_retired().expect("fresh readback"),
        Some(original.clone())
    );
    assert_eq!(
        recovered
            .read_retired_receipt_bytes()
            .expect("recovered bytes"),
        Some(
            original
                .canonical_receipt_bytes_v1()
                .expect("canonical original")
        )
    );
}

#[test]
fn final_use_revocation_fences_both_mutation_and_readback() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let auth = LiveAuthority::allowed();
    let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        auth.clone(),
    )
    .expect("reopen");
    auth.final_use_live.store(false, Ordering::Release);
    assert!(matches!(
        owner.finalize_once(),
        Err(CellSplitFinalizationErrorV1::Revoked(_))
    ));
    assert_eq!(
        owner.checkpoint().phase,
        WriterHandoffPhaseV1::RoutePublished
    );
    auth.final_use_live.store(true, Ordering::Release);
    owner.finalize_once().expect("real append");
    auth.cns_live.store(false, Ordering::Release);
    assert!(matches!(
        owner.read_retired(),
        Err(CellSplitFinalizationErrorV1::Revoked(_))
    ));
}

#[test]
fn pre_route_generation_cannot_retire_or_skip_writer_fences() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::NewWriterFenced);
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::NotRoutePublished)
    ));
}

#[test]
fn independent_minimum_rejects_restoring_valid_older_journal() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let stale_bytes = fs::read(root.path().join("writer-handoff.log")).expect("prefix");
    let durable = {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            LiveAuthority::allowed(),
        )
        .expect("reopen");
        owner.finalize_once().expect("commit")
    };
    fs::write(root.path().join("writer-handoff.log"), stale_bytes)
        .expect("externally restored old-but-valid prefix");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &durable,
            binding(),
            LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::AcknowledgedCheckpointMissing
        ))
    ));
}

#[test]
fn different_original_cns_or_handoff_plan_cannot_replay_same_retirement() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    {
        let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            LiveAuthority::allowed(),
        )
        .expect("open");
        owner.finalize_once().expect("real terminal receipt");
    }
    let mut changed = binding();
    changed.cns_cutover_receipt_digest = digest("different signed CNS effect");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            changed,
            LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::InvalidBinding)
    ));
    let mut changed = binding();
    changed.migration_plan_digest = digest("other migration");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            changed,
            LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::InvalidBinding)
    ));
}

#[test]
fn independent_writer_lock_blocks_second_owner() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let _first = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        LiveAuthority::allowed(),
    )
    .expect("first owner");
    assert!(matches!(
        CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            LiveAuthority::allowed()
        ),
        Err(CellSplitFinalizationErrorV1::Handoff(
            WriterHandoffErrorV1::Busy
        ))
    ));
}
#[test]
fn schema_rollback_and_writer_identity_are_frozen_for_retirement() {
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let changed_fields = [
        {
            let mut alternate = binding();
            alternate.schema_digest = digest("different checkpoint schema");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.rollback_predecessor_digest = digest("different rollback lineage");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.source_writer = id("untrusted-old-writer");
            alternate
        },
        {
            let mut alternate = binding();
            alternate.target_writer = id("untrusted-successor");
            alternate
        },
    ];
    for alternate in changed_fields {
        assert!(matches!(
            CellSplitSupervisorJournalFinalizerV1::recover_at_least(
                file(&root),
                &minimum,
                alternate,
                LiveAuthority::allowed()
            ),
            Err(CellSplitFinalizationErrorV1::InvalidBinding)
        ));
    }
}

#[test]
fn lost_ack_after_real_journal_fsync_recovers_without_second_retirement() {
    struct RevokeAfterWrite(Arc<AtomicUsize>);
    impl CellSplitFinalizationAuthorityV1 for RevokeAfterWrite {
        type Error = &'static str;
        fn verify_current_route(
            &mut self,
            _binding: &CellSplitFinalizationBindingV1,
            _checkpoint: &WriterHandoffCheckpointV1,
        ) -> Result<(), Self::Error> {
            Ok(())
        }
        fn verify_current_final_use(
            &mut self,
            _binding: &CellSplitFinalizationBindingV1,
            _checkpoint: &WriterHandoffCheckpointV1,
        ) -> Result<(), Self::Error> {
            if self.0.fetch_add(1, Ordering::SeqCst) == 0 {
                Ok(())
            } else {
                Err("final-use revoked immediately after the journal commit")
            }
        }
    }
    let root = tempfile::tempdir().expect("dir");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    {
        let mut finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            RevokeAfterWrite(Arc::new(AtomicUsize::new(0))),
        )
        .expect("journal");
        assert!(matches!(
            finalizer.finalize_once(),
            Err(CellSplitFinalizationErrorV1::Revoked(_))
        ));
        assert_eq!(finalizer.checkpoint().phase, WriterHandoffPhaseV1::Retired);
        assert_eq!(finalizer.checkpoint().revision, minimum.revision + 1);
    }
    let mut owner = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        LiveAuthority::allowed(),
    )
    .expect("reconcile original journal after ack loss");
    let original = owner
        .read_retired()
        .expect("retained original")
        .expect("retired");
    assert_eq!(original.revision, minimum.revision + 1);
    assert_eq!(owner.finalize_once().expect("never append twice"), original);
}

#[cfg(all(unix, feature = "cell-split-supervisor-port"))]
fn real_supervisor_effect_inputs() -> (
    codex_hepta_operator_acceptance::CellSplitExecutionPlanV1,
    codex_hepta_operator_acceptance::CellSplitSupervisorFenceBindingV1,
    codex_hepta_operator_acceptance::CellSplitExecutionIntentV1,
    Digest32,
) {
    use codex_hepta_operator_acceptance::CellSplitExecutionIntentV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionPlanV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
    use codex_hepta_operator_acceptance::CellSplitSupervisorFenceBindingV1;
    use sha2::Digest as _;

    let real = binding();
    let accepted_handoff = digest("independently signed handoff plan");
    let execution = CellSplitExecutionPlanV1 {
        split_id: real.operation_id.to_string(),
        scope_digest: digest("journal scope").to_string(),
        parent_generation: real.old_generation.get(),
        child_generation: real.new_generation.get(),
        parent_artifact_digest: digest("parent immutable artifact").to_string(),
        child_artifact_digest: digest("selected immutable artifact").to_string(),
        ndu_snapshot_digest: digest("independent NDU selection").to_string(),
        route_fence_digest: digest("current real result fence").to_string(),
        owner_ids: [
            "artifact.owner".into(),
            "migration.owner".into(),
            "cns.owner".into(),
            "supervisor.owner".into(),
        ],
    };
    let outer = CellSplitSupervisorFenceBindingV1 {
        supervisor_id: "supervisor.real".into(),
        domain_id: real.domain_id.to_string(),
        authority_epoch: real.authority_epoch,
        handoff_plan_digest: accepted_handoff.to_string(),
        successor_route_digest: real.successor_route_digest.to_string(),
    };
    let plan_digest = execution.digest().expect("frozen plan digest");
    let previous = real.cns_cutover_receipt_digest.to_string();
    let idempotency_key = format!(
        "{:x}",
        sha2::Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                plan_digest,
                CellSplitExecutionStepV1::SupervisorGenerationFence.index(),
                previous,
            )
            .as_bytes()
        )
    );
    let intent = CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest,
        step: CellSplitExecutionStepV1::SupervisorGenerationFence,
        owner_id: execution.owner_ids[3].clone(),
        idempotency_key,
        previous_receipt_digest: previous,
    };
    (execution, outer, intent, accepted_handoff)
}

#[cfg(all(unix, feature = "cell-split-supervisor-port"))]
#[test]
fn real_journal_port_links_signed_cns_predecessor_and_original_runtime_bytes() {
    use codex_hepta_operator_acceptance::CellSplitCnsRuntimeCommitV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionReceiptV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
    use codex_hepta_operator_acceptance::CellSplitSupervisorRuntimePortV1;
    use codex_hepta_operator_acceptance::cell_split_execution_receipt_digest_v1;
    use codex_hepta_operator_acceptance::cell_split_execution_signing_payload_v1;
    use ed25519_dalek::Signer as _;
    use ed25519_dalek::SigningKey;
    use sha2::Digest as _;

    let root = tempfile::tempdir().expect("journal");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let authority = LiveAuthority::allowed();
    let (plan, fence, mut supervisor_intent, accepted) = real_supervisor_effect_inputs();
    let cns_signer = SigningKey::from_bytes(&[31; 32]);
    let cns_runtime_signer = SigningKey::from_bytes(&[41; 32]);
    let cns_previous = digest("separately committed child migration").to_string();
    let cns_key = format!(
        "{:x}",
        sha2::Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                plan.digest().expect("plan"),
                CellSplitExecutionStepV1::CnsRouteCutover.index(),
                cns_previous,
            )
            .as_bytes()
        )
    );
    let cns_intent = codex_hepta_operator_acceptance::CellSplitExecutionIntentV1 {
        schema: "hepta.learning.cell-split.execution-owner.v1".into(),
        plan_digest: plan.digest().expect("plan"),
        step: CellSplitExecutionStepV1::CnsRouteCutover,
        owner_id: plan.owner_ids[2].clone(),
        idempotency_key: cns_key.clone(),
        previous_receipt_digest: cns_previous,
    };
    let mut original_cns = CellSplitCnsRuntimeCommitV1 {
        idempotency_key: cns_key,
        cns_id: "cns.original".into(),
        predecessor_route_digest: digest("parent route").to_string(),
        successor_route_digest: fence.successor_route_digest.clone(),
        predecessor_generation: plan.parent_generation,
        successor_generation: plan.child_generation,
        authority_epoch: fence.authority_epoch,
        committed_sequence: 3,
        original_runtime_receipt_bytes: Vec::new(),
        original_runtime_signature_bytes: Vec::new(),
    };
    let attested = codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1::for_commit(
        &plan,
        &original_cns,
    )
    .canonical_bytes()
    .expect("canonical original CNS runtime attestation");
    original_cns.original_runtime_signature_bytes =
        cns_runtime_signer.sign(&attested).to_bytes().to_vec();
    original_cns.original_runtime_receipt_bytes = attested;
    let mut verified_binding = binding();
    verified_binding.cns_cutover_receipt_digest =
        Digest32::of_bytes(&original_cns.original_runtime_receipt_bytes);
    let authority = authority.with_cns_digest(verified_binding.cns_cutover_receipt_digest);
    let original_bytes = serde_json::to_vec(&original_cns).expect("CNS original bytes");
    let mut cns_receipt = CellSplitExecutionReceiptV1 {
        intent: cns_intent,
        owner_sequence: 3,
        output_digest: format!("{:x}", sha2::Sha256::digest(&original_bytes)),
        owner_receipt_bytes: original_bytes,
        owner_signature_bytes: Vec::new(),
        receipt_digest: String::new(),
    };
    cns_receipt.owner_signature_bytes = cns_signer
        .sign(&cell_split_execution_signing_payload_v1(&cns_receipt).expect("CNS signing bytes"))
        .to_bytes()
        .to_vec();
    cns_receipt.receipt_digest =
        cell_split_execution_receipt_digest_v1(&cns_receipt).expect("outer CNS receipt");
    assert_ne!(cns_receipt.receipt_digest, cns_receipt.output_digest);
    assert_ne!(
        cns_receipt.receipt_digest,
        verified_binding.cns_cutover_receipt_digest.to_string()
    );
    supervisor_intent.previous_receipt_digest = cns_receipt.receipt_digest.clone();
    supervisor_intent.idempotency_key = format!(
        "{:x}",
        sha2::Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                supervisor_intent.plan_digest,
                supervisor_intent.step.index(),
                supervisor_intent.previous_receipt_digest,
            )
            .as_bytes()
        )
    );
    let finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        verified_binding.clone(),
        authority.clone(),
    )
    .expect("real journal");
    let mut port = crate::CellSplitSupervisorJournalRuntimePortV1::new_with_signed_cns_predecessor(
        plan.clone(),
        fence.clone(),
        supervisor_intent.clone(),
        accepted,
        finalizer,
        SigningKey::from_bytes(&[22; 32]),
        &cns_receipt,
        &cns_signer.verifying_key(),
        &cns_runtime_signer.verifying_key(),
    )
    .expect("independent CNS/Coordinator digest bridge");
    port.finalize_once(&plan, &supervisor_intent, &fence)
        .expect("actual fsynced retirement");
    assert!(
        port.read_original_commit(&supervisor_intent.idempotency_key)
            .expect("readback")
            .is_some()
    );

    // An attacker may control the outer CNS effect signing key but must not
    // be able to replace the independent runtime acknowledgement. Re-sign the
    // outer envelope after corrupting only the original runtime signature.
    let mut forged_cns = cns_receipt.clone();
    let mut forged_original: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&forged_cns.owner_receipt_bytes).expect("typed original");
    forged_original.original_runtime_signature_bytes[0] ^= 0x80;
    forged_cns.owner_receipt_bytes =
        serde_json::to_vec(&forged_original).expect("outer envelope bytes");
    forged_cns.output_digest = format!(
        "{:x}",
        sha2::Sha256::digest(&forged_cns.owner_receipt_bytes),
    );
    forged_cns.owner_signature_bytes = cns_signer
        .sign(&cell_split_execution_signing_payload_v1(&forged_cns).expect("outer signature"))
        .to_bytes()
        .to_vec();
    forged_cns.receipt_digest =
        cell_split_execution_receipt_digest_v1(&forged_cns).expect("forged outer receipt");
    let mut forged_intent = supervisor_intent.clone();
    forged_intent.previous_receipt_digest = forged_cns.receipt_digest.clone();
    forged_intent.idempotency_key = format!(
        "{:x}",
        sha2::Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                forged_intent.plan_digest,
                forged_intent.step.index(),
                forged_intent.previous_receipt_digest,
            )
            .as_bytes()
        )
    );
    let root_inner_denied = tempfile::tempdir().expect("independent original journal");
    let minimum_inner_denied = prepare(&root_inner_denied, WriterHandoffPhaseV1::RoutePublished);
    let inner_finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root_inner_denied),
        &minimum_inner_denied,
        verified_binding.clone(),
        authority.clone(),
    )
    .expect("original journal before forged CNS evidence");
    assert!(
        crate::CellSplitSupervisorJournalRuntimePortV1::new_with_signed_cns_predecessor(
            plan.clone(),
            fence.clone(),
            forged_intent,
            accepted,
            inner_finalizer,
            SigningKey::from_bytes(&[22; 32]),
            &forged_cns,
            &cns_signer.verifying_key(),
            &cns_runtime_signer.verifying_key(),
        )
        .is_err(),
        "a valid outer CNS signature must never launder a forged runtime signature"
    );

    // Both signatures may be mathematically valid while the independently
    // signed runtime statement belongs to another scope. The Supervisor
    // must reject this provenance substitution before opening an effect.
    let mut cross_scope_cns = cns_receipt.clone();
    let mut cross_scope_original: CellSplitCnsRuntimeCommitV1 =
        serde_json::from_slice(&cross_scope_cns.owner_receipt_bytes)
            .expect("signed outer CNS receipt");
    let mut cross_scope_attestation:
        codex_hepta_operator_acceptance::CellSplitCnsRuntimeAttestationV1 =
        serde_json::from_slice(&cross_scope_original.original_runtime_receipt_bytes)
            .expect("canonical original CNS runtime statement");
    cross_scope_attestation.scope_digest = "aa".repeat(32);
    let unrelated = cross_scope_attestation
        .canonical_bytes()
        .expect("canonical unrelated CNS runtime statement");
    cross_scope_original.original_runtime_signature_bytes =
        cns_runtime_signer.sign(&unrelated).to_bytes().to_vec();
    cross_scope_original.original_runtime_receipt_bytes = unrelated;
    cross_scope_cns.owner_receipt_bytes =
        serde_json::to_vec(&cross_scope_original).expect("outer CNS receipt");
    cross_scope_cns.output_digest = format!(
        "{:x}",
        sha2::Sha256::digest(&cross_scope_cns.owner_receipt_bytes)
    );
    cross_scope_cns.owner_signature_bytes = cns_signer
        .sign(
            &cell_split_execution_signing_payload_v1(&cross_scope_cns)
                .expect("outer CNS signing bytes"),
        )
        .to_bytes()
        .to_vec();
    cross_scope_cns.receipt_digest = cell_split_execution_receipt_digest_v1(&cross_scope_cns)
        .expect("authentic outer signed receipt");
    let mut cross_scope_intent = supervisor_intent.clone();
    cross_scope_intent.previous_receipt_digest = cross_scope_cns.receipt_digest.clone();
    cross_scope_intent.idempotency_key = format!(
        "{:x}",
        sha2::Sha256::digest(
            format!(
                "hepta.learning.cell-split.execution-owner.v1\0{}\0{}\0{}",
                cross_scope_intent.plan_digest,
                cross_scope_intent.step.index(),
                cross_scope_intent.previous_receipt_digest,
            )
            .as_bytes(),
        ),
    );
    let root_cross_scope = tempfile::tempdir().expect("separate journal for wrong scope");
    let minimum_cross_scope = prepare(&root_cross_scope, WriterHandoffPhaseV1::RoutePublished);
    let finalizer_cross_scope = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root_cross_scope),
        &minimum_cross_scope,
        verified_binding.clone(),
        authority.clone(),
    )
    .expect("real Supervisor journal");
    assert!(
        crate::CellSplitSupervisorJournalRuntimePortV1::new_with_signed_cns_predecessor(
            plan.clone(),
            fence.clone(),
            cross_scope_intent,
            accepted,
            finalizer_cross_scope,
            SigningKey::from_bytes(&[22; 32]),
            &cross_scope_cns,
            &cns_signer.verifying_key(),
            &cns_runtime_signer.verifying_key(),
        )
        .is_err(),
        "valid signatures from another scope do not authorize this split"
    );

    let root_denied = tempfile::tempdir().expect("independent journal");
    let minimum_denied = prepare(&root_denied, WriterHandoffPhaseV1::RoutePublished);
    let denied_finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root_denied),
        &minimum_denied,
        verified_binding.clone(),
        authority,
    )
    .expect("other real journal");
    assert!(
        crate::CellSplitSupervisorJournalRuntimePortV1::new_with_signed_cns_predecessor(
            plan,
            fence,
            supervisor_intent,
            accepted,
            denied_finalizer,
            SigningKey::from_bytes(&[22; 32]),
            &cns_receipt,
            &SigningKey::from_bytes(&[32; 32]).verifying_key(),
            &cns_runtime_signer.verifying_key(),
        )
        .is_err(),
        "wrong independent CNS signer must not authorize retirement"
    );
}

#[cfg(all(unix, feature = "cell-split-supervisor-port"))]
#[test]
fn real_journal_port_finalizes_authenticated_fourth_step_and_reopens() {
    use codex_hepta_operator_acceptance::CellSplitDurableEffectBackendV1;
    use codex_hepta_operator_acceptance::CellSplitSupervisorFenceOwnerV1;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt as _;

    let root = tempfile::tempdir().expect("private owner");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).expect("private root");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let authority = LiveAuthority::allowed();
    let (plan, fence, intent, accepted) = real_supervisor_effect_inputs();
    let signer = SigningKey::from_bytes(&[21; 32]);

    let original;
    {
        let finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            file(&root),
            &minimum,
            binding(),
            authority.clone(),
        )
        .expect("real locked journal");
        let port = crate::CellSplitSupervisorJournalRuntimePortV1::new(
            plan.clone(),
            fence.clone(),
            intent.clone(),
            accepted,
            finalizer,
            signer.clone(),
        )
        .expect("pinned source of truth");
        let mut owner =
            CellSplitSupervisorFenceOwnerV1::open(root.path(), plan.clone(), fence.clone(), port)
                .expect("real protocol owner");
        assert!(owner.read_committed(&intent).expect("published").is_none());
        owner
            .commit_once(&intent)
            .expect("actual fsynced journal retirement");
        original = owner
            .read_committed(&intent)
            .expect("read")
            .expect("commit");
        assert_eq!(original.owner_sequence, minimum.revision + 1);
        assert!(
            owner
                .verify_current(&intent, &original)
                .expect("live journal")
        );
        // A committed original fourth-step operation cannot execute twice.
        // Only authenticated read-only reconciliation may confirm it; no
        // extra Supervisor journal record or positive Execute ack is minted.
        assert!(matches!(
            owner.commit_once(&intent),
            Err(codex_hepta_operator_acceptance::CellSplitSupervisorFenceErrorV1::Ambiguous)
        ));
        assert_eq!(
            owner.read_committed(&intent).expect("existing durable effect"),
            Some(original.clone()),
            "rejected replay must preserve the exact original signed receipt"
        );
        assert_eq!(
            owner.current_sequence().expect("original journal revision"),
            original.owner_sequence,
            "rejected replay must not append a second Supervisor journal entry"
        );
    }

    let finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        authority.clone(),
    )
    .expect("authenticated original journal recovery");
    let port = crate::CellSplitSupervisorJournalRuntimePortV1::new(
        plan.clone(),
        fence.clone(),
        intent.clone(),
        accepted,
        finalizer,
        signer,
    )
    .expect("trusted replay");
    let mut reopened = CellSplitSupervisorFenceOwnerV1::open(root.path(), plan, fence, port)
        .expect("reopen frozen effect");
    assert_eq!(
        reopened.read_committed(&intent).expect("fresh readback"),
        Some(original.clone())
    );
    assert!(
        reopened
            .verify_current(&intent, &original)
            .expect("authenticated original")
    );
    authority.final_use_live.store(false, Ordering::Release);
    assert!(reopened.verify_current(&intent, &original).is_err());
}

#[cfg(all(unix, feature = "cell-split-supervisor-port"))]
#[test]
fn real_journal_port_rejects_forged_nonce_and_unpinned_cutover() {
    use codex_hepta_operator_acceptance::CellSplitSupervisorRuntimePortV1;
    use ed25519_dalek::SigningKey;

    let root = tempfile::tempdir().expect("private owner");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let authority = LiveAuthority::allowed();
    let (plan, fence, intent, accepted) = real_supervisor_effect_inputs();
    let finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
        file(&root),
        &minimum,
        binding(),
        authority,
    )
    .expect("original journal");
    let mut port = crate::CellSplitSupervisorJournalRuntimePortV1::new(
        plan.clone(),
        fence.clone(),
        intent.clone(),
        accepted,
        finalizer,
        SigningKey::from_bytes(&[23; 32]),
    )
    .expect("pinned journal port");

    let live = port
        .read_live(&fence.supervisor_id, &fence.domain_id, &"aa".repeat(32))
        .expect("authenticated live read");
    port.verify_live(&live).expect("original signed challenge");
    let mut stale = live.clone();
    stale.challenge_nonce = "bb".repeat(32);
    assert!(port.verify_live(&stale).is_err());

    let mut unbound = intent.clone();
    unbound.previous_receipt_digest = digest("different cutover").to_string();
    assert!(port.verify_preconditions(&plan, &unbound, &fence).is_err());

    port.finalize_once(&plan, &intent, &fence)
        .expect("actual durable retirement");
    let mut original = port
        .read_original_commit(&intent.idempotency_key)
        .expect("source record")
        .expect("durable receipt");
    port.verify_original_commit(&original)
        .expect("pinned original record");
    original.original_checkpoint_bytes[0] ^= 1;
    assert!(port.verify_original_commit(&original).is_err());
}

#[cfg(all(unix, feature = "cell-split-supervisor-port"))]
#[test]
fn real_journal_port_signed_rpc_reconciles_original_after_restart() {
    use codex_hepta_operator_acceptance::CellSplitEffectServiceV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionPortV1;
    use codex_hepta_operator_acceptance::CellSplitExecutionStepV1;
    use codex_hepta_operator_acceptance::CellSplitSupervisorFenceOwnerV1;
    use codex_hepta_operator_acceptance::CellSplitUnixEffectPortV1;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt as _;
    use std::os::unix::net::UnixListener;
    use std::thread;
    use std::time::Duration;

    let root = tempfile::tempdir().expect("private owner directory");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).expect("private owner");
    let minimum = prepare(&root, WriterHandoffPhaseV1::RoutePublished);
    let authority = LiveAuthority::allowed();
    let (plan, fence, intent, accepted) = real_supervisor_effect_inputs();
    let listener =
        UnixListener::bind(root.path().join("supervisor.sock")).expect("real supervisor endpoint");
    let path = root.path().to_path_buf();
    let frozen_plan = plan.clone();
    let frozen_fence = fence.clone();
    let signer_authority = authority.clone();
    let server = thread::spawn(move || {
        let finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(path.join("writer-handoff.log"))
                .expect("original journal"),
            &minimum,
            binding(),
            signer_authority.clone(),
        )
        .expect("real fsynced supervisor journal");
        let port = crate::CellSplitSupervisorJournalRuntimePortV1::new(
            frozen_plan.clone(),
            frozen_fence.clone(),
            real_supervisor_effect_inputs().2,
            accepted,
            finalizer,
            SigningKey::from_bytes(&[21; 32]),
        )
        .expect("pinned runtime adapter");
        let backend = CellSplitSupervisorFenceOwnerV1::open(
            &path,
            frozen_plan.clone(),
            frozen_fence.clone(),
            port,
        )
        .expect("signed final effect");
        let mut service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::SupervisorGenerationFence,
            frozen_plan.owner_ids[3].clone(),
            frozen_plan.digest().expect("frozen plan"),
            SigningKey::from_bytes(&[4; 32]),
            backend,
        )
        .expect("independent operation signer");
        for _ in 0..3 {
            let (mut stream, _) = listener.accept().expect("original RPC");
            service
                .serve_connection(&mut stream)
                .expect("real signed journal read");
        }
        drop(service);
        let reopened_finalizer = CellSplitSupervisorJournalFinalizerV1::recover_at_least(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(path.join("writer-handoff.log"))
                .expect("reopen original"),
            &minimum,
            binding(),
            signer_authority,
        )
        .expect("authentic journal after restart");
        let reopened_port = crate::CellSplitSupervisorJournalRuntimePortV1::new(
            frozen_plan.clone(),
            frozen_fence.clone(),
            real_supervisor_effect_inputs().2,
            accepted,
            reopened_finalizer,
            SigningKey::from_bytes(&[21; 32]),
        )
        .expect("same independent signer");
        let reopened_backend = CellSplitSupervisorFenceOwnerV1::open(
            &path,
            frozen_plan.clone(),
            frozen_fence,
            reopened_port,
        )
        .expect("reopened signed owner");
        let mut reopened_service = CellSplitEffectServiceV1::new(
            CellSplitExecutionStepV1::SupervisorGenerationFence,
            frozen_plan.owner_ids[3].clone(),
            frozen_plan.digest().expect("plan"),
            SigningKey::from_bytes(&[4; 32]),
            reopened_backend,
        )
        .expect("service restart");
        let (mut stream, _) = listener.accept().expect("recovery RPC");
        reopened_service
            .serve_connection(&mut stream)
            .expect("original checkpoint readback");
    });
    let keys = [1_u8, 2, 3, 4].map(|n| SigningKey::from_bytes(&[n; 32]).verifying_key());
    let mut client = CellSplitUnixEffectPortV1::new(
        [
            root.path().join("cas.sock"),
            root.path().join("migration.sock"),
            root.path().join("cns.sock"),
            root.path().join("supervisor.sock"),
        ],
        keys,
        Duration::from_secs(3),
    )
    .expect("four distinct owner credentials");

    let signed = client
        .execute(&intent)
        .expect("actual signed journal append");
    client
        .verify_committed(&intent, &signed)
        .expect("fresh signed live journal readback");
    assert_eq!(
        client.reconcile(&intent).expect("original checkpoint read"),
        Some(signed.clone()),
    );
    assert_eq!(
        client
            .reconcile(&intent)
            .expect("journal read after restart"),
        Some(signed),
    );
    server.join().expect("real journal service restart");
}
