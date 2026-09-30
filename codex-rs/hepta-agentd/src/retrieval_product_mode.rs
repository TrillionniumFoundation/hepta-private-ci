//! Host-fixed retrieval delivery. No request can select its own treatment arm.
//!
//! Canary allocation and shadow structural ceilings are captured once from the
//! host-owned retrieval provider. They are bound into every routed lifecycle
//! identity, so changing rollout or budget policy invalidates in-flight reads.

use std::sync::Arc;

use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::memory::RetrievalExecutionContextV1;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_NODES;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SETTLING_STEPS;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SYNAPSES;
use codex_hepta_agent_components::memory_retrieval::MAX_GENERATION_BOUND_CANDIDATES;
use codex_hepta_agent_components::types::Digest32;

use crate::CognitiveRetrievalMode;
use crate::CurrentMemoryRetrievalContext;

const PPM_SCALE: u32 = 1_000_000;
const DEFAULT_CANARY_THRESHOLD_PPM: u32 = 50_000;
const DEFAULT_CANARY_COHORT_DOMAIN: &[u8] = b"hepta.retrieval.default-canary-cohort.v1";
const LEGACY_CANARY_DOMAIN: &[u8] = b"hepta.retrieval.canary-owner-cohort.v1";
const CANARY_DOMAIN: &[u8] = b"hepta.retrieval.canary-owner-cohort.v2";
const MODE_DOMAIN: &[u8] = b"hepta.retrieval.product-delivery-mode.v2";

#[derive(Clone, Debug)]
struct DeliveryPolicy {
    canary_policy_version: u8,
    canary_threshold_ppm: u32,
    canary_cohort_salt: Digest32,
    shadow_maximum_channel_candidates: u32,
    shadow_maximum_nodes: usize,
    shadow_maximum_synapses: usize,
    shadow_maximum_settling_steps: u8,
    validation_error: Option<String>,
}

impl DeliveryPolicy {
    fn capture(reader: &dyn CurrentMemoryRetrievalContext) -> Self {
        let mut policy = Self {
            canary_policy_version: reader.canary_policy_version(),
            canary_threshold_ppm: reader.canary_threshold_ppm(),
            canary_cohort_salt: reader.canary_cohort_salt(),
            shadow_maximum_channel_candidates: reader.shadow_maximum_channel_candidates(),
            shadow_maximum_nodes: reader.shadow_maximum_nodes(),
            shadow_maximum_synapses: reader.shadow_maximum_synapses(),
            shadow_maximum_settling_steps: reader.shadow_maximum_settling_steps(),
            validation_error: None,
        };
        policy.validation_error = policy.validate().err();
        policy
    }

    fn legacy_default() -> Self {
        let mut policy = Self {
            canary_policy_version: 1,
            canary_threshold_ppm: DEFAULT_CANARY_THRESHOLD_PPM,
            canary_cohort_salt: Digest32::of_bytes(DEFAULT_CANARY_COHORT_DOMAIN),
            shadow_maximum_channel_candidates: u32::try_from(MAX_GENERATION_BOUND_CANDIDATES)
                .unwrap_or(u32::MAX),
            shadow_maximum_nodes: MAX_ENGRAM_NODES,
            shadow_maximum_synapses: MAX_ENGRAM_SYNAPSES,
            shadow_maximum_settling_steps: MAX_ENGRAM_SETTLING_STEPS,
            validation_error: None,
        };
        policy.validation_error = policy.validate().err();
        policy
    }

    fn validate(&self) -> Result<(), String> {
        if !matches!(self.canary_policy_version, 1 | 2) {
            return Err("unsupported retrieval canary policy version".to_string());
        }
        if self.canary_threshold_ppm > PPM_SCALE {
            return Err("retrieval canary threshold exceeds one million ppm".to_string());
        }
        if self.canary_cohort_salt.is_zero() {
            return Err("retrieval canary cohort salt must be nonzero".to_string());
        }
        if self.canary_policy_version == 1
            && (self.canary_threshold_ppm != DEFAULT_CANARY_THRESHOLD_PPM
                || self.canary_cohort_salt != Digest32::of_bytes(DEFAULT_CANARY_COHORT_DOMAIN))
        {
            return Err("retrieval canary v1 policy must preserve its fixed cohort".to_string());
        }
        let maximum_candidates = u32::try_from(MAX_GENERATION_BOUND_CANDIDATES).unwrap_or(u32::MAX);
        if self.shadow_maximum_channel_candidates == 0
            || self.shadow_maximum_channel_candidates > maximum_candidates
        {
            return Err("retrieval shadow candidate budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_nodes == 0 || self.shadow_maximum_nodes > MAX_ENGRAM_NODES {
            return Err("retrieval shadow node budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_synapses == 0 || self.shadow_maximum_synapses > MAX_ENGRAM_SYNAPSES {
            return Err("retrieval shadow synapse budget is outside product bounds".to_string());
        }
        if self.shadow_maximum_settling_steps == 0
            || self.shadow_maximum_settling_steps > MAX_ENGRAM_SETTLING_STEPS
        {
            return Err(
                "retrieval shadow settling-step budget is outside product bounds".to_string(),
            );
        }
        Ok(())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.retrieval-delivery-policy.v2".to_vec();
        bytes.push(self.canary_policy_version);
        bytes.extend_from_slice(&self.canary_threshold_ppm.to_be_bytes());
        bytes.extend_from_slice(self.canary_cohort_salt.as_array());
        bytes.extend_from_slice(&self.shadow_maximum_channel_candidates.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.shadow_maximum_nodes)
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.extend_from_slice(
            &u64::try_from(self.shadow_maximum_synapses)
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        bytes.push(self.shadow_maximum_settling_steps);
        Digest32::of_bytes(&bytes)
    }
}

pub(crate) fn delivers_hnmf(mode: CognitiveRetrievalMode, owner: &AgentId) -> bool {
    delivers_hnmf_with_policy(mode, owner, &DeliveryPolicy::legacy_default())
}

fn delivers_hnmf_with_policy(
    mode: CognitiveRetrievalMode,
    owner: &AgentId,
    policy: &DeliveryPolicy,
) -> bool {
    if policy.validation_error.is_some() {
        // Required/canary must fail closed in acquire_context. Returning true
        // prevents invalid canary configuration from silently becoming a
        // compatibility delivery. Shadow remains non-exposure.
        return matches!(
            mode,
            CognitiveRetrievalMode::HnmfCanary | CognitiveRetrievalMode::HnmfRequired
        );
    }
    match mode {
        CognitiveRetrievalMode::Compatibility | CognitiveRetrievalMode::HnmfShadow => false,
        CognitiveRetrievalMode::HnmfRequired => true,
        CognitiveRetrievalMode::HnmfCanary => match policy.canary_policy_version {
            1 => in_legacy_canary_cohort(owner),
            2 => in_canary_cohort(
                owner,
                policy.canary_threshold_ppm,
                policy.canary_cohort_salt,
            ),
            _ => false,
        },
    }
}

fn in_legacy_canary_cohort(owner: &AgentId) -> bool {
    let mut bytes = LEGACY_CANARY_DOMAIN.to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    let digest = Digest32::of_bytes(&bytes);
    let hash = digest.as_array();
    u32::from_be_bytes([hash[0], hash[1], hash[2], hash[3]]) < u32::MAX / 20
}

fn in_canary_cohort(owner: &AgentId, threshold_ppm: u32, salt: Digest32) -> bool {
    if threshold_ppm == 0 || threshold_ppm > PPM_SCALE || salt.is_zero() {
        return false;
    }
    if threshold_ppm == PPM_SCALE {
        return true;
    }
    let mut bytes = CANARY_DOMAIN.to_vec();
    bytes.extend_from_slice(salt.as_array());
    bytes.extend_from_slice(owner.as_str().as_bytes());
    let digest = Digest32::of_bytes(&bytes);
    let hash = digest.as_array();
    let sample = u64::from_be_bytes([
        hash[0], hash[1], hash[2], hash[3], hash[4], hash[5], hash[6], hash[7],
    ]);
    let cutoff = (1_u128 << 64).saturating_mul(u128::from(threshold_ppm)) / u128::from(PPM_SCALE);
    u128::from(sample) < cutoff
}

pub(crate) fn route(
    mode: CognitiveRetrievalMode,
    reader: Arc<dyn CurrentMemoryRetrievalContext>,
) -> Arc<dyn CurrentMemoryRetrievalContext> {
    let policy = DeliveryPolicy::capture(reader.as_ref());
    Arc::new(ModeRoutedContext {
        mode,
        reader,
        policy,
    })
}

struct ModeRoutedContext {
    mode: CognitiveRetrievalMode,
    reader: Arc<dyn CurrentMemoryRetrievalContext>,
    policy: DeliveryPolicy,
}

impl ModeRoutedContext {
    fn bind_acquired_context(
        &self,
        owner: &AgentId,
        acquired: (RetrievalExecutionContextV1, Digest32, Option<u64>),
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        if let Some(error) = &self.policy.validation_error {
            return Err(error.clone());
        }
        let (context, state, deadline) = acquired;
        if state.is_zero() {
            return Err("retrieval mode cannot bind an empty lifecycle identity".to_string());
        }
        let delivers = delivers_hnmf_with_policy(self.mode, owner, &self.policy);
        if !delivers
            && matches!(
                self.mode,
                CognitiveRetrievalMode::HnmfShadow | CognitiveRetrievalMode::HnmfCanary
            )
        {
            validate_shadow_budget(&context, &self.policy)?;
        }
        let mut bytes = MODE_DOMAIN.to_vec();
        bytes.push(match self.mode {
            CognitiveRetrievalMode::Compatibility => 0,
            CognitiveRetrievalMode::HnmfShadow => 1,
            CognitiveRetrievalMode::HnmfCanary => 2,
            CognitiveRetrievalMode::HnmfRequired => 3,
        });
        bytes.extend_from_slice(self.policy.digest().as_array());
        bytes.extend_from_slice(state.as_array());
        Ok((context, Digest32::of_bytes(&bytes), deadline))
    }
}

impl CurrentMemoryRetrievalContext for ModeRoutedContext {
    fn delivers_hnmf(&self, owner: &AgentId) -> bool {
        delivers_hnmf_with_policy(self.mode, owner, &self.policy)
    }

    fn canary_policy_version(&self) -> u8 {
        self.policy.canary_policy_version
    }

    fn canary_threshold_ppm(&self) -> u32 {
        self.policy.canary_threshold_ppm
    }

    fn canary_cohort_salt(&self) -> Digest32 {
        self.policy.canary_cohort_salt
    }

    fn shadow_maximum_channel_candidates(&self) -> u32 {
        self.policy.shadow_maximum_channel_candidates
    }

    fn shadow_maximum_nodes(&self) -> usize {
        self.policy.shadow_maximum_nodes
    }

    fn shadow_maximum_synapses(&self) -> usize {
        self.policy.shadow_maximum_synapses
    }

    fn shadow_maximum_settling_steps(&self) -> u8 {
        self.policy.shadow_maximum_settling_steps
    }

    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String> {
        self.acquire_context(owner, body_generation)
            .map(|(context, _, _)| context)
    }

    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: std::time::Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        crate::check_retrieval_deadline(deadline)?;
        if let Some(error) = &self.policy.validation_error {
            return Err(error.clone());
        }
        let acquired = self
            .reader
            .acquire_context_before(owner, body_generation, deadline)?;
        crate::check_retrieval_deadline(deadline)?;
        self.bind_acquired_context(owner, acquired)
    }

    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        if let Some(error) = &self.policy.validation_error {
            return Err(error.clone());
        }
        let acquired = self.reader.acquire_context(owner, body_generation)?;
        self.bind_acquired_context(owner, acquired)
    }
}

fn validate_shadow_budget(
    context: &RetrievalExecutionContextV1,
    policy: &DeliveryPolicy,
) -> Result<(), String> {
    let declared_channel_candidates = context
        .retrieval_policy
        .channel_weights
        .iter()
        .map(|row| row.maximum_candidates)
        .max()
        .unwrap_or(0);
    validate_shadow_shape(
        declared_channel_candidates,
        context.engram_snapshot.nodes.len(),
        context.engram_snapshot.synapses.len(),
        context.dynamics_policy.maximum_settling_steps,
        policy,
    )
}

fn validate_shadow_shape(
    declared_channel_candidates: u32,
    nodes: usize,
    synapses: usize,
    settling_steps: u8,
    policy: &DeliveryPolicy,
) -> Result<(), String> {
    if declared_channel_candidates > policy.shadow_maximum_channel_candidates {
        return Err("retrieval shadow candidate budget exceeded".to_string());
    }
    if nodes > policy.shadow_maximum_nodes {
        return Err("retrieval shadow node budget exceeded".to_string());
    }
    if synapses > policy.shadow_maximum_synapses {
        return Err("retrieval shadow synapse budget exceeded".to_string());
    }
    if settling_steps > policy.shadow_maximum_settling_steps {
        return Err("retrieval shadow settling-step budget exceeded".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn owner(value: &str) -> AgentId {
        AgentId::parse(value).expect("valid owner")
    }

    #[test]
    fn legacy_canary_uses_the_original_fixed_cohort() {
        let owner = owner("00000000-0000-4000-8000-000000000001");
        let mut bytes = LEGACY_CANARY_DOMAIN.to_vec();
        bytes.extend_from_slice(owner.as_str().as_bytes());
        let digest = Digest32::of_bytes(&bytes);
        let hash = digest.as_array();
        let expected = u32::from_be_bytes([hash[0], hash[1], hash[2], hash[3]]) < u32::MAX / 20;
        assert_eq!(in_legacy_canary_cohort(&owner), expected);
        assert_eq!(
            delivers_hnmf(CognitiveRetrievalMode::HnmfCanary, &owner),
            expected
        );
    }

    #[test]
    fn zero_and_full_canary_thresholds_are_exact() {
        let owner = owner("00000000-0000-4000-8000-000000000001");
        let salt = Digest32::of_bytes(b"test-rollout-salt");
        assert!(!in_canary_cohort(&owner, 0, salt));
        assert!(in_canary_cohort(&owner, PPM_SCALE, salt));
        assert!(!in_canary_cohort(&owner, PPM_SCALE + 1, salt));
    }

    #[test]
    fn rollout_identity_binds_threshold_salt_and_shadow_budget() {
        let base = DeliveryPolicy::legacy_default();
        let mut threshold = base.clone();
        threshold.canary_threshold_ppm += 1;
        let mut salt = base.clone();
        salt.canary_cohort_salt = Digest32::of_bytes(b"other-rollout-salt");
        let mut budget = base.clone();
        budget.shadow_maximum_nodes -= 1;
        assert_ne!(base.digest(), threshold.digest());
        assert_ne!(base.digest(), salt.digest());
        assert_ne!(base.digest(), budget.digest());
    }

    #[test]
    fn shadow_budget_rejects_each_excess_independently() {
        let policy = DeliveryPolicy {
            canary_policy_version: 2,
            canary_threshold_ppm: 0,
            canary_cohort_salt: Digest32::of_bytes(b"shadow-budget"),
            shadow_maximum_channel_candidates: 8,
            shadow_maximum_nodes: 16,
            shadow_maximum_synapses: 32,
            shadow_maximum_settling_steps: 2,
            validation_error: None,
        };
        assert!(validate_shadow_shape(8, 16, 32, 2, &policy).is_ok());
        assert!(validate_shadow_shape(9, 16, 32, 2, &policy).is_err());
        assert!(validate_shadow_shape(8, 17, 32, 2, &policy).is_err());
        assert!(validate_shadow_shape(8, 16, 33, 2, &policy).is_err());
        assert!(validate_shadow_shape(8, 16, 32, 3, &policy).is_err());
    }

    #[test]
    fn invalid_policy_forces_canary_fail_closed() {
        let owner = owner("00000000-0000-4000-8000-000000000002");
        let mut policy = DeliveryPolicy::legacy_default();
        policy.canary_policy_version = 2;
        policy.canary_threshold_ppm = PPM_SCALE + 1;
        policy.validation_error = policy.validate().err();
        assert!(delivers_hnmf_with_policy(
            CognitiveRetrievalMode::HnmfCanary,
            &owner,
            &policy
        ));
        assert!(!delivers_hnmf_with_policy(
            CognitiveRetrievalMode::HnmfShadow,
            &owner,
            &policy
        ));
    }

    struct DeadlineOnlyReader {
        called: Arc<std::sync::atomic::AtomicBool>,
    }

    impl CurrentMemoryRetrievalContext for DeadlineOnlyReader {
        fn current(
            &self,
            _owner: &AgentId,
            _body_generation: u64,
        ) -> Result<RetrievalExecutionContextV1, String> {
            Err("undeadlined current path used".to_string())
        }

        fn acquire_context(
            &self,
            _owner: &AgentId,
            _body_generation: u64,
        ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
            Err("undeadlined acquire path used".to_string())
        }

        fn acquire_context_before(
            &self,
            _owner: &AgentId,
            _body_generation: u64,
            _deadline: std::time::Instant,
        ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
            self.called
                .store(true, std::sync::atomic::Ordering::Release);
            Err("deadline-aware path reached".to_string())
        }
    }

    #[test]
    fn mode_router_forwards_the_same_absolute_deadline() {
        let called = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let routed = route(
            CognitiveRetrievalMode::HnmfRequired,
            Arc::new(DeadlineOnlyReader {
                called: Arc::clone(&called),
            }),
        );
        let error = routed
            .acquire_context_before(
                &owner("00000000-0000-4000-8000-000000000003"),
                1,
                std::time::Instant::now() + std::time::Duration::from_secs(1),
            )
            .expect_err("provider error should be preserved");
        assert_eq!(error, "deadline-aware path reached");
        assert!(called.load(std::sync::atomic::Ordering::Acquire));
    }

    #[test]
    fn expired_deadline_is_rejected_before_provider_io() {
        let called = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let routed = route(
            CognitiveRetrievalMode::HnmfRequired,
            Arc::new(DeadlineOnlyReader {
                called: Arc::clone(&called),
            }),
        );
        let error = routed
            .acquire_context_before(
                &owner("00000000-0000-4000-8000-000000000004"),
                1,
                std::time::Instant::now(),
            )
            .expect_err("expired deadline must fail");
        assert_eq!(error, "retrieval provider request deadline exceeded");
        assert!(!called.load(std::sync::atomic::Ordering::Acquire));
    }
}
