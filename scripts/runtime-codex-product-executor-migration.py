#!/usr/bin/env python3
"""Install the single Agentd-admitted runtime.codex product executor path.

The production worker may name an Agentd run, but it cannot construct the
revision/context/envelope binding. Those fields are loaded from Agentd's
durable run coordinator and validated before entering the existing native
runtime. The unbound model-only path remains available only through an
explicit development execution mode.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected exactly one legacy block")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and migrated marker are both absent")


def native_run_control(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-binding-v1"
    if marker in text:
        return text
    import_anchor = "use codex_hepta_infer_core::durable_control::DurableInferenceControl;\n"
    imports = (
        "use codex_hepta_agentd::AgentRunPhase;\n"
        "use codex_hepta_agentd::AgentRunReceipt;\n"
        + import_anchor
    )
    if import_anchor not in text:
        raise RuntimeError("agentd-admitted binding: native run-control import anchor absent")
    text = text.replace(import_anchor, imports, 1)
    struct = '''#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeIntelligenceRunBinding {
    pub run_id: String,
    pub expected_revision: u64,
    pub context_digest: String,
    pub envelope_digest: String,
}
'''
    addition = struct + '''
impl NativeIntelligenceRunBinding {
    /// Construct the product binding from Agentd's durable run owner.
    ///
    /// runtime.codex-agentd-admitted-binding-v1: callers may select a run ID,
    /// but cannot mint its revision or content identities. `Dispatched` is
    /// accepted only to reopen and reconcile the same operation; its original
    /// pre-dispatch revision is derived by removing the single dispatch CAS.
    pub fn from_agentd_receipt(
        expected_run_id: &str,
        expected_generation: u64,
        receipt: AgentRunReceipt,
    ) -> Result<Self> {
        if expected_run_id.is_empty()
            || expected_run_id.len() > 256
            || expected_run_id.as_bytes().contains(&0)
            || receipt.run_id != expected_run_id
        {
            return Err("Agentd admitted run identity mismatch".into());
        }
        if expected_generation == 0 || receipt.generation != expected_generation {
            return Err("Agentd admitted run generation mismatch".into());
        }
        if receipt.terminal_observed {
            return Err("Agentd admitted run is already terminal".into());
        }
        let expected_revision = match receipt.phase {
            AgentRunPhase::ContextAttached => {
                if receipt.dispatch_binding_digest.is_some()
                    || receipt.pre_effect_abort_commitment_digest.is_some()
                    || receipt.pre_effect_abort_proof_digest.is_some()
                {
                    return Err("Agentd context-attached run contains dispatch state".into());
                }
                receipt.revision
            }
            AgentRunPhase::Dispatched => {
                if receipt.dispatch_binding_digest.is_none()
                    || receipt.pre_effect_abort_commitment_digest.is_none()
                    || receipt.pre_effect_abort_proof_digest.is_some()
                {
                    return Err("Agentd dispatched run lacks its exact recovery binding".into());
                }
                receipt
                    .revision
                    .checked_sub(1)
                    .ok_or("Agentd dispatch revision underflow")?
            }
            _ => {
                return Err(
                    "Agentd run is not eligible for runtime.codex execution or reconciliation"
                        .into(),
                );
            }
        };
        if expected_revision == 0 {
            return Err("Agentd admitted run revision is zero".into());
        }
        let context_digest = receipt
            .context_digest
            .ok_or("Agentd admitted run omitted its context digest")?;
        let envelope_digest = receipt
            .compilation_receipt_digest
            .ok_or("Agentd admitted run omitted its compilation receipt digest")?;
        if !runtime_codex_sha256_hex(&context_digest)
            || !runtime_codex_sha256_hex(&envelope_digest)
        {
            return Err("Agentd admitted run contains a non-canonical digest".into());
        }
        Ok(Self {
            run_id: receipt.run_id,
            expected_revision,
            context_digest,
            envelope_digest,
        })
    }
}

fn runtime_codex_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
}
'''
    if struct not in text:
        raise RuntimeError("agentd-admitted binding: binding struct absent")
    return text.replace(struct, addition, 1)


def worker_cli(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-executor-v1"
    if marker in text:
        return text
    text = text.replace(
        "use codex_hepta_contracts::AgentId;\n",
        "use codex_hepta_agentd::AgentdClient;\nuse codex_hepta_contracts::AgentId;\n",
        1,
    )
    old_vars = '''    let mut intelligence_run_id = None;
    let mut intelligence_revision = None;
    let mut intelligence_context_digest = None;
    let mut intelligence_envelope_digest = None;
    let mut native_profile_selected = false;
'''
    new_vars = '''    let mut execution_mode = None;
    let mut intelligence_run_id = None;
    let mut native_profile_selected = false;
'''
    text = replace_once(text, old_vars, new_vars, marker)
    old_help = "[--intelligence-run-id ID --intelligence-revision N --intelligence-context-digest HEX --intelligence-envelope-digest HEX]"
    new_help = "--execution-mode agentd-admitted|unbound-development [--intelligence-run-id ID]"
    if old_help not in text:
        raise RuntimeError("agentd-admitted executor: help contract absent")
    text = text.replace(old_help, new_help, 1)
    text = text.replace(
        "Reads one prompt from stdin; an independent final-use authority must sign the exact turn/start binding before model dispatch.",
        "Reads one prompt from stdin. In agentd-admitted mode the worker loads the immutable run revision/context/envelope from Agentd; an independent final-use authority must still sign the exact turn/start binding before model dispatch.",
        1,
    )
    old_flags = '''            "--intelligence-run-id" => intelligence_run_id = Some(value),
            "--intelligence-revision" => intelligence_revision = Some(value.parse()?),
            "--intelligence-context-digest" => intelligence_context_digest = Some(value),
            "--intelligence-envelope-digest" => intelligence_envelope_digest = Some(value),
'''
    new_flags = '''            "--execution-mode" if value == "agentd-admitted" || value == "unbound-development" => {
                execution_mode = Some(value)
            }
            "--execution-mode" => return Err(format!("unsupported execution mode: {value}").into()),
            "--intelligence-run-id" => intelligence_run_id = Some(value),
'''
    text = replace_once(text, old_flags, new_flags, marker)
    old_driver = '''    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: socket.ok_or("--agentd-socket is required")?,
        agent_id: agent_id.ok_or("--agent-id is required")?,
        generation: generation.ok_or("--generation is required")?,
        model: model.ok_or("--model is required")?,
        timeout: Duration::from_millis(timeout_ms),
    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
'''
    new_driver = '''    // runtime.codex-agentd-admitted-executor-v1: retain the owner identity
    // for the durable binding lookup; the driver receives the same exact values.
    let agentd_socket = socket.ok_or("--agentd-socket is required")?;
    let agent_id = agent_id.ok_or("--agent-id is required")?;
    let generation = generation.ok_or("--generation is required")?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: agentd_socket.clone(),
        agent_id: agent_id.clone(),
        generation,
        model: model.ok_or("--model is required")?,
        timeout: Duration::from_millis(timeout_ms),
    })?
    .with_turn_start_authorizer(Arc::new(final_use_authorizer));
'''
    text = replace_once(text, old_driver, new_driver, marker)
    old_binding = '''    let intelligence = match (
        intelligence_run_id,
        intelligence_revision,
        intelligence_context_digest,
        intelligence_envelope_digest,
    ) {
        (None, None, None, None) => None,
        (Some(run_id), Some(expected_revision), Some(context_digest), Some(envelope_digest)) => {
            Some(NativeIntelligenceRunBinding {
                run_id,
                expected_revision,
                context_digest,
                envelope_digest,
            })
        }
        _ => {
            return Err("all four --intelligence-* arguments must be supplied together".into());
        }
    };
'''
    new_binding = '''    let intelligence = match (execution_mode.as_deref(), intelligence_run_id) {
        (Some("agentd-admitted"), Some(run_id)) => {
            let receipt = AgentdClient::new(agentd_socket, agent_id, generation)?
                .run_status(run_id.clone())
                .await?
                .ok_or("Agentd has no durable admitted work for --intelligence-run-id")?;
            Some(NativeIntelligenceRunBinding::from_agentd_receipt(
                &run_id,
                generation,
                receipt,
            )?)
        }
        (Some("unbound-development"), None) => None,
        (Some("agentd-admitted"), None) => {
            return Err("agentd-admitted mode requires --intelligence-run-id".into());
        }
        (Some("unbound-development"), Some(_)) => {
            return Err("unbound-development mode forbids --intelligence-run-id".into());
        }
        (None, _) => return Err("--execution-mode must be selected explicitly".into()),
        _ => unreachable!("execution mode was validated while parsing"),
    };
'''
    return replace_once(text, old_binding, new_binding, marker)


def native_run_control_tests(text: str) -> str:
    marker = "agentd_admitted_binding_rejects_caller_minted_or_terminal_state"
    if marker in text:
        return text
    text = text.replace(
        "use codex_hepta_contracts::AgentId;\n",
        "use codex_hepta_agentd::AgentRunPhase;\nuse codex_hepta_agentd::AgentRunReceipt;\nuse codex_hepta_contracts::AgentId;\n",
        1,
    )
    addition = r'''

fn admitted_receipt(phase: AgentRunPhase) -> AgentRunReceipt {
    let dispatched = phase == AgentRunPhase::Dispatched;
    AgentRunReceipt {
        run_id: "intelligence-run".to_string(),
        revision: if dispatched { 3 } else { 2 },
        phase,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 9,
        generation: 7,
        fence_digest: "c".repeat(64),
        deadline_ms: 50_000,
        dispatch_binding_digest: dispatched.then(|| "d".repeat(64)),
        pre_effect_abort_commitment_digest: dispatched.then(|| "e".repeat(64)),
        pre_effect_abort_proof_digest: None,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: false,
    }
}

#[test]
fn agentd_admitted_binding_is_derived_from_durable_owner_state() {
    let attached = NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        admitted_receipt(AgentRunPhase::ContextAttached),
    )
    .unwrap();
    assert_eq!(attached.expected_revision, 2);
    assert_eq!(attached.context_digest, "a".repeat(64));
    assert_eq!(attached.envelope_digest, "b".repeat(64));

    let dispatched = NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        admitted_receipt(AgentRunPhase::Dispatched),
    )
    .unwrap();
    assert_eq!(dispatched, attached);
}

#[test]
fn agentd_admitted_binding_rejects_caller_minted_or_terminal_state() {
    let mut wrong_generation = admitted_receipt(AgentRunPhase::ContextAttached);
    assert!(NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        8,
        wrong_generation.clone(),
    )
    .is_err());
    wrong_generation.run_id = "other-run".to_string();
    assert!(NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        wrong_generation,
    )
    .is_err());

    let mut terminal = admitted_receipt(AgentRunPhase::Succeeded);
    terminal.terminal_observed = true;
    assert!(NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        terminal,
    )
    .is_err());

    let mut malformed = admitted_receipt(AgentRunPhase::ContextAttached);
    malformed.context_digest = Some("A".repeat(64));
    assert!(NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        malformed,
    )
    .is_err());

    let mut incomplete_dispatch = admitted_receipt(AgentRunPhase::Dispatched);
    incomplete_dispatch.pre_effect_abort_commitment_digest = None;
    assert!(NativeIntelligenceRunBinding::from_agentd_receipt(
        "intelligence-run",
        7,
        incomplete_dispatch,
    )
    .is_err());
}
'''
    return text.rstrip() + addition + "\n"


def product_e2e(text: str) -> str:
    marker = "runtime.codex-agentd-admitted-product-e2e-v1"
    if marker in text:
        return text
    text = text.replace(
        "use codex_hepta_contracts::FinalUseBinding;\n",
        "use codex_hepta_agentd::AgentContextAttachment;\nuse codex_hepta_agentd::AgentRunPhase;\nuse codex_hepta_agentd::AgentRunSnapshot;\nuse codex_hepta_agentd::AgentdClient;\nuse codex_hepta_contracts::FinalUseBinding;\n",
        1,
    )
    text = text.replace(
        "use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;\n",
        "use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;\nuse codex_hepta_infer_worker_host::native_app_server::NativeIntelligenceRunBinding;\n",
        1,
    )
    ready = '''    let (_, health) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    ensure!(health.ready && !health.fenced);
'''
    ready_new = ready + '''
    // runtime.codex-agentd-admitted-product-e2e-v1: create and attach the
    // durable owner record first. The worker derives its immutable binding
    // from this receipt rather than accepting caller-selected fields.
    let agentd = AgentdClient::new(
        agent.layout.agentd_control_socket().to_path_buf(),
        agent.agent_id.clone(),
        1,
    )?;
    let deadline_ms = u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?
    .checked_add(60_000)
    .context("runtime.codex product deadline overflow")?;
    let snapshot = AgentRunSnapshot {
        run_id: REQUEST_ID.to_string(),
        request_digest: "1".repeat(64),
        objective_digest: "2".repeat(64),
        body_digest: "3".repeat(64),
        artifact_set_digest: "4".repeat(64),
        authority_epoch: 9,
        generation: 1,
        fence_digest: "5".repeat(64),
        deadline_ms,
    };
    let admitted = agentd.run_start(snapshot.clone()).await?;
    ensure!(admitted.phase == AgentRunPhase::Admitted);
    let attached = agentd
        .run_attach_context(
            admitted.revision,
            AgentContextAttachment {
                run_id: snapshot.run_id.clone(),
                request_digest: snapshot.request_digest.clone(),
                objective_digest: snapshot.objective_digest.clone(),
                body_digest: snapshot.body_digest.clone(),
                artifact_set_digest: snapshot.artifact_set_digest.clone(),
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest.clone(),
                deadline_ms: snapshot.deadline_ms,
                context_digest: "6".repeat(64),
                compilation_receipt_digest: "7".repeat(64),
            },
        )
        .await?;
    ensure!(attached.phase == AgentRunPhase::ContextAttached);
    let intelligence = NativeIntelligenceRunBinding::from_agentd_receipt(
        REQUEST_ID,
        1,
        attached,
    )
    .map_err(|error| anyhow::anyhow!(error.to_string()))?;
'''
    text = replace_once(text, ready, ready_new, marker)
    old_run = '''    let output = driver
        .run(
            &mut control,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase runtime codex e2e.".to_string(),
            None,
            &cancellation,
        )
'''
    new_run = '''    let output = driver
        .run_intelligence(
            &mut control,
            NativeAdmission {
                request_id: REQUEST_ID.to_string(),
                maximum_in_flight: 1,
            },
            "Return the exact phrase runtime codex e2e.".to_string(),
            None,
            intelligence,
            &cancellation,
        )
'''
    text = replace_once(text, old_run, new_run, marker)
    status_anchor = '''    ensure!(output.terminal_observed);
'''
    status_new = status_anchor + '''    let owner_terminal = agentd
        .run_status(REQUEST_ID.to_string())
        .await?
        .context("Agentd terminal record disappeared")?;
    ensure!(owner_terminal.phase == AgentRunPhase::Succeeded);
    ensure!(owner_terminal.terminal_observed);
'''
    if status_anchor not in text:
        raise RuntimeError("agentd-admitted product e2e: output assertion anchor absent")
    return text.replace(status_anchor, status_new, 1)


def quickstart(text: str) -> str:
    marker = "## Agentd-admitted product execution"
    if marker in text:
        return text
    return text.rstrip() + r'''

## Agentd-admitted product execution

Production composition uses `--execution-mode agentd-admitted` and supplies only
`--intelligence-run-id`. The worker reads the durable Agentd run receipt and
derives the revision, context digest and compilation-receipt digest itself.
Those fields are intentionally not command-line options.

```text
hepta-infer-worker \
  --profile native-app-server \
  --execution-mode agentd-admitted \
  --intelligence-run-id <durably-attached-run-id> \
  --agentd-socket /run/hepta/agentd.sock \
  --agent-id <agent-id> \
  --generation <generation> \
  --model <model> \
  --journal /var/lib/hepta/runtime-codex.journal \
  --request-id <same-operation-id> \
  --maximum-in-flight 256 \
  --final-use-authority-config /etc/hepta/runtime-codex-final-use.json
```

`unbound-development` is an explicit model-only development mode. It is not a
product admission path and cannot be combined with `--intelligence-run-id`.
''' + "\n"


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/native_run_control.rs", native_run_control)
    rewrite("codex-rs/hepta-infer-worker-host/src/bin/hepta-infer-worker.rs", worker_cli)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs", native_run_control_tests)
    rewrite("codex-rs/hepta-agentd/tests/runtime_codex_product_e2e.rs", product_e2e)
    rewrite("docs/modules/runtime.codex/QUICKSTART.md", quickstart)


if __name__ == "__main__":
    main()
