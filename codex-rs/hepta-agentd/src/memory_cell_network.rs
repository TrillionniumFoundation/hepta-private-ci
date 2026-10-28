//! A bounded, read-only multi-owner memory host over real Agentd sockets.
//!
//! A deployment pins every source owner and selected bundle. Destination data
//! and parameter publication remain with their existing owners. Migration here
//! transfers the admitted read routes through OrganHostV1; it does not copy a
//! database, mint a federation grant, select a model, or invoke TaskFlow effects.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::OrganHostV1;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_types::StableId;

#[path = "memory_cell_network_bindings.rs"]
mod bindings;
#[path = "memory_cell_network_organ.rs"]
mod organ;
#[path = "memory_cell_network_transport.rs"]
mod transport;
pub use bindings::*;
use transport::NetworkAttempt;

const ATTEMPT_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Phase {
    Ready,
    Preparing,
    Unavailable,
}

struct NetworkState {
    deployment: Arc<MemoryCellDeploymentV1>,
    organ: OrganHostV1,
    phase: Phase,
    epoch: u64,
}

/// One composition owner, never a second cognitive or artifact writer. Pins
/// are explicit configuration; after restart, recovery must probe all owners.
pub struct MemoryCellNetworkV1 {
    registry: FleetRegistry,
    consumer: AgentId,
    consumer_spawn: u64,
    state: Mutex<NetworkState>,
    host_token: Arc<()>,
    accounting: Arc<Mutex<MemoryCellNetworkCostV1>>,
}

impl MemoryCellNetworkV1 {
    pub fn new(
        registry: FleetRegistry,
        consumer: AgentId,
        consumer_spawn: u64,
        deployment: MemoryCellDeploymentV1,
    ) -> Result<Self, MemoryCellNetworkErrorV1> {
        if consumer_spawn == 0
            || deployment
                .nodes
                .iter()
                .any(|node| node.grant.consumer_agent_id() != &consumer)
        {
            return Err("memory deployment consumer or spawn mismatch"
                .to_string()
                .into());
        }
        let (graph, handlers) = organ::graph(&deployment)?;
        let mut organ = OrganHostV1::new(graph, handlers).map_err(|error| error.to_string())?;
        organ.start_all().map_err(|error| error.to_string())?;
        Ok(Self {
            registry,
            consumer,
            consumer_spawn,
            state: Mutex::new(NetworkState {
                deployment: Arc::new(deployment),
                organ,
                phase: Phase::Unavailable,
                epoch: 0,
            }),
            host_token: Arc::new(()),
            accounting: Arc::new(Mutex::new(MemoryCellNetworkCostV1::default())),
        })
    }

    pub fn version(&self) -> Result<MemoryCellNetworkVersionV1, MemoryCellNetworkErrorV1> {
        Ok(self
            .state
            .lock()
            .map_err(|_| "memory network state lock poisoned".to_string())?
            .deployment
            .version())
    }

    /// Completed and cancelled attempt costs. Elapsed time is summed attempt
    /// time, not concurrent wall time; kernel transport headers are excluded.
    pub fn cumulative_cost(&self) -> Result<MemoryCellNetworkCostV1, MemoryCellNetworkErrorV1> {
        Ok(*self
            .accounting
            .lock()
            .map_err(|_| "memory network accounting lock poisoned".to_string())?)
    }

    pub async fn recover(
        &self,
        expected: MemoryCellNetworkVersionV1,
    ) -> Result<MemoryCellNetworkReceiptV1, MemoryCellNetworkErrorV1> {
        let (deployment, mut admission) = self.begin_change(expected)?;
        let attempt = self.attempt(&deployment)?;
        let result = bounded(async {
            attempt.verify_complete_vector().await?;
            attempt.verify_complete_vector().await?;
            let mut state = self
                .state
                .lock()
                .map_err(|_| "memory network state lock poisoned".to_string())?;
            require_change(&state, expected, admission.epoch)?;
            organ::verify_routes(&mut state.organ, &deployment)?;
            state.phase = Phase::Ready;
            admission.armed = false;
            Ok(())
        })
        .await;
        outcome(result, attempt.cost())?;
        Ok(MemoryCellNetworkReceiptV1 {
            version: expected,
            cost: attempt.cost(),
        })
    }

    /// Close admission before probing the complete successor vector. A failed
    /// or cancelled migration remains unavailable until explicit recovery or
    /// a successful retry. An acknowledged generation never rolls backwards.
    pub async fn migrate(
        &self,
        expected: MemoryCellNetworkVersionV1,
        candidate: MemoryCellDeploymentV1,
    ) -> Result<MemoryCellNetworkReceiptV1, MemoryCellNetworkErrorV1> {
        if expected.generation.get().checked_add(1) != Some(candidate.generation.get()) {
            return Err("memory deployment must be the exact successor generation"
                .to_string()
                .into());
        }
        let (graph, handlers) = organ::graph(&candidate)?;
        let (_, mut admission) = self.begin_change(expected)?;
        let attempt = self.attempt(&candidate)?;
        let version = candidate.version();
        let result = bounded(async {
            attempt.verify_complete_vector().await?;
            attempt.verify_complete_vector().await?;
            let mut state = self
                .state
                .lock()
                .map_err(|_| "memory network state lock poisoned".to_string())?;
            require_change(&state, expected, admission.epoch)?;
            let mut migration = organ::RouteMigration {
                from: expected,
                to: version,
                applied: false,
            };
            let prior_generation = state.organ.generation();
            state
                .organ
                .replace_read_only_generation_with_migration(
                    prior_generation,
                    graph,
                    handlers,
                    &mut migration,
                )
                .map_err(|error| error.to_string())?;
            if !migration.applied {
                return Err("memory route state migration did not acknowledge".to_string());
            }
            organ::verify_routes(&mut state.organ, &candidate)?;
            state.deployment = Arc::new(candidate);
            state.phase = Phase::Ready;
            admission.armed = false;
            Ok(())
        })
        .await;
        outcome(result, attempt.cost())?;
        Ok(MemoryCellNetworkReceiptV1 {
            version,
            cost: attempt.cost(),
        })
    }

    pub async fn read(
        &self,
        expected: MemoryCellNetworkVersionV1,
        requests: BTreeMap<StableId, MemoryRequestV1>,
    ) -> Result<MemoryCellNetworkReadV1, MemoryCellNetworkErrorV1> {
        let (deployment, epoch) = self.capture(expected)?;
        let attempt = match self.attempt(&deployment) {
            Ok(attempt) => attempt,
            Err(error) => {
                self.close_epoch(expected, epoch);
                return Err(error.into());
            }
        };
        let result = bounded(async {
            attempt.verify_complete_vector().await?;
            let readouts = attempt.read(&requests).await?;
            attempt.verify_complete_vector().await?;
            self.require_epoch(expected, epoch)?;
            Ok(readouts)
        })
        .await;
        let readouts = match outcome(result, attempt.cost()) {
            Ok(readouts) => readouts,
            Err(error) => {
                self.close_epoch(expected, epoch);
                return Err(error);
            }
        };
        Ok(MemoryCellNetworkReadV1 {
            host_token: Arc::clone(&self.host_token),
            version: expected,
            admission_epoch: epoch,
            readouts,
            cost: attempt.cost(),
        })
    }

    pub async fn revalidate(
        &self,
        read: &MemoryCellNetworkReadV1,
    ) -> Result<MemoryCellNetworkCostV1, MemoryCellNetworkErrorV1> {
        if !Arc::ptr_eq(&self.host_token, &read.host_token) {
            return Err("memory read belongs to another network admission"
                .to_string()
                .into());
        }
        let (deployment, epoch) = self.capture(read.version)?;
        if epoch != read.admission_epoch {
            return Err("memory read admission epoch was superseded"
                .to_string()
                .into());
        }
        let attempt = match self.attempt(&deployment) {
            Ok(attempt) => attempt,
            Err(error) => {
                self.close_epoch(read.version, epoch);
                return Err(error.into());
            }
        };
        let result = bounded(async {
            attempt.verify_complete_vector().await?;
            self.require_epoch(read.version, epoch)
        })
        .await;
        if let Err(error) = outcome(result, attempt.cost()) {
            self.close_epoch(read.version, epoch);
            return Err(error);
        }
        Ok(attempt.cost())
    }

    fn capture(
        &self,
        expected: MemoryCellNetworkVersionV1,
    ) -> Result<(Arc<MemoryCellDeploymentV1>, u64), String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "memory network state lock poisoned".to_string())?;
        if state.phase != Phase::Ready || state.deployment.version() != expected {
            return Err("memory deployment is unavailable or superseded".to_string());
        }
        let deployment = Arc::clone(&state.deployment);
        if let Err(error) = organ::verify_routes(&mut state.organ, &deployment) {
            state.phase = Phase::Unavailable;
            return Err(error);
        }
        Ok((deployment, state.epoch))
    }

    fn begin_change(
        &self,
        expected: MemoryCellNetworkVersionV1,
    ) -> Result<(Arc<MemoryCellDeploymentV1>, AdmissionGuard<'_>), String> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| "memory network state lock poisoned".to_string())?;
        if state.deployment.version() != expected || state.phase == Phase::Preparing {
            return Err("memory deployment compare-and-swap failed".to_string());
        }
        state.epoch = state
            .epoch
            .checked_add(1)
            .ok_or_else(|| "memory admission epoch exhausted".to_string())?;
        state.phase = Phase::Preparing;
        Ok((
            Arc::clone(&state.deployment),
            AdmissionGuard {
                network: self,
                epoch: state.epoch,
                armed: true,
            },
        ))
    }

    fn attempt(&self, deployment: &MemoryCellDeploymentV1) -> Result<NetworkAttempt, String> {
        NetworkAttempt::new(
            &self.registry,
            &self.consumer,
            self.consumer_spawn,
            deployment,
            Arc::clone(&self.accounting),
        )
    }

    fn require_epoch(&self, version: MemoryCellNetworkVersionV1, epoch: u64) -> Result<(), String> {
        let state = self
            .state
            .lock()
            .map_err(|_| "memory network state lock poisoned".to_string())?;
        if state.phase != Phase::Ready
            || state.epoch != epoch
            || state.deployment.version() != version
        {
            return Err("memory network read crossed a deployment change".to_string());
        }
        Ok(())
    }

    fn close_epoch(&self, version: MemoryCellNetworkVersionV1, epoch: u64) {
        if let Ok(mut state) = self.state.lock()
            && state.deployment.version() == version
            && state.epoch == epoch
        {
            state.phase = Phase::Unavailable;
        }
    }
}

struct AdmissionGuard<'a> {
    network: &'a MemoryCellNetworkV1,
    epoch: u64,
    armed: bool,
}
impl Drop for AdmissionGuard<'_> {
    fn drop(&mut self) {
        if self.armed
            && let Ok(mut state) = self.network.state.lock()
            && state.epoch == self.epoch
        {
            state.phase = Phase::Unavailable;
        }
    }
}

fn require_change(
    state: &NetworkState,
    expected: MemoryCellNetworkVersionV1,
    epoch: u64,
) -> Result<(), String> {
    if state.phase != Phase::Preparing
        || state.epoch != epoch
        || state.deployment.version() != expected
    {
        return Err("memory deployment changed during preparation".to_string());
    }
    Ok(())
}

async fn bounded<T>(
    work: impl std::future::Future<Output = Result<T, String>>,
) -> Result<T, String> {
    tokio::time::timeout(ATTEMPT_TIMEOUT, work)
        .await
        .map_err(|_| "memory network attempt deadline elapsed".to_string())?
}

fn outcome<T>(
    result: Result<T, String>,
    cost: MemoryCellNetworkCostV1,
) -> Result<T, MemoryCellNetworkErrorV1> {
    result.map_err(|reason| MemoryCellNetworkErrorV1 {
        reason: reason.chars().take(1_024).collect(),
        cost,
    })
}

fn unix_seconds() -> Result<i64, String> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_secs()
        .try_into()
        .map_err(|_| "memory network clock overflow".to_string())
}

#[cfg(test)]
#[path = "memory_cell_network_test_support.rs"]
mod test_support;
#[cfg(test)]
#[path = "memory_cell_network_tests.rs"]
mod tests;
