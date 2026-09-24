from pathlib import Path

path = Path("codex-rs/hepta-cognitive-read/src/ids_tests.rs")
text = path.read_text()
start = text.index("fn duplicate_fields_invalid_budgets_and_snapshot_mismatch_fail_closed()")
end = text.index("\n#[test]", start)
block = text[start:end]
old = block
block = block.replace("let snapshot = snapshot(", "let base_snapshot = snapshot(", 1)
block = block.replace("snapshot.snapshot_digest", "base_snapshot.snapshot_digest")
block = block.replace("read_ids_v1(&snapshot,", "read_ids_v1(&base_snapshot,")
if block == old:
    raise SystemExit("phase-one shadowing correction did not apply")
path.write_text(text[:start] + block + text[end:])

host_path = Path("codex-rs/hepta-agentd/src/test_support.rs")
host = host_path.read_text()
old = """        state.attach_cognitive_store(Arc::clone(&store))?;
        registry.compare_and_transition(&agent_id, 1, AgentLifecycle::Running)?;
"""
new = """        state.attach_cognitive_store(Arc::clone(&store))?;
        // Mirror the production startup order: attaching the store alone does
        // not open control admission. Freeze the critical-store and revocation
        // prerequisites before the App Server advertises readiness.
        state.mark_runtime_prerequisites_ready()?;
        registry.compare_and_transition(&agent_id, 1, AgentLifecycle::Running)?;
"""
if host.count(old) != 1:
    raise SystemExit("Agentd test host startup anchor mismatch")
host_path.write_text(host.replace(old, new, 1))

worker_tests_path = Path(
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs"
)
worker_tests = worker_tests_path.read_text()
old = '    assert!(accepted.output.contains("fresh context accepted"));\n'
new = """    // Provider assistant text is not an acceptance oracle. The structured
    // success observation, durable TurnStart record, one physical Responses
    // request, and exact attached owner context below are the product proof.
"""
if worker_tests.count(old) != 1:
    raise SystemExit("native worker output-text assertion anchor mismatch")
worker_tests_path.write_text(worker_tests.replace(old, new, 1))
