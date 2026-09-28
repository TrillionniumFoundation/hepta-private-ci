#!/usr/bin/env python3
"""Apply the bounded inference.worker hardening edits to large source files.

This script is intentionally exact and one-shot: every replacement asserts the
expected predecessor text and count. It exists so the repository runner can
format and commit large-file edits without weakening the source/branch binding.
"""

from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def replace_exact(
    relative: str,
    old: str,
    new: str,
    *,
    count: int = 1,
) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    observed = text.count(old)
    if observed != count:
        raise RuntimeError(
            f"{relative}: expected {count} occurrences, observed {observed}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/lib.rs",
        "pub mod native_app_server;\n",
        "pub mod native_app_server;\n/// Explicit hosted recovery, terminal-receipt reconciliation and metrics.\npub mod native_recovery;\n",
    )

    replace_exact(
        "codex-rs/hepta-infer-core/src/native_control.rs",
        """    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }
""",
        """    pub fn native_record(&self, request_id: &str) -> Option<&NativeRunRecord> {
        self.native.records.get(request_id)
    }

    /// Read-only operational projection. Callers cannot mutate or manufacture
    /// native journal facts through this iterator.
    pub fn native_records(&self) -> impl Iterator<Item = &NativeRunRecord> {
        self.native.records.values()
    }

    pub fn native_maximum_in_flight(&self) -> Option<usize> {
        self.native.maximum_in_flight
    }

    pub fn native_journal_bytes(&self) -> u64 {
        self.journal_bytes
    }

    pub fn journal_record_capacity(&self) -> usize {
        self.capacity
    }
""",
    )

    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/experimental_local/resources.rs",
        """        if let Some(reason) = &state.fenced_reason {
            return Err(LocalWorkerError::GenerationFenced(reason.clone()));
        }
        Ok(())
""",
        """        // Fencing blocks new admission in `ensure_available`, but exact
        // recovery and physical cleanup must remain possible for the same
        // generation and device epoch.
        Ok(())
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/experimental_local/resources.rs",
        """        for model in state.models.values_mut() {
            model.lifecycle = ModelLifecycle::RepairRequired;
        }
""",
        """        for model in state.models.values_mut() {
            if model.lifecycle != ModelLifecycle::Zombie {
                model.lifecycle = ModelLifecycle::RepairRequired;
            }
        }
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/experimental_local/resources.rs",
        """        if model.lifecycle != ModelLifecycle::Ready || model.active_requests != 0 {
            return Err(LocalWorkerError::InvalidTransition(
                "model cannot enter unload",
            ));
        }
""",
        """        if !matches!(
            model.lifecycle,
            ModelLifecycle::Ready | ModelLifecycle::RepairRequired | ModelLifecycle::Zombie
        ) || model.active_requests != 0
        {
            return Err(LocalWorkerError::InvalidTransition(
                "model cannot enter unload",
            ));
        }
""",
    )

    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/experimental_local/durable.rs",
        """        drop(abort_token);
        request_resources.mark_running()?;

        let observed = match self
""",
        """        drop(abort_token);
        if let Err(error) = request_resources.mark_running() {
            let output = indeterminate_output(
                &admission.request_id,
                manifest.model_id(),
                handle.handle_id(),
                None,
                "local resource ledger failed after durable effect entry; no replay permitted",
            );
            let settled = control
                .settle_native(&admission.request_id, output)
                .map_err(control_error)?;
            request_resources.quarantine()?;
            self.resources
                .fence_generation("local resource ledger failed after effect entry")?;
            let mut result = result_from_record(&settled)?;
            result.stop_reason = Some(format!(
                "{}; {error}",
                result.stop_reason.unwrap_or_default()
            ));
            return Ok(result);
        }

        let observed = match self
""",
    )

    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/experimental_local/authority.rs",
        """    file.take(u64::try_from(MAX_CONFIG_BYTES + 1).map_err(|_| LocalWorkerError::ArithmeticOverflow)?)
        .read_to_end(&mut bytes)
""",
        """    file.by_ref()
        .take(
            u64::try_from(MAX_CONFIG_BYTES + 1)
                .map_err(|_| LocalWorkerError::ArithmeticOverflow)?,
        )
        .read_to_end(&mut bytes)
""",
    )

    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """use tokio_util::sync::CancellationToken;

const MAX_PROMPT_BYTES: usize = 32 * 1024;
""",
        """use tokio_util::sync::CancellationToken;

use crate::native_recovery::NativeRecoveryCounters;
use crate::native_recovery::NativeRecoveryPolicy;

const MAX_PROMPT_BYTES: usize = 32 * 1024;
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        "const TURN_START_RECONCILE_GRACE: Duration = Duration::from_secs(2);\n",
        "",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """pub struct AppServerModelDriver {
    config: NativeWorkerConfig,
    turn_start_authorizer: Option<Arc<dyn TurnStartAuthorizer>>,
}
""",
        """pub struct AppServerModelDriver {
    config: NativeWorkerConfig,
    turn_start_authorizer: Option<Arc<dyn TurnStartAuthorizer>>,
    recovery_policy: NativeRecoveryPolicy,
    recovery_counters: Arc<NativeRecoveryCounters>,
}
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """        Ok(Self {
            config,
            turn_start_authorizer: None,
        })
""",
        """        Ok(Self {
            config,
            turn_start_authorizer: None,
            recovery_policy: NativeRecoveryPolicy::default(),
            recovery_counters: Arc::new(NativeRecoveryCounters::default()),
        })
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """    pub fn with_turn_start_authorizer(mut self, authorizer: Arc<dyn TurnStartAuthorizer>) -> Self {
        self.turn_start_authorizer = Some(authorizer);
        self
    }
""",
        """    pub fn with_turn_start_authorizer(mut self, authorizer: Arc<dyn TurnStartAuthorizer>) -> Self {
        self.turn_start_authorizer = Some(authorizer);
        self
    }

    pub fn with_recovery_policy(mut self, policy: NativeRecoveryPolicy) -> Self {
        self.recovery_policy = policy;
        self
    }

    pub fn with_recovery_counters(mut self, counters: Arc<NativeRecoveryCounters>) -> Self {
        self.recovery_counters = counters;
        self
    }

    pub fn recovery_counters(&self) -> Arc<NativeRecoveryCounters> {
        Arc::clone(&self.recovery_counters)
    }
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        "reconcile_turn_start(&mut client, &started.thread.id).await?",
        "reconcile_turn_start(\n                                &mut client,\n                                &started.thread.id,\n                                self.recovery_policy.turn_start_reconcile_grace(),\n                                &self.recovery_counters,\n                            )\n                            .await?",
        count=3,
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """async fn reconcile_turn_start(
    client: &mut RemoteAppServerClient,
    thread_id: &str,
) -> Result<Option<codex_app_server_protocol::Turn>> {
    let deadline = Instant::now() + TURN_START_RECONCILE_GRACE;
""",
        """async fn reconcile_turn_start(
    client: &mut RemoteAppServerClient,
    thread_id: &str,
    grace: Duration,
    counters: &NativeRecoveryCounters,
) -> Result<Option<codex_app_server_protocol::Turn>> {
    counters.record_reconcile_attempt();
    let deadline = Instant::now() + grace;
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """            Ok(Some(event)) => event,
            Ok(None) | Err(_) => return Ok(None),
""",
        """            Ok(Some(event)) => event,
            Ok(None) | Err(_) => {
                counters.record_reconcile_miss();
                return Ok(None);
            }
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """                if let Some(turn) = exact_reconciled_turn(thread_id, &event)? {
                    return Ok(Some(turn));
                }
""",
        """                match exact_reconciled_turn(thread_id, &event) {
                    Ok(Some(turn)) => {
                        counters.record_reconcile_success();
                        return Ok(Some(turn));
                    }
                    Ok(None) => {}
                    Err(error) => {
                        counters.record_reconcile_failure();
                        return Err(error.into());
                    }
                }
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
        """            AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => {
                return Ok(None);
            }
""",
        """            AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => {
                counters.record_reconcile_miss();
                return Ok(None);
            }
""",
    )

    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
        """use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
""",
        """use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_infer_worker_host::native_recovery::NativeRecoveryPolicy;
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
        """    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
""",
        """    let mut native_profile_selected = false;
    let mut timeout_ms = 120_000_u64;
    let mut turn_start_reconcile_grace_ms = 2_000_u64;
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
        "[--context-query TEXT] [--timeout-ms N]\\nReads one prompt from stdin;",
        "[--context-query TEXT] [--timeout-ms N] [--turn-start-reconcile-grace-ms N]\\nReads one prompt from stdin;",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
        """            "--timeout-ms" => timeout_ms = value.parse()?,
""",
        """            "--timeout-ms" => timeout_ms = value.parse()?,
            "--turn-start-reconcile-grace-ms" => {
                turn_start_reconcile_grace_ms = value.parse()?
            }
""",
    )
    replace_exact(
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs",
        """    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
""",
        """    })?
    .with_recovery_policy(NativeRecoveryPolicy::new(Duration::from_millis(
        turn_start_reconcile_grace_ms,
    ))?)
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
""",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
