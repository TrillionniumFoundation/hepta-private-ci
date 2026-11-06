from pathlib import Path
import difflib
import hashlib
import json

ROOT = Path('/workspace/scratch/08f5efd48967')
BASE = ROOT / 'core-hooks-r14-audit/original'
OUT = ROOT / 'core-hook-binding-r14-repair'
operations = []
files = {}

def edit(path, before, after):
    source = files.setdefault(path, (BASE / path).read_text())
    assert source.count(before) == 1, (path, before[:100])
    files[path] = source.replace(before, after, 1)
    operations.append({'path': path, 'before': before, 'after': after})

edit('codex-rs/codex-mcp/src/binding.rs',
'''    pub fn has_servers(&self) -> bool {
''',
'''    /// Binds a configured hook to a permitted tool, including model-hidden tools.
    ///
    /// Hook configuration and governance are checked by the hook owner. This
    /// uses the same filtered catalog and exact client/revision as model calls;
    /// it does not add tools to the model-visible catalog or relax `prepare_call`.
    pub fn prepare_hook_call(&self, server: &str, tool: &str) -> Option<PreparedMcpCall> {
        self.calls
            .get(&(server.to_string(), tool.to_string()))
            .cloned()
    }

    pub fn has_servers(&self) -> bool {
''')

edit('codex-rs/core/src/hook_mcp_executor.rs',
     'binding.prepare_call(&call.server, &call.tool)',
     'binding.prepare_hook_call(&call.server, &call.tool)')

path = 'codex-rs/codex-mcp/src/connection_manager_tests.rs'
edit(path,
'''    let mut ready_client = create_test_managed_client(vec![
        create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "client_local_tool"),
        create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "client_local_blocked"),
    ])
''',
'''    let mut hidden_tool = create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "client_local_hidden");
    let mut hidden_meta = rmcp::model::MetaObject::new();
    hidden_meta.insert("ui".to_string(), serde_json::json!({ "visibility": [] }));
    hidden_tool.tool.meta = Some(hidden_meta);
    let mut ready_client = create_test_managed_client(vec![
        create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "client_local_tool"),
        create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "client_local_blocked"),
        hidden_tool,
    ])
''')
edit(path,
'''    assert!(
        step.prepare_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_blocked")
            .is_none()
    );
''',
'''    assert!(
        step.prepare_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_blocked")
            .is_none()
    );
    assert!(
        step.prepare_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_hidden")
            .is_none()
    );
    assert!(
        step.prepare_hook_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_hidden")
            .is_some()
    );
    assert!(
        step.prepare_hook_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_tool")
            .is_some()
    );
    assert!(
        step.prepare_hook_call(CODEX_APPS_MCP_SERVER_NAME, "shared_cached_tool")
            .is_none()
    );
    assert!(
        step.prepare_hook_call(CODEX_APPS_MCP_SERVER_NAME, "client_local_blocked")
            .is_none()
    );
''')
edit(path,
'''    let removed = reconcile_reusable_server(&reused, config, runtime_context).await;
    assert!(!removed.servers.contains_key("docs"));
''',
'''    let removed = reconcile_reusable_server(&reused, config, runtime_context).await;
    assert!(!removed.servers.contains_key("docs"));
    let removed = Arc::new(removed);
    let removed_binding = capture_binding(&removed).await;
    assert!(removed_binding.prepare_hook_call("docs", "search").is_none());
''')

path = 'codex-rs/codex-mcp/src/binding_tests.rs'
edit(path,
'''use codex_config::AppToolApproval;
''',
'''use anyhow::Context;
use codex_config::AppToolApproval;
''')
before = (BASE / path).read_text()
test = '''
#[tokio::test]
async fn hook_call_retains_owner_and_rejects_stale_catalog_before_preparation() -> anyhow::Result<()> {
    let step = test_step(
        "old",
        AppToolApproval::Prompt,
        /*supports_sandbox_state_meta*/ true,
    )
    .await;
    let prepared = step
        .step
        .prepare_hook_call(SERVER_NAME, TOOL_NAME)
        .context("configured hook should retain the permitted original call")?;
    assert!(Arc::ptr_eq(&prepared.client.client, &step.client));
    assert_eq!(
        (prepared.server_environment_id(), prepared.tool_approval_mode()),
        ("old-environment", AppToolApproval::Prompt)
    );

    *step.tool_catalog_revision.write().await += 1;
    let preparation_ran = Arc::new(AtomicBool::new(false));
    let marker = Arc::clone(&preparation_ran);
    let error = prepared
        .call_with_preparation(/*requested_timeout*/ None, || async move {
            marker.store(true, Ordering::SeqCst);
            Ok((None, None))
        })
        .await
        .err()
        .context("a stale hook call must fail before irreversible preparation")?;
    assert!(format!("{error:#}").contains("catalog changed"));
    assert!(!preparation_ran.load(Ordering::SeqCst));
    Ok(())
}
'''
files[path] += test
operations.append({'path': path, 'before': '', 'after': test, 'append': True})

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

manifest = []
patches = []
for path, content in files.items():
    original = (BASE / path).read_bytes()
    dest = OUT / 'source' / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    inverse = content
    for op in reversed([op for op in operations if op['path'] == path]):
        if op.get('append'):
            assert inverse.endswith(op['after'])
            inverse = inverse[:-len(op['after'])]
        else:
            assert inverse.count(op['after']) == 1
            inverse = inverse.replace(op['after'], op['before'], 1)
    assert inverse.encode() == original, path
    manifest.append({'path': path, 'git_mode': '100644', 'before': identity(original),
                     'after': identity(dest.read_bytes()), 'exact_inverse': True})
    patches.append(''.join(difflib.unified_diff(original.decode().splitlines(keepends=True), content.splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path)))

(OUT / 'repair.patch').write_text(''.join(patches))
(OUT / 'edit-operations.json').write_text(json.dumps(operations, indent=2) + '\n')
(OUT / 'source-manifest.json').write_text(json.dumps({'source_commit': 'b44d4ca4aa0ef9f894eff29e9975938e066a82f5', 'source_tree': 'd3d2313b838422818bf9448ce5a1b86d89abdf69', 'files': manifest}, indent=2) + '\n')
print(json.dumps({'files': manifest, 'patch': identity((OUT / 'repair.patch').read_bytes())}, indent=2))
