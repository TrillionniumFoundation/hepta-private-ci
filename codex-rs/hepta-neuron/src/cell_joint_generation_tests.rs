//! Actual process execution with invalid packets and fixed legal synthetic
//! tensors. These tests do not qualify a trained checkpoint or model accuracy.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellEvolutionBindingV2;
use crate::CellGenerationScopeV2;
use crate::CellRuntimeSnapshotV2;
use crate::cell_joint_protocol::JointGenerationActionV1;
use crate::cell_joint_protocol::JointGenerationCommandV1;
use crate::cell_joint_protocol::JointGenerationModalityV1;
use crate::cell_joint_protocol::JointGenerationSamplerV1;

#[path = "../tests/support/joint_synthetic.rs"]
mod synthetic;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new() -> TestResult<Self> {
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("hepta-joint-transport-{}-{id}", std::process::id()));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

struct Harness {
    directory: Directory,
    worker: JointGenerationProcessWorkerV1,
    manifest: CellBackendManifestV2,
    request: CellGenerationRequestV2,
}

impl Harness {
    fn new(weights_bytes: usize, clock: Arc<dyn Fn() -> u64 + Send + Sync>) -> TestResult<Self> {
        Self::with_assets(
            vec![1; weights_bytes],
            b"invalid public packet for transport qualification".to_vec(),
            clock,
        )
    }

    fn with_assets(
        weights: Vec<u8>,
        public: Vec<u8>,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> TestResult<Self> {
        let directory = Directory::new()?;
        // The qualification helper manifest supplies compiler-reported paths.
        // The repository's /bin/sh entry preserves the underscore alias; some
        // shells remove hyphenated environment names. Never guess target paths.
        let binary = [
            "CARGO_BIN_EXE_hepta-joint-propose",
            "CARGO_BIN_EXE_hepta_joint_propose",
            "NEXTEST_BIN_EXE_hepta-joint-propose",
            "NEXTEST_BIN_EXE_hepta_joint_propose",
        ]
        .into_iter()
        .find_map(std::env::var_os)
        .map(PathBuf::from)
        .ok_or_else(|| {
            std::io::Error::other("missing actual hepta-joint-propose helper metadata")
        })?;
        if !binary.is_absolute() {
            return Err(std::io::Error::other("helper path must be absolute").into());
        }
        let executable = directory.0.join("proposal");
        fs::copy(binary, &executable)?;
        let weights_path = directory.0.join("weights.hps");
        let public_path = directory.0.join("public.hps");
        fs::write(&weights_path, &weights)?;
        fs::write(&public_path, &public)?;
        let executable_digest = cell_joint_process::executable_digest(&File::open(&executable)?)?;
        let weights_digest = Digest32::of_bytes(&weights).into_array();
        let public_digest = Digest32::of_bytes(&public).into_array();
        let source_digest =
            Digest32::of_bytes(b"explicit-synthetic-joint-process-fixture").into_array();
        let device_digest = JointGenerationProcessWorkerV1::observed_device_digest()?;
        let worker = JointGenerationProcessWorkerV1::open(
            JointGenerationProcessConfigV1 {
                executable,
                executable_digest,
                source_digest,
                weights: weights_path,
                weights_digest,
                public: public_path,
                public_digest,
                device_digest,
            },
            clock,
        )?;
        let manifest = CellBackendManifestV2 {
            profile: JointGenerationProcessWorkerV1::PROFILE.into(),
            source_digest,
            bundle_digest: Digest32::of_bytes(b"synthetic-transport-bundle").into_array(),
            encoder: Some(worker.encoder_digest()),
            head: Some(worker.head_digest()),
            memory: Some(worker.memory_digest()),
            world_model: None,
            decoder: Some(worker.decoder_digest()),
            runtime_digest: executable_digest,
            device_digest,
            input_schema: JointGenerationProcessWorkerV1::input_schema_digest(),
            state_schema: JointGenerationProcessWorkerV1::state_schema_digest(),
            output_schema: JointGenerationProcessWorkerV1::output_schema_digest(),
            learning: CellLearningBindingV2::Frozen {
                weights: weights_digest,
            },
            evolution: CellEvolutionBindingV2 {
                structure: [1; 32],
                lineage: [2; 32],
                source_dependencies: [3; 32],
                adoption_receipt: [4; 32],
            },
            max_input_bytes: 65_536,
            max_state_bytes: 65_536,
            max_delta_bytes: 65_536,
            max_prefix_bytes: 65_536,
            max_step_cost_entries: 8,
            max_ack_cost_entries: 1,
        };
        let request = CellGenerationRequestV2 {
            operation_id: "test-operation".into(),
            task_digest: [5; 32],
            source_frontier: [6; 32],
            predecessor: CellRuntimeSnapshotV2 {
                scope: CellGenerationScopeV2 {
                    principal_digest: [7; 32],
                    agent_id: "test-agent".into(),
                    cell_id: "test-cell".into(),
                    run_id: "test-run".into(),
                },
                manifest_digest: manifest.digest()?,
                generation: 1,
                writer_epoch: 1,
                revision: 0,
                state: Vec::new(),
                prefix: Vec::new(),
                stopped: false,
            },
            input: serde_json::to_vec(&JointGenerationInputV1 {
                public_digest,
                command: JointGenerationCommandV1::Init {
                    seed: 17,
                    sampler: JointGenerationSamplerV1::Mean,
                },
            })?,
            admitted_at_micros: 1,
            deadline_micros: 30_000_000,
        };
        Ok(Self {
            directory,
            worker,
            manifest,
            request,
        })
    }

    fn reopened_worker(&self) -> TestResult<JointGenerationProcessWorkerV1> {
        Ok(JointGenerationProcessWorkerV1::open(
            JointGenerationProcessConfigV1 {
                executable: self.directory.0.join("proposal"),
                executable_digest: self.manifest.runtime_digest,
                source_digest: self.manifest.source_digest,
                weights: self.directory.0.join("weights.hps"),
                weights_digest: self.worker.weights_digest,
                public: self.directory.0.join("public.hps"),
                public_digest: self.worker.public_digest,
                device_digest: self.manifest.device_digest,
            },
            Arc::clone(&self.worker.clock),
        )?)
    }

    fn propose(
        &mut self,
        operation: &str,
        command: JointGenerationCommandV1,
    ) -> TestResult<CellGenerationProposalV2> {
        self.request.operation_id = operation.into();
        self.request.input = serde_json::to_vec(&JointGenerationInputV1 {
            public_digest: self.worker.public_digest,
            command,
        })?;
        let proposal =
            self.worker
                .execute(&self.manifest, &self.request, &AtomicBool::new(false))?;
        assert_eq!(proposal.request_digest, self.request.digest()?);
        assert_eq!(proposal.runtime_digest, self.manifest.runtime_digest);
        assert_eq!(proposal.cost.entries().len(), 5);
        assert_eq!(
            proposal
                .cost
                .entries()
                .iter()
                .map(|entry| entry.stage)
                .collect::<Vec<_>>(),
            [
                CellCostStageV2::Codec,
                CellCostStageV2::Encoder,
                CellCostStageV2::Inference,
                CellCostStageV2::Planning,
                CellCostStageV2::Communication,
            ]
        );
        assert!(proposal.cost.entries().iter().all(|entry| {
            entry.outcome == CellCostOutcomeV2::Succeeded
                && entry.accounting == CellCostAccountingV2::Exclusive
                && entry.metrics.wall_micros.is_some()
                && entry.metrics.cpu_micros.is_none()
                && entry.metrics.energy_microjoules.is_none()
        }));
        assert!(
            proposal
                .cost
                .entries()
                .iter()
                .any(|entry| entry.metrics.wall_micros.is_some_and(|value| value > 0))
        );
        assert!(
            proposal.cost.entries()[4]
                .metrics
                .communication_bytes
                .is_some_and(|value| value > 4_778_904)
        );
        Ok(proposal)
    }

    fn adopt_for_next_fixture_request(&mut self, proposal: &CellGenerationProposalV2) {
        // Only this direct worker test projects the caller-supplied predecessor.
        // The Agentd test separately exercises the sole durable journal owner.
        self.request.predecessor.state = proposal.successor_state.clone();
        self.request
            .predecessor
            .prefix
            .extend(&proposal.output_delta);
        self.request.predecessor.stopped =
            proposal.disposition == CellGenerationDispositionV2::Stopped;
        self.request.predecessor.revision += 1;
    }
}

#[test]
fn synthetic_real_process_initializes_advances_commits_and_restores_all_modalities() -> TestResult {
    let assets = synthetic::assets()?;
    let mut harness = Harness::with_assets(
        assets.weights.clone(),
        assets.public.clone(),
        Arc::new(|| 10),
    )?;
    let initial = harness.propose(
        "synthetic-init",
        JointGenerationCommandV1::Init {
            seed: 17,
            sampler: JointGenerationSamplerV1::Mean,
        },
    )?;
    assert_eq!(initial.disposition, CellGenerationDispositionV2::Advanced);
    assert!(!initial.successor_state.is_empty());
    assert!(initial.output_delta.is_empty());
    assert_eq!(
        synthetic::state(&initial.successor_state, &[], &assets)?.steps,
        0
    );
    harness.adopt_for_next_fixture_request(&initial);
    let advanced = harness.propose(
        "synthetic-shared",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Shared,
        },
    )?;
    assert_eq!(advanced.disposition, CellGenerationDispositionV2::Advanced);
    assert_ne!(advanced.successor_state, initial.successor_state);
    assert!(advanced.output_delta.is_empty());
    harness.adopt_for_next_fixture_request(&advanced);
    let partial = harness.propose(
        "synthetic-audio-prefix",
        JointGenerationCommandV1::Commit {
            modality: JointGenerationModalityV1::Audio,
            units: 16,
        },
    )?;
    assert_eq!(partial.disposition, CellGenerationDispositionV2::Advanced);
    assert_eq!(
        synthetic::prefix(&partial.output_delta)?.cursors,
        [0, 16, 0, 0]
    );
    harness.adopt_for_next_fixture_request(&partial);
    let partial_snapshot = harness.request.predecessor.clone();
    assert_eq!(
        synthetic::state(&partial_snapshot.state, &partial_snapshot.prefix, &assets)?.cursors,
        [0, 16, 0, 0]
    );
    // Reopen the host's verified assets and executable, then pass only the
    // complete caller state/prefix to a fresh actual helper process.
    harness.worker = harness.reopened_worker()?;
    let stopped = harness.propose(
        "synthetic-stop",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    )?;
    assert_eq!(stopped.disposition, CellGenerationDispositionV2::Stopped);
    assert!(!stopped.output_delta.is_empty());
    let replay = harness.propose(
        "synthetic-stop",
        JointGenerationCommandV1::Advance {
            action: JointGenerationActionV1::Stop,
        },
    )?;
    assert_eq!(
        (&replay.successor_state, &replay.output_delta),
        (&stopped.successor_state, &stopped.output_delta)
    );
    harness.adopt_for_next_fixture_request(&stopped);
    let complete = synthetic::prefix(&harness.request.predecessor.prefix)?;
    assert_eq!(complete.cursors, synthetic::TOTAL_UNITS);
    assert_eq!(complete.bytes[0], vec![128; 768]);
    assert_eq!(complete.bytes[1], vec![0; 2048]);
    assert_eq!(complete.bytes[2], vec![128; 3072]);
    assert_eq!(complete.bytes[3], b"action=0;sound=0\n");
    let facts = synthetic::state(
        &stopped.successor_state,
        &harness.request.predecessor.prefix,
        &assets,
    )?;
    assert_eq!(facts.steps, 2);
    assert!(facts.stopped);
    assert_eq!(facts.cursors, synthetic::TOTAL_UNITS);
    assert!(
        harness
            .request
            .predecessor
            .prefix
            .starts_with(&partial_snapshot.prefix)
    );
    Ok(())
}

#[test]
fn actual_child_failure_retains_cost_without_new_state_or_output() -> TestResult {
    let harness = Harness::new(/*weights_bytes*/ 128, Arc::new(|| 10))?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Failed);
    assert_eq!(proposal.successor_state, harness.request.predecessor.state);
    assert_eq!(proposal.output_delta, Vec::<u8>::new());
    assert_eq!(proposal.request_digest, harness.request.digest()?);
    assert_eq!(proposal.runtime_digest, harness.manifest.runtime_digest);
    assert_eq!(proposal.cost.entries().len(), 1);
    let measured = &proposal.cost.entries()[0];
    assert_eq!(measured.outcome, CellCostOutcomeV2::Failed);
    assert!(measured.metrics.wall_micros.is_some_and(|value| value > 0));
    assert!(
        measured
            .metrics
            .communication_bytes
            .is_some_and(|value| value > 128)
    );
    assert_eq!(measured.metrics.cpu_micros, None);
    assert_eq!(measured.metrics.energy_microjoules, None);
    Ok(())
}

#[test]
fn asset_and_executable_path_replacement_cannot_change_opened_worker() -> TestResult {
    let harness = Harness::new(/*weights_bytes*/ 128, Arc::new(|| 10))?;
    fs::write(harness.directory.0.join("weights.hps"), b"replaced weights")?;
    fs::write(harness.directory.0.join("public.hps"), b"replaced input")?;
    fs::rename(
        harness.directory.0.join("proposal"),
        harness.directory.0.join("original-proposal"),
    )?;
    fs::write(
        harness.directory.0.join("proposal"),
        b"not the verified executable",
    )?;
    let proposal =
        harness
            .worker
            .execute(&harness.manifest, &harness.request, &AtomicBool::new(false))?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Failed);
    assert_eq!(proposal.runtime_digest, harness.manifest.runtime_digest);
    assert!(
        proposal.cost.entries()[0]
            .metrics
            .communication_bytes
            .is_some_and(|value| value > 128)
    );
    assert_eq!(harness.worker.weights, vec![1; 128]);
    let mut manifest = harness.manifest.clone();
    manifest.head = Some([99; 32]);
    assert_eq!(
        harness
            .worker
            .execute(&manifest, &harness.request, &AtomicBool::new(false)),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    Ok(())
}

#[test]
fn rejected_input_finishes_without_process_traffic_and_keeps_measured_validation() -> TestResult {
    let harness = Harness::new(/*weights_bytes*/ 128, Arc::new(|| 10))?;
    for input in [
        b"not json".to_vec(),
        serde_json::to_vec(&JointGenerationInputV1 {
            public_digest: [66; 32],
            command: JointGenerationCommandV1::Init {
                seed: 17,
                sampler: JointGenerationSamplerV1::Mean,
            },
        })?,
    ] {
        let mut request = harness.request.clone();
        request.input = input;
        let proposal =
            harness
                .worker
                .execute(&harness.manifest, &request, &AtomicBool::new(false))?;
        assert_eq!(proposal.disposition, CellGenerationDispositionV2::Rejected);
        assert_eq!(proposal.successor_state, request.predecessor.state);
        assert_eq!(proposal.output_delta, Vec::<u8>::new());
        assert_eq!(proposal.cost.entries().len(), 1);
        assert_eq!(proposal.cost.entries()[0].stage, CellCostStageV2::Codec);
        assert!(proposal.cost.entries()[0].metrics.wall_micros.is_some());
        assert_eq!(proposal.cost.entries()[0].metrics.cpu_micros, None);
    }
    Ok(())
}

#[test]
fn cancellation_deadline_and_clock_rollback_never_adopt_output() -> TestResult {
    let cancelled = Harness::new(/*weights_bytes*/ 128, Arc::new(|| 10))?;
    let proposal = cancelled.worker.execute(
        &cancelled.manifest,
        &cancelled.request,
        &AtomicBool::new(true),
    )?;
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(
        proposal.cost.entries()[0].metrics.communication_bytes,
        Some(0)
    );
    assert_eq!(proposal.cost.entries()[0].metrics.cpu_micros, None);
    let ticks = AtomicU64::new(10);
    let mut deadline = Harness::new(
        /*weights_bytes*/ 4_000_000,
        Arc::new(move || ticks.fetch_add(100, Ordering::SeqCst)),
    )?;
    deadline.request.deadline_micros = 100;
    let proposal = deadline.worker.execute(
        &deadline.manifest,
        &deadline.request,
        &AtomicBool::new(false),
    )?;
    assert_eq!(
        proposal.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert_eq!(proposal.successor_state, deadline.request.predecessor.state);
    assert_eq!(proposal.output_delta, Vec::<u8>::new());
    assert_eq!(proposal.cost.entries()[0].metrics.cpu_micros, None);
    let ticks = AtomicU64::new(10);
    let rolled_back_micros = 9;
    let rollback = Harness::new(
        /*weights_bytes*/ 4_000_000,
        Arc::new(move || ticks.swap(rolled_back_micros, Ordering::SeqCst)),
    )?;
    let proposal = rollback.worker.execute(
        &rollback.manifest,
        &rollback.request,
        &AtomicBool::new(false),
    )?;
    // The live clock moved backwards while the child was running; no actual
    // deadline elapsed. Retain this failed execution without claiming expiry.
    assert_eq!(proposal.disposition, CellGenerationDispositionV2::Failed);
    assert_eq!(proposal.successor_state, rollback.request.predecessor.state);
    assert!(proposal.output_delta.is_empty());
    assert_eq!(
        proposal.cost.entries()[0].outcome,
        CellCostOutcomeV2::Failed
    );
    assert_eq!(proposal.cost.entries()[0].metrics.cpu_micros, None);
    Ok(())
}

fn wire_response(request_digest: [u8; 32], stopped: u8, suffix: &[u8]) -> Vec<u8> {
    let mut bytes = b"HJRESV01".to_vec();
    bytes.extend(request_digest);
    bytes.push(stopped);
    for value in [1_u64, 2, 3, 4] {
        bytes.extend(value.to_le_bytes());
    }
    bytes.extend(3_u32.to_le_bytes());
    bytes.extend(b"HPS");
    bytes.extend(0_u32.to_le_bytes());
    bytes.extend(suffix);
    bytes.extend(Digest32::of_bytes(&bytes).to_string().bytes());
    bytes
}

#[test]
fn response_parser_binds_exact_digest_checksum_lengths_and_tail() -> TestResult {
    let digest = [9; 32];
    let valid = wire_response(digest, /*stopped*/ 1, &[]);
    let proposal = cell_joint_protocol::read_proposal(&valid, digest)?;
    assert_eq!(proposal.state, b"HPS");
    assert_eq!(proposal.delta, Vec::<u8>::new());
    assert!(proposal.stopped);
    assert_eq!(proposal.wall_micros, [1, 2, 3, 4]);
    let mut corrupted = valid.clone();
    corrupted[45] ^= 1;
    for bytes in [
        corrupted,
        wire_response(digest, /*stopped*/ 2, &[]),
        wire_response(digest, /*stopped*/ 1, b"trailing"),
        valid[..valid.len() - 1].to_vec(),
    ] {
        assert!(cell_joint_protocol::read_proposal(&bytes, digest).is_err());
    }
    assert!(cell_joint_protocol::read_proposal(&valid, [10; 32]).is_err());
    Ok(())
}
