#!/usr/bin/env python3
"""One-shot finalization for intelligence.control product closure.

The script is intentionally exact-string based. It closes the daemon-owned
learning reconciliation loop, fixes destination-observation completeness
matching, and refreshes generated truth. It is idempotent so the temporary
workflow can safely be inspected or retried.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text and old not in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, block: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + block.strip() + "\n")


def write_learning_runtime() -> None:
    write(
        "codex-rs/hepta-agentd/src/intelligence_learning_runtime.rs",
        r'''//! Daemon-owned scheduling for durable intelligence Decision/Outcome closure.
//!
//! The host and all final-use authority are supplied explicitly by the product
//! embedding. Agentd owns only bounded restart reconciliation and outbox drain
//! scheduling for the current Running generation. The default CLI installs no
//! host and therefore gains no learning-writer authority.

use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIntelligenceLearningErrorV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdState;

const MIN_RECONCILE_INTERVAL: Duration = Duration::from_millis(10);
const MAX_RECONCILE_INTERVAL: Duration = Duration::from_secs(60 * 60);
const MAX_RECONCILE_BATCH: u32 = 256;
const NOT_READY_POLL: Duration = Duration::from_millis(50);

/// Explicit product-owned scheduling profile for the durable learning outbox.
///
/// Construction does not mint a writer, grant provider, or authority. Those
/// objects are already sealed inside `AgentdIntelligenceLearningHostV1`.
pub struct AgentdIntelligenceLearningRuntimeConfigV1 {
    host: Arc<AgentdIntelligenceLearningHostV1>,
    interval: Duration,
    max_batch: u32,
}

impl AgentdIntelligenceLearningRuntimeConfigV1 {
    pub fn new(
        host: Arc<AgentdIntelligenceLearningHostV1>,
        interval: Duration,
        max_batch: u32,
    ) -> Result<Self, AgentdError> {
        validate_runtime_policy(interval, max_batch)?;
        Ok(Self {
            host,
            interval,
            max_batch,
        })
    }

    #[must_use]
    pub fn owner_generation(&self) -> u64 {
        self.host.owner_generation().get()
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        Arc<AgentdIntelligenceLearningHostV1>,
        Duration,
        u32,
    ) {
        (self.host, self.interval, self.max_batch)
    }
}

fn validate_runtime_policy(interval: Duration, max_batch: u32) -> Result<(), AgentdError> {
    if !(MIN_RECONCILE_INTERVAL..=MAX_RECONCILE_INTERVAL).contains(&interval) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation interval must be 10ms..=1h".to_string(),
        ));
    }
    if !(1..=MAX_RECONCILE_BATCH).contains(&max_batch) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation batch must be 1..=256".to_string(),
        ));
    }
    Ok(())
}

pub(crate) async fn run_intelligence_learning_runtime_v1(
    host: Arc<AgentdIntelligenceLearningHostV1>,
    state: Arc<AgentdState>,
    interval: Duration,
    max_batch: u32,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    validate_runtime_policy(interval, max_batch)?;
    loop {
        if !state.automation_admission_ready()? {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(std::cmp::min(interval, NOT_READY_POLL)) => {}
            }
            continue;
        }

        let current_generation = state.current_generation()?;
        let owner_generation = host.owner_generation().get();
        if current_generation != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(format!(
                "intelligence learning host generation {owner_generation} does not match current Running generation {current_generation}"
            )));
        }

        let reconciled = host
            .reconcile_unsettled(max_batch)
            .await
            .map_err(learning_error)?;
        let reconciled = u32::try_from(reconciled.len()).unwrap_or(max_batch);
        let mut remaining = max_batch.saturating_sub(reconciled);
        while remaining > 0 {
            match host.dispatch_next().await.map_err(learning_error)? {
                Some(_) => remaining -= 1,
                None => break,
            }
        }

        // A generation change during destination observation or append closes
        // the required service. The operation store retains any unsettled row
        // for adoption and exact replay by the successor generation.
        state.refresh_generation()?;
        if state.current_generation()? != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(
                "intelligence learning generation changed during reconciliation".to_string(),
            ));
        }

        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {}
        }
    }
}

fn learning_error(error: AgentdIntelligenceLearningErrorV1) -> AgentdError {
    AgentdError::Protocol(format!(
        "intelligence learning reconciliation failed: {error}"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn learning_runtime_policy_is_bounded() {
        assert!(validate_runtime_policy(Duration::from_millis(10), 1).is_ok());
        assert!(validate_runtime_policy(Duration::from_secs(3600), 256).is_ok());
        assert!(validate_runtime_policy(Duration::ZERO, 1).is_err());
        assert!(validate_runtime_policy(Duration::from_millis(9), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(3601), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 0).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 257).is_err());
    }
}
''',
    )


def patch_learning_source() -> None:
    path = "codex-rs/hepta-agentd/src/intelligence_learning.rs"
    replace_once(
        path,
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;\n",
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;\nuse codex_hepta_learning_ledger::validate_candidate_set_completeness;\n",
    )
    replace_once(
        path,
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(completeness_digest) =
                validate_candidate_set_completeness(&completeness)
            else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
    )
    replace_once(
        path,
        "                        && value.completeness == completeness\n",
        "                        && value.candidate_completeness_digest == completeness_digest\n",
    )
    replace_once(
        path,
        '''    pub async fn backlog_metrics(
        &self,
    ) -> Result<OperationBacklogMetrics, AgentdIntelligenceLearningErrorV1> {''',
        '''    #[must_use]
    pub const fn owner_generation(&self) -> Generation {
        self.generation
    }

    pub async fn backlog_metrics(
        &self,
    ) -> Result<OperationBacklogMetrics, AgentdIntelligenceLearningErrorV1> {''',
    )


def patch_rewrite_script() -> None:
    path = "scripts/codex-intelligence-learning-reconcile-rewrite.py"
    replace_once(
        path,
        '''    replace_once(
        path,
        "use codex_hepta_learning_ledger::AppendReceipt;",
        ''' + "'''use codex_hepta_learning_ledger::AppendDisposition;\nuse codex_hepta_learning_ledger::AppendReceipt;'''" + ''',
    )
''',
        '''    replace_once(
        path,
        "use codex_hepta_learning_ledger::AppendReceipt;",
        ''' + "'''use codex_hepta_learning_ledger::AppendDisposition;\nuse codex_hepta_learning_ledger::AppendReceipt;'''" + ''',
    )
    replace_once(
        path,
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;",
        ''' + "'''use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;\nuse codex_hepta_learning_ledger::validate_candidate_set_completeness;'''" + ''',
    )
''',
    )
    replace_once(
        path,
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(completeness_digest) =
                validate_candidate_set_completeness(&completeness)
            else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
    )
    replace_once(
        path,
        "                        && value.completeness == completeness\n",
        "                        && value.candidate_completeness_digest == completeness_digest\n",
    )


def patch_config() -> None:
    path = "codex-rs/hepta-agentd/src/config.rs"
    replace_once(
        path,
        '''    intelligence_invocation_provider:
        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
}''',
        '''    intelligence_invocation_provider:
        Option<std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>>,
    intelligence_learning_runtime: Option<crate::AgentdIntelligenceLearningRuntimeConfigV1>,
}''',
    )
    replace_once(
        path,
        '''            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
        })''',
        '''            intelligence_product_runner: None,
            intelligence_invocation_provider: None,
            intelligence_learning_runtime: None,
        })''',
    )
    replace_once(
        path,
        '''    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }
''',
        '''    /// Attach the daemon-owned scheduler for the already constructed
    /// product learning host. The canonical profile must be complete first;
    /// default process startup never manufactures a ledger writer or grant.
    pub fn with_intelligence_learning_runtime(
        mut self,
        runtime: crate::AgentdIntelligenceLearningRuntimeConfigV1,
    ) -> Result<Self, AgentdError> {
        if self.intelligence_product_runner.is_none()
            || self.intelligence_invocation_provider.is_none()
        {
            return Err(AgentdError::Invalid(
                "intelligence learning runtime requires a complete canonical intelligence profile"
                    .to_string(),
            ));
        }
        if self.intelligence_learning_runtime.is_some() {
            return Err(AgentdError::Invalid(
                "intelligence learning runtime already configured".to_string(),
            ));
        }
        let expected_generation = self
            .identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("Agentd running generation overflow".to_string()))?;
        if runtime.owner_generation() != expected_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "intelligence learning runtime generation {} does not match expected Running generation {expected_generation}",
                runtime.owner_generation()
            )));
        }
        self.intelligence_learning_runtime = Some(runtime);
        Ok(self)
    }

    pub(crate) fn take_intelligence_learning_runtime(
        &mut self,
    ) -> Option<crate::AgentdIntelligenceLearningRuntimeConfigV1> {
        self.intelligence_learning_runtime.take()
    }

    pub fn identity(&self) -> &AgentdIdentity {
        &self.identity
    }
''',
    )


def patch_runtime() -> None:
    path = "codex-rs/hepta-agentd/src/runtime.rs"
    replace_once(
        path,
        '''    let production_operations = config.take_production_operations();
    let plasticity_bootstrap = config.take_plasticity_runtime_bootstrap();''',
        '''    let production_operations = config.take_production_operations();
    let intelligence_learning = config.take_intelligence_learning_runtime();
    let plasticity_bootstrap = config.take_plasticity_runtime_bootstrap();''',
    )
    replace_once(
        path,
        '''    let startup: Result<(), AgentdError> = async {
        if let Some((host, interval)) = production_operations {''',
        '''    let startup: Result<(), AgentdError> = async {
        if let Some(runtime) = intelligence_learning {
            let (host, interval, max_batch) = runtime.into_parts();
            tasks.spawn_required(
                "intelligence-learning-reconciler",
                crate::intelligence_learning_runtime::run_intelligence_learning_runtime_v1(
                    host,
                    Arc::clone(&state),
                    interval,
                    max_batch,
                    cancellation.clone(),
                ),
            )?;
        }
        if let Some((host, interval)) = production_operations {''',
    )


def patch_lib() -> None:
    path = "codex-rs/hepta-agentd/src/lib.rs"
    replace_once(
        path,
        '''mod intelligence_learning;
mod intelligence_observability;''',
        '''mod intelligence_learning;
mod intelligence_learning_runtime;
mod intelligence_observability;''',
    )
    replace_once(
        path,
        '''pub use intelligence_learning::AgentdIntelligenceLearningHostV1;
pub use intelligence_learning::AgentdIntelligenceLearningReceiptV1;''',
        '''pub use intelligence_learning::AgentdIntelligenceLearningHostV1;
pub use intelligence_learning::AgentdIntelligenceLearningReceiptV1;
pub use intelligence_learning_runtime::AgentdIntelligenceLearningRuntimeConfigV1;''',
    )


def patch_bound_test_name() -> None:
    replace_once(
        "codex-rs/hepta-agentd/src/lane_b_bound.rs",
        "fn starting_draining_or_forged_fence_is_rejected_before_mutation()",
        "fn forged_generation_or_fence_is_rejected_before_mutation()",
    )


def patch_generated_truth() -> None:
    path = "scripts/hepta-intelligence-control-status.py"
    replace_once(
        path,
        '''    "learning": "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "telemetry":''',
        '''    "learning": "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "learning_runtime": "codex-rs/hepta-agentd/src/intelligence_learning_runtime.rs",
    "telemetry":''',
    )
    replace_once(
        path,
        '''    "restartReconciliationPresent": (
        "learning",
        "reconcile_unsettled",
    ),
    "physicalTerminalBindingPresent":''',
        '''    "restartReconciliationPresent": (
        "learning",
        "reconcile_unsettled",
    ),
    "daemonLearningReconcilerPresent": (
        "learning_runtime",
        "run_intelligence_learning_runtime_v1",
    ),
    "physicalTerminalBindingPresent":''',
    )
    replace_once(
        path,
        '''    "evidence_payload_rejects_role_substitution",
}''',
        '''    "evidence_payload_rejects_role_substitution",
    "learning_runtime_policy_is_bounded",
}''',
    )
    replace_once(
        path,
        '''            "restartReconciliationPresent": facts[
                "restartReconciliationPresent"
            ],
            "physicalTerminalBindingPresent":''',
        '''            "restartReconciliationPresent": facts[
                "restartReconciliationPresent"
            ],
            "daemonLearningReconcilerPresent": facts[
                "daemonLearningReconcilerPresent"
            ],
            "physicalTerminalBindingPresent":''',
    )
    replace_once(
        path,
        '''                    "restartReconciliationPresent",
                    "physicalTerminalBindingPresent",''',
        '''                    "restartReconciliationPresent",
                    "daemonLearningReconcilerPresent",
                    "physicalTerminalBindingPresent",''',
    )
    replace_once(
        path,
        '''                "tests": names("operation_ids", "evidence_payload", "decision_outcome"),''',
        '''                "tests": names(
                    "operation_ids",
                    "evidence_payload",
                    "decision_outcome",
                    "learning_runtime_policy",
                ),''',
    )


def patch_docs() -> None:
    append_once(
        "docs/modules/intelligence.control/RESTART_RECONCILIATION.md",
        "## Daemon scheduling profile",
        '''## Daemon scheduling profile

A product embedding may attach `AgentdIntelligenceLearningRuntimeConfigV1` only after the canonical runner and host-owned invocation provider are installed. The config must carry a learning host for the exact Running generation (`spawn + 1`), a 10 ms to one hour cadence, and a batch bound of 1 to 256. Agentd then starts one required `intelligence-learning-reconciler` task. Each iteration waits for the live Running admission fence, observes/reconciles unsettled rows first, drains only the remaining bounded batch from the prepared outbox, and rechecks generation after destination work. A generation mismatch fences the daemon; the successor adopts the unsettled operation and replays only the exact immutable payload.

The ordinary CLI installs no learning host, writer, grant provider, or scheduler. Absence therefore means no product-learning mutation authority, not an implicit compatibility writer.''',
    )
    append_once(
        "docs/modules/intelligence.control/PRODUCT_CLOSURE.md",
        "## Daemon-owned product-learning service",
        '''## Daemon-owned product-learning service

`AgentdIntelligenceLearningRuntimeConfigV1` composes the durable learning host into the normal Agentd task owner without manufacturing authority. It is accepted only after the all-or-none canonical profile, must bind the unique Running generation, and runs restart reconciliation before bounded prepared-outbox dispatch. The required service is generation-fenced before and after destination work. The default binary remains fail-closed because it does not construct this config.''',
    )
    append_once(
        "docs/modules/intelligence.control/TECHNICAL.md",
        "## 18. Daemon-owned product-learning reconciliation",
        '''## 18. Daemon-owned product-learning reconciliation

The optional product embedding can attach `AgentdIntelligenceLearningRuntimeConfigV1` after installing the complete canonical runner/provider profile. Agentd then owns one required, bounded reconciliation task for the sealed `AgentdIntelligenceLearningHostV1`: it waits for the current Running fence, observes/reconciles unsettled destination state, drains only the configured residual batch, and rechecks generation after durable work. No CLI default creates the host, ledger writer, final-use authority or signed-grant provider. This closes repository-owned daemon scheduling while preserving the separate real-process, target-host, independent-acceptance, activation and release gates.''',
    )


def main() -> None:
    write_learning_runtime()
    patch_learning_source()
    patch_rewrite_script()
    patch_config()
    patch_runtime()
    patch_lib()
    patch_bound_test_name()
    patch_generated_truth()
    patch_docs()
    subprocess.run(
        ["cargo", "fmt", "--all"], cwd=ROOT / "codex-rs", check=True
    )
    subprocess.run(
        ["python3", "scripts/hepta-intelligence-control-status.py", "--write-tracked"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
