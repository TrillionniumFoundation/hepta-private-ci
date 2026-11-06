//! Native, narrow Dataset -> terminal-value candidate coordinator.
//!
//! Reuses one existing shared LedgerWriter and Memory owner. It creates no
//! ledger, signer, database, parameter proposal or selected model. The bounded
//! job cache reconciles acknowledgement loss within this owner lifetime; it is
//! not the missing durable generic-iteration checkpoint owner.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::TryLockError;
use std::sync::mpsc::RecvTimeoutError;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Semaphore;
use tokio::sync::oneshot;

use crate::AgentdSharedReplayHostV1;
use crate::TerminalLearningErrorV1;
use crate::TerminalLearningReceiptV1;
use crate::TerminalLearningRequestV1;
use crate::TerminalLearningSourceLineageV1;
use crate::terminal_learning_types::TerminalLearningModeV1;

type JobResult = Result<TerminalLearningReceiptV1, TerminalLearningErrorV1>;

#[derive(Clone)]
enum JobState {
    Admitted,
    Computing,
    Computed(Box<JobResult>),
}
struct Job { digest: Digest32, state: JobState }

pub struct AgentdTerminalLearningOwnerV1 {
    agent_id: AgentId,
    producer_id: StableId,
    ledger: Arc<Mutex<LedgerWriter>>,
    replay: Arc<AgentdSharedReplayHostV1>,
    jobs: Arc<Mutex<BTreeMap<StableId, Job>>>,
    compute: Arc<Semaphore>,
    maximum_jobs: usize,
}

impl AgentdTerminalLearningOwnerV1 {
    /// The host shares its already-authorized product writer; no second durable
    /// writer is opened. Retained jobs never evict an unresolved operation.
    pub fn new(
        agent_id: AgentId,
        producer_id: StableId,
        ledger: Arc<Mutex<LedgerWriter>>,
        replay: Arc<AgentdSharedReplayHostV1>,
        maximum_jobs: usize,
    ) -> Result<Self, TerminalLearningErrorV1> {
        if !(1..=16).contains(&maximum_jobs) { return Err(TerminalLearningErrorV1::Capacity); }
        if replay.consumer_agent_id() != &agent_id { return Err(TerminalLearningErrorV1::WrongScope); }
        Ok(Self { agent_id, producer_id, ledger, replay,
            jobs: Arc::new(Mutex::new(BTreeMap::new())), compute: Arc::new(Semaphore::new(/*permits*/ 1)), maximum_jobs })
    }

    pub(crate) fn agent_id(&self) -> &AgentId { &self.agent_id }
    pub(crate) fn producer_id(&self) -> &StableId { &self.producer_id }

    /// Reconcile the same operation and exact signed dataset/training identity.
    /// A timeout does not prove that the bounded native fit did not run.
    pub async fn train(&self, request: TerminalLearningRequestV1, now: u64) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        request.job_digest(&self.agent_id, &self.producer_id)?;
        tokio::time::timeout(
            Duration::from_millis(request.budget.maximum_wall_milliseconds),
            self.execute(request, now, TerminalLearningModeV1::Train),
        ).await.map_err(|_| TerminalLearningErrorV1::CommitUncertain)?
    }

    /// Current owner-authenticated readback of an existing job. Missing state
    /// after a process restart is unknown, never proof of non-execution.
    pub async fn readback(&self, request: TerminalLearningRequestV1, now: u64) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        request.job_digest(&self.agent_id, &self.producer_id)?;
        tokio::time::timeout(
            Duration::from_millis(request.budget.maximum_wall_milliseconds),
            self.execute(request, now, TerminalLearningModeV1::Readback),
        ).await.map_err(|_| TerminalLearningErrorV1::CommitUncertain)?
    }

    async fn execute(&self, request: TerminalLearningRequestV1, now: u64, mode: TerminalLearningModeV1) -> JobResult {
        let digest = request.job_digest(&self.agent_id, &self.producer_id)?;
        let state = {
            let mut jobs = self.jobs.lock().map_err(|_| TerminalLearningErrorV1::Unavailable)?;
            if let Some(job) = jobs.get(&request.operation_id) {
                if job.digest != digest { return Err(TerminalLearningErrorV1::Conflict); }
                job.state.clone()
            } else {
                if matches!(mode, TerminalLearningModeV1::Readback) { return Err(TerminalLearningErrorV1::CommitUncertain); }
                if jobs.len() >= self.maximum_jobs { return Err(TerminalLearningErrorV1::Capacity); }
                check_deadline(&request, now)?;
                jobs.insert(request.operation_id.clone(), Job { digest, state: JobState::Admitted });
                JobState::Admitted
            }
        };
        match state {
            JobState::Computed(result) => return self.verify_readback(*result, &request, now).await,
            JobState::Computing => return Err(TerminalLearningErrorV1::CommitUncertain),
            JobState::Admitted if matches!(mode, TerminalLearningModeV1::Readback) => return Err(TerminalLearningErrorV1::CommitUncertain),
            JobState::Admitted => {}
        }
        check_deadline(&request, now)?;
        let admitted_at = Instant::now();
        let source = self.replay.training_source(&request.source_policy_id).await.map_err(owner_error)?;
        if source.source_support_digest().as_str() != request.expected_source_support_digest.to_string() {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        check_deadline(&request, projected_now(now, admitted_at))?;
        // Claim the operation and lane together. A concurrent retry observes
        // Computing (unknown), never a Busy result implying its work did not run.
        // No await separates this claim from submitting the native job.
        let claim = {
            let mut jobs = self.jobs.lock().map_err(|_| TerminalLearningErrorV1::Unavailable)?;
            let job = jobs.get_mut(&request.operation_id).ok_or(TerminalLearningErrorV1::CommitUncertain)?;
            match &job.state {
                JobState::Admitted => {
                    let permit = Arc::clone(&self.compute).try_acquire_owned()
                        .map_err(|_| TerminalLearningErrorV1::Busy)?;
                    job.state = JobState::Computing;
                    Ok(permit)
                }
                JobState::Computing => return Err(TerminalLearningErrorV1::CommitUncertain),
                JobState::Computed(result) => Err((**result).clone()),
            }
        };
        let permit = match claim {
            Ok(permit) => permit,
            Err(result) => return self.verify_readback(result, &request, projected_now(now, admitted_at)).await,
        };
        let ledger = Arc::clone(&self.ledger);
        let jobs = Arc::clone(&self.jobs);
        let native_request = request.clone();
        let (ready, waiting) = oneshot::channel();
        let (authorize, authorization) = std::sync::mpsc::sync_channel::<
            Result<SharedExperienceUseV1, TerminalLearningErrorV1>,
        >(/*bound*/ 1);
        let job = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let result = (|| {
                check_work_budget(&native_request, now, admitted_at)?;
                let _ = ready.send(());
                let remaining = Duration::from_millis(native_request.budget.maximum_wall_milliseconds)
                    .saturating_sub(admitted_at.elapsed());
                let source = authorization.recv_timeout(remaining).map_err(|error| match error {
                    RecvTimeoutError::Timeout => TerminalLearningErrorV1::DeadlineExceeded,
                    RecvTimeoutError::Disconnected => TerminalLearningErrorV1::CommitUncertain,
                })??;
                fit_native(&ledger, &native_request, digest, source, now, admitted_at)
            })();
            let mut jobs = jobs.lock().map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
            let entry = jobs.get_mut(&native_request.operation_id).ok_or(TerminalLearningErrorV1::CommitUncertain)?;
            if entry.digest != digest { return Err(TerminalLearningErrorV1::CommitUncertain); }
            entry.state = if matches!(result, Err(TerminalLearningErrorV1::Busy)) {
                // try_lock proved no ledger read or fit occurred.
                JobState::Admitted
            } else { JobState::Computed(Box::new(result.clone())) };
            result
        });
        waiting.await.map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        // Read permission after the native lane is ready. Cancellation drops
        // this sender, so its bounded blocking wait cannot outlive shutdown.
        let authorization = self.replay.revalidate_training_source(&source).await
            .map(|()| source).map_err(owner_error);
        authorize.try_send(authorization).map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        let result = tokio::time::timeout(Duration::from_millis(request.budget.maximum_wall_milliseconds), job)
            .await.map_err(|_| TerminalLearningErrorV1::CommitUncertain)?
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?;
        // An atomic native fit cannot be preempted. Over-budget results are
        // rejected; the single permit prevents overlapping abandoned jobs.
        self.verify_readback(result, &request, projected_now(now, admitted_at)).await
    }

    async fn verify_readback(&self, result: JobResult, request: &TerminalLearningRequestV1, now: u64) -> JobResult {
        let receipt = result?;
        let started = Instant::now();
        self.replay.revalidate_source(&receipt.candidate).await.map_err(owner_error)?;
        let ledger = match self.ledger.try_lock() {
            Ok(ledger) => ledger,
            Err(TryLockError::WouldBlock) => return Err(TerminalLearningErrorV1::Busy),
            Err(TryLockError::Poisoned(_)) => return Err(TerminalLearningErrorV1::Unavailable),
        };
        anchored_snapshot(&ledger, request.budget.maximum_ledger_records)?;
        if ledger.verifier().trust_digest() != receipt.evidence_trust_digest {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        ledger.revalidate_dataset_snapshot(receipt.candidate.dataset(), projected_now(now, started)).map_err(owner_error)?;
        if receipt.candidate.dataset().snapshot.dataset_digest != request.expected_dataset_digest
            || receipt.candidate.payload_digest() != Digest32::of_bytes(&receipt.payload)
        { return Err(TerminalLearningErrorV1::Conflict); }
        Ok(receipt)
    }
}

fn fit_native(
    ledger: &Mutex<LedgerWriter>,
    request: &TerminalLearningRequestV1,
    digest: Digest32,
    source: SharedExperienceUseV1,
    now: u64,
    started: Instant,
) -> JobResult {
    check_work_budget(request, now, started)?;
    let ledger = match ledger.try_lock() {
        Ok(ledger) => ledger,
        Err(TryLockError::WouldBlock) => return Err(TerminalLearningErrorV1::Busy),
        Err(TryLockError::Poisoned(_)) => return Err(TerminalLearningErrorV1::Unavailable),
    };
    anchored_snapshot(&ledger, request.budget.maximum_ledger_records)?;
    let dataset = ledger.freeze_dataset(request.dataset_plan.clone(), &request.dataset_evidence, projected_now(now, started)).map_err(owner_error)?;
    if dataset.snapshot.dataset_digest != request.expected_dataset_digest {
        return Err(TerminalLearningErrorV1::Conflict);
    }
    if dataset.snapshot.source_record_digests.len() > request.budget.maximum_dataset_records as usize {
        return Err(TerminalLearningErrorV1::Capacity);
    }
    check_work_budget(request, now, started)?;
    let source_lineage = TerminalLearningSourceLineageV1 {
        owner_id: source.owner_id().clone(), policy_id: source.policy_id().clone(),
        policy_revision: source.policy_revision(),
        support_digest: source.source_support_digest().as_str().parse().map_err(|_| TerminalLearningErrorV1::Conflict)?,
    };
    let candidate = AgentdSharedReplayHostV1::fit_from_source(
        source, &ledger, &dataset, request.profile.clone(), projected_now(now, started),
    ).map_err(owner_error)?;
    let payload = encode_tabular_payload_v1(candidate.artifact()).map_err(owner_error)?;
    check_work_budget(request, now, started)?;
    if payload.len() as u64 > request.budget.maximum_artifact_bytes {
        return Err(TerminalLearningErrorV1::Capacity);
    }
    ledger.revalidate_dataset_snapshot(&dataset, projected_now(now, started)).map_err(owner_error)?;
    check_work_budget(request, now, started)?;
    let elapsed_microseconds = u64::try_from(started.elapsed().as_micros()).map_err(|_| TerminalLearningErrorV1::Capacity)?;
    Ok(TerminalLearningReceiptV1 {
        operation_id: request.operation_id.clone(), job_digest: digest,
        source_records: u32::try_from(dataset.snapshot.source_record_digests.len()).map_err(|_| TerminalLearningErrorV1::Capacity)?,
        training_samples: u32::try_from(candidate.training_samples()).map_err(|_| TerminalLearningErrorV1::Capacity)?,
        candidate, payload, source: source_lineage, elapsed_microseconds,
        evidence_trust_digest: ledger.verifier().trust_digest(), authority: AuthorityPosture::DENY_ALL,
    })
}

fn anchored_snapshot(ledger: &LedgerWriter, maximum: u32) -> Result<LedgerSnapshot, TerminalLearningErrorV1> {
    let witness = ledger.witness_frontier().map_err(owner_error)?;
    if witness.anchor.sequence > u64::from(maximum) { return Err(TerminalLearningErrorV1::Capacity); }
    let snapshot = ledger.snapshot().map_err(owner_error)?;
    let sequence = snapshot.records().last().map_or(0, |record| record.sequence.get());
    if sequence != witness.anchor.sequence || snapshot.head_digest != witness.anchor.chain_digest {
        return Err(TerminalLearningErrorV1::CommitUncertain);
    }
    if let Some(checkpoint) = ledger.segmented_checkpoint().map_err(owner_error)?
        && (witness.segment != Some(checkpoint.segment) || witness.sealed != checkpoint.sealed)
    { return Err(TerminalLearningErrorV1::CommitUncertain); }
    Ok(snapshot)
}

fn check_work_budget(request: &TerminalLearningRequestV1, now: u64, started: Instant) -> Result<(), TerminalLearningErrorV1> {
    if started.elapsed() > Duration::from_millis(request.budget.maximum_wall_milliseconds) {
        return Err(TerminalLearningErrorV1::DeadlineExceeded);
    }
    check_deadline(request, projected_now(now, started))
}
fn check_deadline(request: &TerminalLearningRequestV1, now: u64) -> Result<(), TerminalLearningErrorV1> {
    if now >= request.deadline_unix_seconds || request.deadline_unix_seconds - now > 86_400 {
        return Err(TerminalLearningErrorV1::DeadlineExceeded);
    }
    Ok(())
}
fn projected_now(now: u64, started: Instant) -> u64 { now.saturating_add(started.elapsed().as_secs()) }
fn owner_error(error: impl std::fmt::Display) -> TerminalLearningErrorV1 { TerminalLearningErrorV1::Owner(error.to_string()) }
