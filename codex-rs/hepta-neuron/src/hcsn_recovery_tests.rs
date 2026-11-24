use super::*;
use crate::HcsnIntegrationV1;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Worker {
    weight: u64,
    backend: [u64; 5], // density, content, pending mass, release micros, absolute micros
    optimizer: u64,
    controller: u64,
    rng: u64,
    cost: u64,
    history: u64,
}

impl Worker {
    fn advance(&mut self) {
        self.rng = self
            .rng
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1);
        self.optimizer = (self.optimizer + self.rng % 7) / 2;
        self.controller += 1;
        self.backend[4] += 1;
        if self.backend[4] >= self.backend[3] {
            self.backend[0] += self.backend[2];
            self.backend[2] = 0;
        }
        self.backend[1] += self.backend[0] * self.weight + self.optimizer;
        self.cost += 3;
        self.history = self.history.wrapping_mul(31).wrapping_add(self.backend[1]);
    }

    fn snapshot(&self, binding: HcsnRecoveryBindingV2) -> HcsnResearchStateV2 {
        HcsnResearchStateV2 {
            binding,
            parameters: self.weight.to_be_bytes().to_vec(),
            backend: self.backend.iter().flat_map(|v| v.to_be_bytes()).collect(),
            optimizer: HcsnOptimizerStateV2::Snapshot(self.optimizer.to_be_bytes().to_vec()),
            controller: self.controller.to_be_bytes().to_vec(),
            rng: self.rng.to_be_bytes().to_vec(),
            cost_ledger: self.cost.to_be_bytes().to_vec(),
            history: self.history.to_be_bytes().to_vec(),
        }
    }
}

struct Codec;
fn number(bytes: &[u8]) -> Result<u64, HcsnRecoveryErrorV2> {
    Ok(u64::from_be_bytes(
        bytes.try_into().map_err(|_| HcsnRecoveryErrorV2::Backend)?,
    ))
}
impl HcsnResearchStateCodecV2 for Codec {
    type State = Worker;
    fn schema_digest(&self) -> Digest32 {
        Digest32::of_bytes(
            b"fixture.v2: u64 weight; 5 backend fields; optimizer/controller/rng/cost/history",
        )
    }
    fn restore_complete_state(
        &self,
        snapshot: &HcsnResearchStateV2,
        clock: &HcsnClockCheckpointV1,
        profile: &HcsnTimeProfileV1,
    ) -> Result<Worker, HcsnRecoveryErrorV2> {
        if snapshot.backend.len() != 40
            || !matches!(profile.integration, HcsnIntegrationV1::PopulationAge { .. })
        {
            return Err(HcsnRecoveryErrorV2::Backend);
        }
        let mut backend = [0; 5];
        for (value, bytes) in backend.iter_mut().zip(snapshot.backend.chunks_exact(8)) {
            *value = number(bytes)?;
        }
        if backend[4] != clock.last_micros() || (backend[2] > 0 && backend[3] <= backend[4]) {
            return Err(HcsnRecoveryErrorV2::Backend);
        }
        let optimizer = match &snapshot.optimizer {
            HcsnOptimizerStateV2::Snapshot(bytes) => number(bytes)?,
            HcsnOptimizerStateV2::NotUsed => return Err(HcsnRecoveryErrorV2::Backend),
        };
        Ok(Worker {
            weight: number(&snapshot.parameters)?,
            backend,
            optimizer,
            controller: number(&snapshot.controller)?,
            rng: number(&snapshot.rng)?,
            cost: number(&snapshot.cost_ledger)?,
            history: number(&snapshot.history)?,
        })
    }
}

fn fixture() -> (
    Worker,
    HcsnResearchStateV2,
    HcsnRecoveryContextV2,
    HcsnClockCheckpointV1,
) {
    let mut worker = Worker {
        weight: 2,
        backend: [1, 0, 4, 5, 0],
        optimizer: 3,
        controller: 0,
        rng: 7,
        cost: 0,
        history: 0,
    };
    for _ in 0..3 {
        worker.advance();
    }
    let digest = Digest32::of_bytes(b"retained admitted context");
    let binding = HcsnRecoveryBindingV2 {
        request_digest: digest,
        base_checkpoint_digest: digest,
        code_digest: digest,
        dataset_digest: digest,
        runtime_digest: digest,
        backend_state_schema_digest: Codec.schema_digest(),
        parameter_mask_digest: digest,
        learning_rule_digest: digest,
    };
    let snapshot = worker.snapshot(binding);
    let profile = HcsnTimeProfileV1 {
        maximum_gap_micros: 100,
        forecast_horizon_micros: 20,
        integration: HcsnIntegrationV1::PopulationAge {
            max_step_micros: 10,
            max_substeps: 16,
        },
    };
    let identity = HcsnClockIdentityV1 {
        clock_epoch: digest,
        scope_digest: digest,
        generation: checked(Generation::new(1)),
        writer_epoch: 1,
        model_digest: Digest32::of_bytes(&snapshot.parameters),
    };
    let clock = checked(HcsnClockCheckpointV1::initial(
        &profile,
        identity,
        /*last_micros*/ 3,
        Digest32::of_bytes(&checked(snapshot.encode())),
    ));
    let context = HcsnRecoveryContextV2 {
        profile,
        identity,
        binding,
        checkpoint_digest: clock.digest(),
    };
    (worker, snapshot, context, clock)
}

#[test]
fn complete_restore_matches_continuation_across_pending_release_and_learning_steps() {
    let (mut uninterrupted, snapshot, context, clock) = fixture();
    let restored = checked(restore_hcsn_research_state_v2(
        &context,
        &checked(clock.encode()),
        &checked(snapshot.encode()),
        &Codec,
    ));
    assert_eq!(
        restored,
        HcsnRestoredResearchStateV2 {
            clock,
            state: uninterrupted.clone()
        }
    );
    let mut resumed = restored.state;
    for _ in 0..5 {
        uninterrupted.advance();
        resumed.advance();
    }
    assert_eq!(resumed, uninterrupted);
    assert_eq!(resumed.backend[2], 0);
}

#[test]
fn all_state_components_are_custodied_and_changed_contexts_fail() {
    let (_, snapshot, context, clock) = fixture();
    let clock_bytes = checked(clock.encode());
    for index in 0..7 {
        let mut changed = snapshot.clone();
        let optimizer = match &mut changed.optimizer {
            HcsnOptimizerStateV2::Snapshot(bytes) => bytes,
            HcsnOptimizerStateV2::NotUsed => panic!("fixture optimizer"),
        };
        let parts = [
            &mut changed.parameters,
            &mut changed.backend,
            optimizer,
            &mut changed.controller,
            &mut changed.rng,
            &mut changed.cost_ledger,
            &mut changed.history,
        ];
        parts[index][0] ^= 1;
        assert_eq!(
            restore_hcsn_research_state_v2(
                &context,
                &clock_bytes,
                &checked(changed.encode()),
                &Codec
            ),
            Err(HcsnRecoveryErrorV2::StateMismatch)
        );
    }
    for index in 0..8 {
        let mut changed = context.clone();
        let b = &mut changed.binding;
        let parts = [
            &mut b.request_digest,
            &mut b.base_checkpoint_digest,
            &mut b.code_digest,
            &mut b.dataset_digest,
            &mut b.runtime_digest,
            &mut b.backend_state_schema_digest,
            &mut b.parameter_mask_digest,
            &mut b.learning_rule_digest,
        ];
        *parts[index] = Digest32::of_bytes(b"other admitted context");
        assert_eq!(
            restore_hcsn_research_state_v2(
                &changed,
                &clock_bytes,
                &checked(snapshot.encode()),
                &Codec
            ),
            Err(HcsnRecoveryErrorV2::Binding)
        );
    }
}

#[test]
fn malformed_state_is_rejected_before_backend_restore() {
    let (_, mut snapshot, _, _) = fixture();
    let bytes = checked(snapshot.encode());
    for end in [0, MAGIC.len(), bytes.len() - 1] {
        assert_eq!(
            HcsnResearchStateV2::decode(&bytes[..end]),
            Err(HcsnRecoveryErrorV2::Format)
        );
    }
    let mut trailing = bytes;
    trailing.push(0);
    assert_eq!(
        HcsnResearchStateV2::decode(&trailing),
        Err(HcsnRecoveryErrorV2::Format)
    );
    snapshot.history.clear();
    assert_eq!(snapshot.encode(), Err(HcsnRecoveryErrorV2::Format));
}

#[test]
fn backend_schema_validation_is_required_even_for_a_consistently_hashed_container() {
    let (_, mut snapshot, mut context, _) = fixture();
    snapshot.optimizer = HcsnOptimizerStateV2::NotUsed;
    let bytes = checked(snapshot.encode());
    let clock = checked(HcsnClockCheckpointV1::initial(
        &context.profile,
        context.identity,
        /*last_micros*/ 3,
        Digest32::of_bytes(&bytes),
    ));
    context.checkpoint_digest = clock.digest();
    assert_eq!(
        restore_hcsn_research_state_v2(&context, &checked(clock.encode()), &bytes, &Codec),
        Err(HcsnRecoveryErrorV2::Backend)
    );
    snapshot.parameters[0] ^= 1;
    let bytes = checked(snapshot.encode());
    let clock = checked(HcsnClockCheckpointV1::initial(
        &context.profile,
        context.identity,
        /*last_micros*/ 3,
        Digest32::of_bytes(&bytes),
    ));
    context.checkpoint_digest = clock.digest();
    assert_eq!(
        restore_hcsn_research_state_v2(&context, &checked(clock.encode()), &bytes, &Codec),
        Err(HcsnRecoveryErrorV2::Binding)
    );
}

#[test]
fn consistently_hashed_state_with_incompatible_clock_or_profile_is_rejected() {
    let (_, mut snapshot, mut context, _) = fixture();
    snapshot.backend[32..40].copy_from_slice(&4_u64.to_be_bytes());
    let bytes = checked(snapshot.encode());
    let clock = checked(HcsnClockCheckpointV1::initial(
        &context.profile,
        context.identity,
        /*last_micros*/ 3,
        Digest32::of_bytes(&bytes),
    ));
    context.checkpoint_digest = clock.digest();
    assert_eq!(
        restore_hcsn_research_state_v2(&context, &checked(clock.encode()), &bytes, &Codec),
        Err(HcsnRecoveryErrorV2::Backend)
    );
    snapshot.backend[32..40].copy_from_slice(&3_u64.to_be_bytes());
    let bytes = checked(snapshot.encode());
    context.profile.integration = HcsnIntegrationV1::ValueKernel;
    let clock = checked(HcsnClockCheckpointV1::initial(
        &context.profile,
        context.identity,
        /*last_micros*/ 3,
        Digest32::of_bytes(&bytes),
    ));
    context.checkpoint_digest = clock.digest();
    assert_eq!(
        restore_hcsn_research_state_v2(&context, &checked(clock.encode()), &bytes, &Codec),
        Err(HcsnRecoveryErrorV2::Backend)
    );
}
