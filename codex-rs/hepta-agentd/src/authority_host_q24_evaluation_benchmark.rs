//! Execute only fresh preregistered unpublished Cell outputs, then surrender
//! both native writers and observe their actual complete physical cuts. A
//! retained cut is read without reopening a writer or repeating computation.

use std::io;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use super::deployment::OriginalBCellFiles;
use super::deployment::OriginalBInputs;
use super::protocol::OriginalBProtocolData;
use super::record::OriginalBEnrollment;
use crate::LoadedCellQ24ModelV1;
use crate::cell_composed_q24::OriginalQ24BenchmarkMeterV1;
use crate::cell_composed_q24::original_q24_benchmark_meter_contract;

pub(super) fn prepare_original_cells(
    files: &mut OriginalBInputs,
    enrollment: &mut OriginalBEnrollment,
    training: &LearningIterationSnapshotV1,
    protocol: &OriginalBProtocolData,
    end: Instant,
) -> io::Result<()> {
    if enrollment.cell_images.is_some() {
        return restore_original_cells(files, enrollment, training, protocol);
    }
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
        .map_err(io::Error::other)?;
    let candidate = coordinator
        .candidate()
        .ok_or_else(|| io::Error::other("original candidate missing"))?;
    let baseline = &training.request.selected_bundle;
    let work = original_training_work(files, enrollment, training)?;
    let (registration, _, _) = protocol.plans(training, &work)?;
    if registration
        .comparison
        .cost_coverage
        .metering_contract_digest
        != original_q24_benchmark_meter_contract().into_array()
        || files.fixed_expert.config.generation.task_digest
            != Digest32::of_parts(&[
                b"hepta.root.b.benchmark-task.v1\0",
                training.request.evaluation_profile.as_array(),
                protocol.benchmark_input().as_array(),
            ])
            .into_array()
    {
        return Err(io::Error::other(
            "original B native metering or benchmark task differs",
        ));
    }
    let heads = files
        .candidate_data
        .require_digest(candidate.components.heads, 32_780)?;
    let template = files.fixed_expert.config.generation.clone();
    let mut candidate_meter =
        OriginalQ24BenchmarkMeterV1::new(identity(&template)).map_err(io::Error::other)?;
    let (model, config) = candidate_meter
        .measure(CellCostStageV2::Recovery, || {
            files
                .model
                .candidate(&template, baseline, candidate, &heads)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)
        })
        .map_err(io::Error::other)?;
    files.candidate.config.generation = config;
    if enrollment.realized_plan.is_some()
        || enrollment.completed_receipt.is_some()
        || enrollment.heads.is_some()
    {
        return Err(io::Error::other(
            "original B component preparation is incomplete",
        ));
    }
    let input = candidate_meter
        .measure(CellCostStageV2::Codec, || {
            files
                .model
                .input(protocol.benchmark_input())
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)
        })
        .map_err(io::Error::other)?;
    run_original_arm(
        &mut files.candidate,
        candidate,
        model,
        input,
        candidate_meter,
        end,
    )?;
    let mut baseline_meter =
        OriginalQ24BenchmarkMeterV1::new(identity(&template)).map_err(io::Error::other)?;
    let model = baseline_meter
        .measure(CellCostStageV2::Recovery, || {
            files
                .model
                .load_baseline(baseline)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)
        })
        .map_err(io::Error::other)?;
    let input = baseline_meter
        .measure(CellCostStageV2::Codec, || {
            files
                .model
                .input(protocol.benchmark_input())
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)
        })
        .map_err(io::Error::other)?;
    run_original_arm(
        &mut files.fixed_expert,
        baseline,
        model,
        input,
        baseline_meter,
        end,
    )?;
    enrollment.cell_images = Some(physical_images(files)?);
    require_original_cells(files, enrollment, training, protocol)
}

pub(super) fn restore_original_cells(
    files: &mut OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    training: &LearningIterationSnapshotV1,
    protocol: &OriginalBProtocolData,
) -> io::Result<()> {
    let expected = enrollment
        .cell_images
        .as_ref()
        .ok_or_else(|| io::Error::other("original B components were never prepared"))?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
        .map_err(io::Error::other)?;
    let candidate = coordinator
        .candidate()
        .ok_or_else(|| io::Error::other("original B candidate missing"))?;
    let heads = files
        .candidate_data
        .require_digest(candidate.components.heads, 32_780)?;
    let (_, config) = files.model.candidate(
        &files.fixed_expert.config.generation,
        &training.request.selected_bundle,
        candidate,
        &heads,
    )?;
    files.candidate.config.generation = config;
    if physical_images(files)? != *expected {
        return Err(io::Error::other("original B component history differs"));
    }
    files
        .candidate
        .journal
        .relinquish_writer_for_observation()?;
    files
        .candidate
        .witness
        .relinquish_writer_for_observation()?;
    files
        .fixed_expert
        .journal
        .relinquish_writer_for_observation()?;
    files
        .fixed_expert
        .witness
        .relinquish_writer_for_observation()?;
    require_original_cells(files, enrollment, training, protocol)
}

pub(super) fn require_original_cells(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    training: &LearningIterationSnapshotV1,
    protocol: &OriginalBProtocolData,
) -> io::Result<()> {
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
        .map_err(io::Error::other)?;
    let candidate = coordinator
        .candidate()
        .ok_or_else(|| io::Error::other("original B candidate missing"))?;
    files
        .candidate_data
        .require_digest(candidate.components.heads, 32_780)?;
    files
        .model
        .require_baseline(&training.request.selected_bundle)?;
    files.model.input(protocol.benchmark_input())?;
    let work = original_training_work(files, enrollment, training)?;
    protocol.plans(training, &work)?;
    if enrollment.cell_images.as_ref() != Some(&physical_images(files)?) {
        return Err(io::Error::other("original B component images changed"));
    }
    for cell in [&files.candidate, &files.fixed_expert] {
        let observed = cell.observer()?.observe().map_err(io::Error::other)?;
        if !observed.is_drained()
            || observed.observation().pending_request_digest().is_some()
            || observed.observation().pending_output().is_some()
        {
            return Err(io::Error::other("original B component is unresolved"));
        }
    }
    Ok(())
}

pub(super) fn original_training_work(
    files: &OriginalBInputs,
    enrollment: &OriginalBEnrollment,
    training: &LearningIterationSnapshotV1,
) -> io::Result<crate::cell_composed_q24::OriginalQ24TrainingWorkObservedV1> {
    let work = enrollment
        .original_training_work
        .as_ref()
        .ok_or_else(|| io::Error::other("original authenticated Training work was not retained"))?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(training.clone())
        .map_err(io::Error::other)?;
    let candidate = coordinator
        .candidate()
        .ok_or_else(|| io::Error::other("original Training candidate absent"))?;
    let heads = files
        .candidate_data
        .require_digest(candidate.components.heads, 32_780)?;
    let actual = files
        .model
        .observe_original_training_work(work, training, &heads)?;
    files
        .candidate_data
        .require_digest(candidate.components.heads, 32_780)?;
    Ok(actual)
}

fn run_original_arm(
    files: &mut OriginalBCellFiles,
    bundle: &CellCompatibilityBundleV1,
    model: LoadedCellQ24ModelV1,
    input: Vec<u8>,
    mut meter: OriginalQ24BenchmarkMeterV1,
    end: Instant,
) -> io::Result<()> {
    let config = files.config.generation.clone();
    if Instant::now() >= end
        || config.manifest.max_step_cost_entries < 16
        || files.config.journal_records < 64
    {
        return Err(io::Error::other(
            "original bounded B component capacity or end differs",
        ));
    }
    files.journal.require_empty()?;
    files.witness.require_empty()?;
    let mut journal = meter
        .measure(CellCostStageV2::Persistence, || {
            let witness = FileAnchorWitnessStore::open(
                files
                    .witness
                    .take_original_writer()
                    .map_err(|_| CellGenerationErrorV2::Unavailable)?,
                files.config.witness_scope,
                files.config.witness_generation,
                files.config.witness_records,
            )
            .map_err(|_| CellGenerationErrorV2::Unavailable)?;
            CellGenerationJournalV2::open(
                files
                    .journal
                    .take_original_writer()
                    .map_err(|_| CellGenerationErrorV2::Unavailable)?,
                witness,
                config.clone(),
                files.config.journal_records,
            )
        })
        .map_err(io::Error::other)?;
    let admitted = monotonic_micros().map_err(io::Error::other)?;
    let remaining = end
        .checked_duration_since(Instant::now())
        .ok_or_else(|| io::Error::other("original B frame expired"))?;
    let deadline = admitted
        .checked_add(u64::try_from(remaining.as_micros()).map_err(io::Error::other)?)
        .ok_or_else(|| io::Error::other("B original deadline overflow"))?;
    let request = CellGenerationRequestV2 {
        operation_id: format!("original-b:{}", bundle.digest().map_err(io::Error::other)?),
        task_digest: config.task_digest,
        source_frontier: config.source_frontier,
        predecessor: journal.snapshot().map_err(io::Error::other)?.clone(),
        input,
        admitted_at_micros: admitted,
        deadline_micros: deadline,
    };
    meter
        .measure(CellCostStageV2::Persistence, || {
            if journal
                .admit(request.clone(), monotonic_micros()?)?
                .is_some()
            {
                return Err(CellGenerationErrorV2::Conflict);
            }
            journal.observe_dispatch_time(request.digest()?, monotonic_micros()?)
        })
        .map_err(io::Error::other)?;
    let worker = Arc::new(model)
        .shared_worker(
            bundle,
            config.manifest.clone(),
            Arc::new(|| monotonic_micros().unwrap_or(u64::MAX)),
        )
        .map_err(io::Error::other)?;
    let proposal = worker
        .execute_original_root_benchmark(&request, &mut meter)
        .map_err(io::Error::other)?;
    let output = proposal.output_delta.clone();
    meter
        .measure(CellCostStageV2::Persistence, || {
            let receipt = journal.commit(proposal, monotonic_micros()?)?;
            if receipt.disposition != CellGenerationDispositionV2::Stopped {
                return Err(CellGenerationErrorV2::Conflict);
            }
            Ok(())
        })
        .map_err(io::Error::other)?;
    let chunk = meter
        .measure(CellCostStageV2::Evaluation, || {
            let chunk = journal
                .pending_output()?
                .cloned()
                .ok_or(CellGenerationErrorV2::Pending)?;
            if chunk.request_digest != request.digest()?
                || chunk.bytes != output
                || !chunk.bytes.starts_with(b"HQ24O001")
            {
                return Err(CellGenerationErrorV2::Conflict);
            }
            Ok(chunk)
        })
        .map_err(io::Error::other)?;
    meter
        .measure(CellCostStageV2::Persistence, || {
            let acknowledgement = Digest32::of_parts(&[
                b"hepta.root.b.private-native-read.v1\0",
                &chunk.request_digest,
                &chunk.bytes,
            ])
            .into_array();
            journal.acknowledge(
                chunk,
                acknowledgement,
                CellTaskCostV2::new(identity(&config))
                    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            )?;
            journal.drain()
        })
        .map_err(io::Error::other)?;
    meter
        .record_fixed_absent_phases()
        .map_err(io::Error::other)?;
    // Entries already included in the native proposal replay identically.
    for entry in meter.observations().entries() {
        journal
            .record_cost(entry.clone())
            .map_err(io::Error::other)?;
    }
    if !journal.is_drained().map_err(io::Error::other)? || Instant::now() >= end {
        return Err(io::Error::other(
            "original B component did not finish before its original end",
        ));
    }
    drop(journal);
    files.observer()?.observe().map_err(io::Error::other)?;
    Ok(())
}

fn identity(config: &CellGenerationConfigV2) -> CellTaskCostIdentityV2 {
    CellTaskCostIdentityV2 {
        task_digest: config.task_digest,
        source_digest: config.manifest.source_digest,
    }
}

fn physical_images(files: &OriginalBInputs) -> io::Result<Vec<[u8; 32]>> {
    [
        &files.candidate.journal,
        &files.candidate.witness,
        &files.fixed_expert.journal,
        &files.fixed_expert.witness,
    ]
    .into_iter()
    .map(|file| {
        file.read_stable(1_048_576)
            .map(|bytes| Digest32::of_bytes(&bytes).into_array())
    })
    .collect()
}

fn monotonic_micros() -> Result<u64, CellGenerationErrorV2> {
    let mut sample = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: the kernel writes one live timespec for the actual monotonic clock.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut sample) } != 0
        || sample.tv_sec < 0
        || !(0..1_000_000_000).contains(&sample.tv_nsec)
    {
        return Err(CellGenerationErrorV2::Unavailable);
    }
    (sample.tv_sec as u64)
        .checked_mul(1_000_000)
        .and_then(|v| v.checked_add(sample.tv_nsec as u64 / 1000))
        .filter(|v| *v != 0)
        .ok_or(CellGenerationErrorV2::Unavailable)
}
