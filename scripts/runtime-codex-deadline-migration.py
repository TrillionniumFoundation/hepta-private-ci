#!/usr/bin/env python3
"""Propagate one absolute pre-effect deadline through runtime.codex awaits."""

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
            raise RuntimeError(f"{marker}: expected one legacy block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and migrated marker both absent")


def execution(text: str) -> str:
    replacements = [
        (
            "        let health = owner.health().await?;\n",
            '''        let health = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd health",
            owner.health(),
        )
        .await?;
''',
            '"Agentd health"',
        ),
        (
            "            let capabilities = owner.capabilities().await?;\n",
            '''            let capabilities = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd capabilities",
                owner.capabilities(),
            )
            .await?;
''',
            '"Agentd capabilities"',
        ),
        (
            "            Some(binding) => Some(require_intelligence_handoff(&owner, binding).await?),\n",
            '''            Some(binding) => Some(
                require_intelligence_handoff(&execution_clock, &owner, binding).await?,
            ),
''',
            "require_intelligence_handoff(&execution_clock",
        ),
        (
            "        let ingress = owner.session_ingress().await?;\n",
            '''        let ingress = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd session ingress",
            owner.session_ingress(),
        )
        .await?;
''',
            '"Agentd session ingress"',
        ),
        (
            '''        let mut client = timeout(
            RPC_TIMEOUT,
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 256,
            ),
        )
        .await??;
''',
            '''        let mut client = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "App Server connect",
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-infer-worker".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 32,
                },
                /*event_channel_capacity*/ 256,
            ),
        )
        .await?;
''',
            '"App Server connect"',
        ),
        (
            '''        let started: ThreadStartResponse = timeout(
            RPC_TIMEOUT,
            client.request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    model: Some(self.config.model.clone()),
                    cwd: health.workspace.to_str().map(str::to_string),
                    approval_policy: Some(AskForApproval::Never),
                    sandbox: Some(SandboxMode::ReadOnly),
                    ephemeral: Some(true),
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await??;
''',
            '''        let started: ThreadStartResponse = await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "App Server thread/start",
            client.request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    model: Some(self.config.model.clone()),
                    cwd: health.workspace.to_str().map(str::to_string),
                    approval_policy: Some(AskForApproval::Never),
                    sandbox: Some(SandboxMode::ReadOnly),
                    ephemeral: Some(true),
                    environments: Some(Vec::new()),
                    ..Default::default()
                },
            }),
        )
        .await?;
''',
            '"App Server thread/start"',
        ),
        (
            "        owner.session_ingress().await?;\n",
            '''        await_before_effect(
            &execution_clock,
            RPC_TIMEOUT,
            "Agentd ingress recheck",
            owner.session_ingress(),
        )
        .await?;
''',
            '"Agentd ingress recheck"',
        ),
        (
            "            Some(query) => Some(owner.cognitive_context(query, /*limit*/ 4).await?),\n",
            '''            Some(query) => Some(
                await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd cognitive context",
                    owner.cognitive_context(query, /*limit*/ 4),
                )
                .await?,
            ),
''',
            '"Agentd cognitive context"',
        ),
        (
            "            let current_revision = require_intelligence_handoff(&owner, binding).await?;\n",
            '''            let current_revision =
                require_intelligence_handoff(&execution_clock, &owner, binding).await?;
''',
            "require_intelligence_handoff(&execution_clock, &owner, binding)",
        ),
        (
            '''                let dispatched = owner
                    .run_mark_dispatched_bound(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_binding_digest.clone(),
                        commitment.clone(),
                    )
                    .await?;
''',
            '''                let dispatched = await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd bound dispatch commit",
                    owner.run_mark_dispatched_bound(
                        binding.run_id.clone(),
                        binding.expected_revision,
                        dispatch_binding_digest.clone(),
                        commitment.clone(),
                    ),
                )
                .await?;
''',
            '"Agentd bound dispatch commit"',
        ),
        (
            "            let post_health = owner.health().await?;\n",
            '''            let post_health = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd final health",
                owner.health(),
            )
            .await?;
''',
            '"Agentd final health"',
        ),
        (
            "            let current_ingress = owner.session_ingress().await?;\n",
            '''            let current_ingress = await_before_effect(
                &execution_clock,
                RPC_TIMEOUT,
                "Agentd final ingress",
                owner.session_ingress(),
            )
            .await?;
''',
            '"Agentd final ingress"',
        ),
        (
            '''                let revalidated = owner
                    .revalidate_cognitive_context(snapshot)
                    .await
                    .map_err(|error| format!("cognitive final-use revalidation failed: {error}"))?;
''',
            '''                let revalidated = await_before_effect(
                    &execution_clock,
                    RPC_TIMEOUT,
                    "Agentd cognitive final-use revalidation",
                    owner.revalidate_cognitive_context(snapshot),
                )
                .await
                .map_err(|error| format!("cognitive final-use revalidation failed: {error}"))?;
''',
            '"Agentd cognitive final-use revalidation"',
        ),
    ]
    for old, new, marker in replacements:
        text = replace_once(text, old, new, marker)

    if "async fn await_before_effect" not in text:
        helper = r'''

async fn await_before_effect<T, E, F>(
    clock: &crate::native_deadline::NativeDeadline,
    per_hop_cap: Duration,
    operation: &'static str,
    future: F,
) -> Result<T>
where
    F: std::future::Future<Output = std::result::Result<T, E>>,
    E: Into<Box<dyn std::error::Error + Send + Sync>>,
{
    let budget = clock.remaining(unix_time_ms()?)?.min(per_hop_cap);
    match timeout(budget, future).await {
        Ok(Ok(value)) => Ok(value),
        Ok(Err(error)) => Err(error.into()),
        Err(_) => Err(format!("{operation} exceeded the runtime.codex absolute deadline").into()),
    }
}
'''
        text = text.rstrip() + helper + "\n"
    return text


def app_server(text: str) -> str:
    old = '''async fn require_intelligence_handoff(
    owner: &AgentdClient,
    binding: &NativeIntelligenceRunBinding,
) -> Result<u64> {
'''
    new = '''async fn require_intelligence_handoff(
    clock: &crate::native_deadline::NativeDeadline,
    owner: &AgentdClient,
    binding: &NativeIntelligenceRunBinding,
) -> Result<u64> {
'''
    text = replace_once(text, old, new, "clock: &crate::native_deadline::NativeDeadline")
    old = '''    let run = owner
        .run_status(binding.run_id.clone())
        .await?
        .ok_or("intelligence run is not admitted in Agentd")?;
'''
    new = '''    let run = execution::await_before_effect(
        clock,
        RPC_TIMEOUT,
        "Agentd intelligence handoff",
        owner.run_status(binding.run_id.clone()),
    )
    .await?
    .ok_or("intelligence run is not admitted in Agentd")?;
'''
    text = replace_once(text, old, new, '"Agentd intelligence handoff"')
    return text


def main() -> None:
    rewrite("codex-rs/hepta-infer-worker-host/src/native_execution.rs", execution)
    rewrite("codex-rs/hepta-infer-worker-host/src/native_app_server.rs", app_server)


if __name__ == "__main__":
    main()
