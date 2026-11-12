//! Measured native phases for Root's fixed, unpublished B benchmark. This
//! meter records thread CPU and monotonic wall observations, not authority.
//! Accounting/clock probes and appending their own records are excluded by the
//! explicit common contract; no absent physical energy measurement becomes 0.

use super::*;

pub(crate) fn original_q24_benchmark_meter_contract() -> Digest32 {
    Digest32::of_bytes(b"hepta.root.b.q24-meter.v1;thread-cpu-clock;monotonic-wall;exclusive-native-phases;private-output-readback;no-training-routing-planning-critic-queue-network;before-final-holdout;exclude-meter-probes-and-cost-record-writes")
}

pub(crate) struct OriginalQ24BenchmarkMeterV1 {
    cost: CellTaskCostV2,
    sequence: u64,
    not_send: std::marker::PhantomData<std::rc::Rc<()>>,
}

impl OriginalQ24BenchmarkMeterV1 {
    pub(crate) fn new(identity: CellTaskCostIdentityV2) -> Result<Self, CellGenerationErrorV2> {
        Ok(Self {
            cost: CellTaskCostV2::new(identity)
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?,
            sequence: 0,
            not_send: std::marker::PhantomData,
        })
    }

    pub(crate) fn measure<T>(
        &mut self,
        stage: CellCostStageV2,
        work: impl FnOnce() -> Result<T, CellGenerationErrorV2>,
    ) -> Result<T, CellGenerationErrorV2> {
        let cpu = thread_cpu_micros()?;
        let started = Instant::now();
        let result = work();
        let wall = u64::try_from(started.elapsed().as_micros())
            .map_err(|_| CellGenerationErrorV2::Capacity)?;
        let cpu = thread_cpu_micros()?
            .checked_sub(cpu)
            .ok_or(CellGenerationErrorV2::Unavailable)?;
        self.record(
            stage,
            if result.is_ok() {
                CellCostOutcomeV2::Succeeded
            } else {
                CellCostOutcomeV2::Failed
            },
            wall,
            cpu,
        )?;
        result
    }

    /// These stages perform no work in this fixed synchronous native benchmark:
    /// no optimization, dynamic route, planner, critic, queue or external send.
    /// Training history is separately signed in the comparison contract.
    pub(crate) fn record_fixed_absent_phases(&mut self) -> Result<(), CellGenerationErrorV2> {
        for stage in [
            CellCostStageV2::Routing,
            CellCostStageV2::Training,
            CellCostStageV2::Planning,
            CellCostStageV2::Critic,
            CellCostStageV2::Queue,
            CellCostStageV2::Communication,
        ] {
            self.record(
                stage,
                CellCostOutcomeV2::Succeeded,
                /*wall*/ 0,
                /*cpu*/ 0,
            )?;
        }
        Ok(())
    }

    fn record(
        &mut self,
        stage: CellCostStageV2,
        outcome: CellCostOutcomeV2,
        wall: u64,
        cpu: u64,
    ) -> Result<(), CellGenerationErrorV2> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(CellGenerationErrorV2::Capacity)?;
        let identity = self.cost.identity();
        self.cost
            .record(CellCostEntryV2 {
                event_id: Digest32::of_parts(&[
                    b"hepta.root.b.native-cost.v1\0",
                    &identity.task_digest,
                    &identity.source_digest,
                    &self.sequence.to_be_bytes(),
                ])
                .into_array(),
                identity,
                stage,
                outcome,
                accounting: CellCostAccountingV2::Exclusive,
                metrics: CellCostMetricsV2 {
                    wall_micros: Some(wall),
                    cpu_micros: Some(cpu),
                    ..CellCostMetricsV2::default()
                },
            })
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        Ok(())
    }

    pub(crate) fn observations(&self) -> &CellTaskCostV2 {
        &self.cost
    }
}

impl CellQ24GenerationWorkerV1 {
    pub(crate) fn execute_original_root_benchmark(
        &self,
        request: &CellGenerationRequestV2,
        meter: &mut OriginalQ24BenchmarkMeterV1,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        let manifest = &self.manifest;
        let live = || {
            let now = (self.clock)();
            if now == 0 || now < request.admitted_at_micros || now >= request.deadline_micros {
                return Err(CellGenerationErrorV2::Deadline);
            }
            Ok(())
        };
        live()?;
        let request_digest = request.digest()?;
        if request.predecessor.manifest_digest != manifest.digest()?
            || !request.predecessor.state.is_empty()
            || !request.predecessor.prefix.is_empty()
            || request.predecessor.stopped
            || meter.cost.identity()
                != (CellTaskCostIdentityV2 {
                    task_digest: request.task_digest,
                    source_digest: manifest.source_digest,
                })
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let input = meter.measure(CellCostStageV2::Codec, || {
            codec::input(&request.input, self.model.encoder.cols)
        })?;
        let encoded = meter.measure(CellCostStageV2::Encoder, || {
            Ok(self.model.encoder.apply(&input))
        })?;
        live()?;
        let heads = meter.measure(CellCostStageV2::Inference, || {
            let mut hidden = self.model.base.apply(&encoded);
            let apply = |adapter: &Option<Adapter>| {
                adapter.as_ref().map_or_else(
                    || vec![0; hidden.len()],
                    |adapter| adapter.up.apply(&adapter.down.apply(&encoded)),
                )
            };
            let organ = apply(&self.model.organ);
            let cell = apply(&self.model.cell);
            codec::combine(&mut hidden, &organ, &cell);
            Ok(self.model.heads.apply(&hidden))
        })?;
        live()?;
        let output = meter.measure(CellCostStageV2::Codec, || {
            let mut output = b"HQ24O001".to_vec();
            output.extend_from_slice(&((heads.len() / 2) as u16).to_le_bytes());
            for value in &heads {
                output.extend_from_slice(&value.to_le_bytes());
            }
            Ok(output)
        })?;
        live()?;
        Ok(CellGenerationProposalV2 {
            request_digest,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: Vec::new(),
            output_delta: output,
            disposition: CellGenerationDispositionV2::Stopped,
            cost: meter.cost.clone(),
        })
    }
}

fn thread_cpu_micros() -> Result<u64, CellGenerationErrorV2> {
    let mut sample = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: the kernel writes one live timespec; this clock is the current
    // thread's actual consumed CPU. This !Send meter cannot move across threads.
    if unsafe { libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID, &mut sample) } != 0
        || sample.tv_sec < 0
        || !(0..1_000_000_000).contains(&sample.tv_nsec)
    {
        return Err(CellGenerationErrorV2::Unavailable);
    }
    (sample.tv_sec as u64)
        .checked_mul(1_000_000)
        .and_then(|value| value.checked_add(sample.tv_nsec as u64 / 1000))
        .ok_or(CellGenerationErrorV2::Capacity)
}
