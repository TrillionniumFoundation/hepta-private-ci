from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Raw durable mutations remain useful inside the owning crate's deterministic
# fixtures, but they are not an external product capability.
durable = "codex-rs/hepta-prompt-registry/src/durable.rs"
replace_once(
    durable,
    "    pub fn register_factor(\n",
    "    pub(crate) fn register_factor(\n",
)
replace_once(
    durable,
    "    pub fn register_factor_relation(\n",
    "    pub(crate) fn register_factor_relation(\n",
)

runtime = Path("codex-rs/hepta-agentd/src/prompt_runtime.rs")
text = runtime.read_text(encoding="utf-8")
replacements = [
    (
        "pub struct AgentdPromptRuntimeOwner {\n",
        "pub(crate) struct AgentdPromptRuntimeOwner {\n",
    ),
    (
        "    pub fn host(self: &Arc<Self>) -> Result<PromptRuntimeHost, AgentdPromptRuntimeError> {\n",
        "    pub(crate) fn host(\n        self: &Arc<Self>,\n    ) -> Result<PromptRuntimeHost, AgentdPromptRuntimeError> {\n",
    ),
    (
        "    #[must_use]\n    pub fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n        Arc::clone(&self.runtime)\n    }\n\n",
        "    #[cfg(test)]\n    #[must_use]\n    pub(crate) fn runtime_owner(&self) -> Arc<AgentdPromptRuntimeOwner> {\n        Arc::clone(&self.runtime)\n    }\n\n",
    ),
]
for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"prompt_runtime.rs: expected one match for {old.splitlines()[0]!r}")
    text = text.replace(old, new, 1)

owner_marker = "/// Named Agentd composition owner for the canonical prompt-intervention path.\n"
wrapper = '''/// Product-only prompt capability. The raw runtime owner and its ungated host
/// remain crate-private; App Server receives only this final-use-fenced handle.
pub(crate) struct PromptPipelineHost(PromptRuntimeHost);

impl PromptPipelineHost {
    pub(crate) fn into_runtime_host(self) -> PromptRuntimeHost {
        self.0
    }
}

'''
if text.count(owner_marker) != 1:
    raise SystemExit("prompt pipeline owner marker changed")
text = text.replace(owner_marker, wrapper + owner_marker, 1)

start = text.index("    /// Product host that enforces the durable registry lease both when\n")
end = text.index("    /// Authenticated production writer for draft factor publication.\n", start)
old_host = text[start:end]
new_host = '''    /// Product host that enforces the durable registry lease both when
    /// exposing staged bytes and immediately before provider dispatch.
    pub(crate) fn host(
        self: &Arc<Self>,
    ) -> Result<PromptPipelineHost, AgentdPromptPipelineError> {
        let prepare_owner = Arc::clone(self);
        let dispatch_owner = Arc::clone(self);
        let record_owner = Arc::clone(self);
        let host = PromptRuntimeHost::new(
            PROMPT_RUNTIME_CAPABILITY_ID,
            move |request: PromptRuntimePrepareRequest| -> PromptRuntimePrepareFuture {
                let owner = Arc::clone(&prepare_owner);
                Box::pin(async move { owner.prepare_final_use(request) })
            },
            move |record: PromptRuntimeDispatchRecordV1| -> PromptRuntimeDispatchFuture {
                let owner = Arc::clone(&dispatch_owner);
                Box::pin(async move { owner.record_dispatch_final_use(record) })
            },
            move |record: PromptRuntimeTerminalRecordV1| -> PromptRuntimeRecordFuture {
                let owner = Arc::clone(&record_owner);
                Box::pin(async move { owner.record_terminal_final_use(record) })
            },
        )
        .map_err(|error| {
            AgentdPromptPipelineError::Stage(AgentdPromptRuntimeError::Adapter(error.to_string()))
        })?;
        Ok(PromptPipelineHost(host))
    }

'''
if "PromptRuntimeHost::new" not in old_host:
    raise SystemExit("product host body changed unexpectedly")
text = text[:start] + new_host + text[end:]
runtime.write_text(text, encoding="utf-8")

replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use prompt_runtime::AgentdPromptRuntimeOwner;\n",
    "",
)
replace_once(
    "codex-rs/hepta-agentd/src/app_runtime.rs",
    "    let prompt_runtime_host = state\n        .prompt_pipeline_owner()\n        .host()\n        .map_err(std::io::Error::other)?;\n",
    "    let prompt_runtime_host = state\n        .prompt_pipeline_owner()\n        .host()\n        .map_err(std::io::Error::other)?\n        .into_runtime_host();\n",
)

# Convert the implementation map from a curated list to a checked closed-world
# inventory for the authoritative owner and product capability boundary.
mapper = Path("scripts/hepta-prompt-registry-map.py")
map_text = mapper.read_text(encoding="utf-8")
map_text = map_text.replace(
    '    "codex-rs/ext/hepta-prompt",\n',
    '    "codex-rs/ext/extension-api",\n    "codex-rs/ext/hepta-prompt",\n',
    1,
)

build_marker = "\ndef build(observation: dict[str, str]) -> dict:\n"
helper = r'''

def impl_public_methods(path: str, type_name: str) -> list[str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    methods: set[str] = set()
    cursor = 0
    marker = f"impl {type_name} {{"
    while True:
        start = text.find(marker, cursor)
        if start < 0:
            break
        brace = text.find("{", start)
        depth = 0
        end = None
        for index in range(brace, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            raise ValueError(f"unterminated impl block: {path}::{type_name}")
        block = text[brace + 1:end]
        methods.update(re.findall(r"(?m)^\s*pub\s+(?:const\s+)?fn\s+(\w+)\b", block))
        cursor = end + 1
    if cursor == 0:
        raise ValueError(f"missing impl block: {path}::{type_name}")
    return sorted(methods)


def closed_world_public_surface() -> list[dict[str, object]]:
    expected = {
        DURABLE: sorted([
            "open_state_dir", "registry", "requires_reopen",
            "register_factor_final_use", "register_factor_relation_final_use",
            "admit_factor_final_use", "register_realization_payload_final_use_v2",
            "retire_factor_final_use", "revoke_factor_final_use", "snapshot_v2",
            "read_compatible_v2", "dereference_realization_v2",
        ]),
        MAINTENANCE: sorted([
            "operational_metrics", "export_consistent_checkpoint",
            "checkpoint_compacted", "verify_restore_checkpoint", "probe_fsync",
        ]),
        CORE + "/src/durable_gc.rs": ["collect_payload_garbage"],
    }
    inventory: list[dict[str, object]] = []
    for path, allowed in expected.items():
        actual = impl_public_methods(path, "DurablePromptRegistry")
        if actual != allowed:
            raise ValueError(
                f"prompt registry public surface drift: {path}: expected={allowed}, actual={actual}"
            )
        inventory.append({"path": path, "publicMethods": actual})
    failure_methods = impl_public_methods(CORE + "/src/failure.rs", "DurableRegistryError")
    if failure_methods != ["failure"]:
        raise ValueError(f"durable failure public surface drift: {failure_methods}")
    inventory.append({
        "path": CORE + "/src/failure.rs",
        "publicMethods": failure_methods,
    })
    agentd_lib = (ROOT / "codex-rs/hepta-agentd/src/lib.rs").read_text(encoding="utf-8")
    runtime = (ROOT / RUNTIME).read_text(encoding="utf-8")
    app_runtime = (ROOT / "codex-rs/hepta-agentd/src/app_runtime.rs").read_text(encoding="utf-8")
    if "pub use prompt_runtime::AgentdPromptRuntimeOwner;" in agentd_lib:
        raise ValueError("raw prompt runtime owner remains publicly re-exported")
    if re.search(r"(?m)^\s*pub\s+fn\s+runtime_owner\b", runtime):
        raise ValueError("raw prompt runtime owner accessor remains public")
    if "pub(crate) struct PromptPipelineHost" not in runtime:
        raise ValueError("missing product-only PromptPipelineHost")
    if ".into_runtime_host();" not in app_runtime:
        raise ValueError("App Server does not consume PromptPipelineHost")
    inventory.append({
        "path": RUNTIME,
        "productHost": "PromptPipelineHost",
        "rawOwnerExported": False,
    })
    return inventory
'''
if map_text.count(build_marker) != 1:
    raise SystemExit("map build marker changed")
map_text = map_text.replace(build_marker, helper + build_marker, 1)

callers_marker = "    callers = []\n"
if map_text.count(callers_marker) != 1:
    raise SystemExit("callers marker changed")
map_text = map_text.replace(
    callers_marker,
    "    public_inventory = closed_world_public_surface()\n" + callers_marker,
    1,
)
map_text = map_text.replace(
    '        "closedWorldPublicFunctions": False,\n        "mappingCoverage": "curated_owner_and_boundary_operations_not_all_public_functions",\n',
    '        "closedWorldPublicFunctions": True,\n'
    '        "mappingCoverage": "closed_world_owner_and_product_capability_surface",\n'
    '        "publicFunctionInventory": public_inventory,\n',
    1,
)
map_text = map_text.replace(
    '"claimBoundary": {"nativeSourceMappingComplete": False, "sourceRootPresent": True,\n',
    '"claimBoundary": {"nativeSourceMappingComplete": True, "sourceRootPresent": True,\n',
    1,
)
mapper.write_text(map_text, encoding="utf-8")
