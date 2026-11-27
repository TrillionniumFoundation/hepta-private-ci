//! Compose current Objective and NDU owners without caller-supplied context digests.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use codex_hepta_ndu::NduCurrentProjectionV1;
use codex_hepta_ndu::NduProjectionReadRequestV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::NativeMemoryContextAuthorityV1;
use crate::NativeMemoryContextBindingV1;
use crate::NativeMemoryError;
use crate::NativeMemoryTickContextV1;
use crate::native_memory_shadow_namespace::reject;
use crate::state::AgentdState;
use crate::state::CurrentObjectiveReadV1;

/// The embedding host supplies a protected monotonic source and its continuity
/// domain. Observations must be bounded and must not acquire owner locks or
/// reenter this host. No wall
/// clock, process-local Instant or attestation is invented here.
pub trait NativeMemoryTickClockV1: Send + Sync {
    fn observe(&self) -> Result<NativeMemoryClockObservationV1, NativeMemoryError>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeMemoryClockObservationV1 {
    pub domain: Digest32,
    pub monotonic_micros: u64,
}

/// Reference to owners installed in one Agentd runtime. Every use rechecks
/// currentness; shutdown permanently closes the runtime's external handles.
pub struct AgentdNativeMemoryContextHostV1 {
    state: Weak<AgentdState>,
    ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
    clock: Arc<dyn NativeMemoryTickClockV1>,
    last_clock: Mutex<NativeMemoryClockObservationV1>,
    pub(crate) cancellation: tokio_util::sync::CancellationToken,
}

/// Prepared by the host for an external issuer. This value grants no read and
/// cannot be transferred to another runtime or edited into another query.
pub struct AgentdNativeMemoryPreparedReadV1 {
    host: Arc<AgentdNativeMemoryContextHostV1>,
    objective: CurrentObjectiveReadV1,
    query: MemoryCellQueryV1,
    request: NduProjectionReadRequestV1,
    binding: FinalUseBinding,
}

pub struct AgentdNativeMemoryCurrentContextV1 {
    host: Arc<AgentdNativeMemoryContextHostV1>,
    objective: CurrentObjectiveReadV1,
    query: MemoryCellQueryV1,
    projection: NduCurrentProjectionV1,
    binding: NativeMemoryContextBindingV1,
}

pub fn native_memory_subject_digest_v1(subject: &StableId) -> Digest32 {
    let bytes = subject.as_str().as_bytes();
    Digest32::of_parts(&[
        b"hepta.memory-cell.subject.v1",
        &(bytes.len() as u32).to_be_bytes(),
        bytes,
    ])
}

impl AgentdNativeMemoryContextHostV1 {
    #[cfg(test)]
    pub(crate) fn attach(
        state: &Arc<AgentdState>,
        ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
        clock: Arc<dyn NativeMemoryTickClockV1>,
    ) -> Result<Arc<Self>, NativeMemoryError> {
        Self::attach_with_cancellation(
            state,
            ndu,
            clock,
            tokio_util::sync::CancellationToken::new(),
        )
    }

    pub(crate) fn attach_with_cancellation(
        state: &Arc<AgentdState>,
        ndu: Arc<Mutex<NduAuthenticatedOwnerV1>>,
        clock: Arc<dyn NativeMemoryTickClockV1>,
        cancellation: tokio_util::sync::CancellationToken,
    ) -> Result<Arc<Self>, NativeMemoryError> {
        if cancellation.is_cancelled() {
            return Err(reject("current memory runtime closed"));
        }
        if state.objective_runtime.get().is_none() {
            return Err(reject(
                "current memory requires an installed Objective owner",
            ));
        }
        state.refresh_generation().map_err(reject)?;
        // Installation may occur while Fleet is Starting. Agentd's existing
        // lifecycle contract serves Running at spawn + 1; this only validates
        // the configured target. A real current Objective is required to read.
        let serving_generation = state
            .identity()
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| reject("Agentd serving generation overflow"))?;
        let current = ndu.lock().map_err(reject)?;
        if current.context().principal_id.as_str() != state.identity().agent_id.as_str()
            || current.context().host_generation != serving_generation
        {
            return Err(reject(
                "NDU principal or host generation differs from Agentd",
            ));
        }
        drop(current);
        let observed = clock.observe()?;
        if observed.domain.is_zero() || observed.monotonic_micros == 0 {
            return Err(reject(
                "current memory requires an explicit monotonic clock domain",
            ));
        }
        Ok(Arc::new(Self {
            state: Arc::downgrade(state),
            ndu,
            clock,
            last_clock: Mutex::new(observed),
            cancellation,
        }))
    }

    fn state(&self) -> Result<Arc<AgentdState>, NativeMemoryError> {
        if self.cancellation.is_cancelled() {
            return Err(reject("current memory runtime closed"));
        }
        self.state
            .upgrade()
            .ok_or_else(|| reject("current memory runtime unavailable"))
    }

    fn observe_clock(&self) -> Result<NativeMemoryClockObservationV1, NativeMemoryError> {
        let mut previous = self.last_clock.lock().map_err(reject)?;
        let observed = self.clock.observe()?;
        if observed.domain != previous.domain
            || observed.monotonic_micros < previous.monotonic_micros
        {
            self.cancellation.cancel();
            return Err(reject("monotonic clock continuity lost"));
        }
        *previous = observed;
        Ok(observed)
    }

    fn require_ndu_owner(
        state: &AgentdState,
        ndu: &NduAuthenticatedOwnerV1,
        objective: &CurrentObjectiveReadV1,
    ) -> Result<(), NativeMemoryError> {
        if ndu.context().principal_id.as_str() != state.identity().agent_id.as_str()
            || ndu.context().host_generation != objective.snapshot().fleet_generation
        {
            return Err(reject(
                "current NDU differs from the actual serving Objective owner",
            ));
        }
        Ok(())
    }

    pub fn prepare_read(
        self: &Arc<Self>,
        run_id: &str,
        query: MemoryCellQueryV1,
    ) -> Result<AgentdNativeMemoryPreparedReadV1, NativeMemoryError> {
        query.key.question()?;
        let state = self.state()?;
        let objective = state.checked_current_objective(run_id).map_err(reject)?;
        if query.deadline_unix_ms > objective.snapshot().deadline_ms
            || query.deadline_unix_ms <= crate::authbus_ingress::now_ms().map_err(reject)?
        {
            return Err(reject("query deadline is outside its current run"));
        }
        let material = serde_json::to_vec(&(
            "hepta.memory-cell.current-read.v1",
            run_id,
            &query,
            objective.binding_digest().to_string(),
        ))
        .map_err(reject)?;
        let request = NduProjectionReadRequestV1 {
            request_id: Digest32::of_bytes(&material),
            objective_digest: objective.snapshot().objective_digest,
            subject_digest: native_memory_subject_digest_v1(&objective.snapshot().subject_id),
        };
        let ndu = self.ndu.lock().map_err(reject)?;
        Self::require_ndu_owner(&state, &ndu, &objective)?;
        let binding = ndu.current_projection_binding(&request).map_err(reject)?;
        state
            .revalidate_current_objective(&objective)
            .map_err(reject)?;
        if ndu.current_projection_binding(&request).map_err(reject)? != binding {
            return Err(reject("current NDU changed during Objective observation"));
        }
        self.observe_clock()?;
        Ok(AgentdNativeMemoryPreparedReadV1 {
            host: Arc::clone(self),
            objective,
            query,
            request,
            binding,
        })
    }
}

impl AgentdNativeMemoryPreparedReadV1 {
    pub fn binding(&self) -> &FinalUseBinding {
        &self.binding
    }
    pub(crate) fn belongs_to(&self, host: &Arc<AgentdNativeMemoryContextHostV1>) -> bool {
        Arc::ptr_eq(&self.host, host)
    }
    pub(crate) fn query(&self) -> &MemoryCellQueryV1 {
        &self.query
    }

    pub fn authorize(
        self,
        signed: &SignedFinalUseGrant,
    ) -> Result<AgentdNativeMemoryCurrentContextV1, NativeMemoryError> {
        let state = self.host.state()?;
        state
            .revalidate_current_objective(&self.objective)
            .map_err(reject)?;
        let ndu = self.host.ndu.lock().map_err(reject)?;
        AgentdNativeMemoryContextHostV1::require_ndu_owner(&state, &ndu, &self.objective)?;
        if ndu
            .current_projection_binding(&self.request)
            .map_err(reject)?
            != self.binding
        {
            return Err(reject("prepared NDU binding no longer current"));
        }
        let projection = ndu
            .read_current_projection(&self.request, signed)
            .map_err(reject)?;
        state
            .revalidate_current_objective(&self.objective)
            .map_err(reject)?;
        ndu.revalidate_current_projection(&projection)
            .map_err(reject)?;
        let clock = self.host.observe_clock()?;
        let binding = NativeMemoryContextBindingV1::from_checked_owners(
            self.objective.snapshot().run_id.clone(),
            self.objective.binding_digest(),
            projection.digest(),
            clock.domain,
        )?;
        drop(ndu);
        Ok(AgentdNativeMemoryCurrentContextV1 {
            host: self.host,
            objective: self.objective,
            query: self.query,
            projection,
            binding,
        })
    }
}

impl NativeMemoryContextAuthorityV1 for AgentdNativeMemoryCurrentContextV1 {
    fn current(&mut self) -> Result<NativeMemoryTickContextV1, NativeMemoryError> {
        let state = self.host.state()?;
        let ndu = self.host.ndu.lock().map_err(reject)?;
        // Stable run incarnation/revision and selected-projection versions
        // bracket a common observation. They are not a lease after return.
        state
            .revalidate_current_objective(&self.objective)
            .map_err(reject)?;
        AgentdNativeMemoryContextHostV1::require_ndu_owner(&state, &ndu, &self.objective)?;
        ndu.revalidate_current_projection(&self.projection)
            .map_err(reject)?;
        state
            .revalidate_current_objective(&self.objective)
            .map_err(reject)?;
        ndu.revalidate_current_projection(&self.projection)
            .map_err(reject)?;
        if self.query.deadline_unix_ms <= crate::authbus_ingress::now_ms().map_err(reject)? {
            return Err(reject("current memory query expired"));
        }
        let clock = self.host.observe_clock()?;
        Ok(NativeMemoryTickContextV1 {
            subject_id: self.objective.snapshot().subject_id.clone(),
            objective_digest: self.objective.snapshot().objective_digest,
            ndu_snapshot_digest: self.projection.digest(),
            monotonic_time_micros: clock.monotonic_micros,
            body_generation: None,
            modulator_digest: None,
        })
    }
    fn binding(&self) -> Option<&NativeMemoryContextBindingV1> {
        Some(&self.binding)
    }
    fn validate_query(&self, query: &MemoryCellQueryV1) -> Result<(), NativeMemoryError> {
        if query != &self.query {
            return Err(reject("query differs from its signed current-owner read"));
        }
        Ok(())
    }
}
