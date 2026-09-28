#!/usr/bin/env python3
"""Bounded source authoring, isolated from the product and qualification tree."""
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1]).resolve()
expected = "1ea9d0fd8a913661d407c7f4ebb9a865a907539e"
if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != expected:
    raise SystemExit("source drift")

def replace(path, old, new, count=1):
    target = root / path
    text = target.read_text()
    if text.count(old) != count:
        raise SystemExit(f"unexpected anchor count {path}: {text.count(old)} != {count}")
    target.write_text(text.replace(old, new))

subprocess.run(["python3", str(root / "scripts/apply-prompt-publisher-lifecycle.py")], check=True, cwd=root)
replace("codex-rs/hepta-agentd/src/prompt_runtime.rs", '    #[allow(clippy::too_many_arguments)]', '    #[expect(clippy::too_many_arguments, reason = "Preserve explicit signed operation-bound fields")]', count=3)
path = "codex-rs/hepta-agentd/src/prompt_runtime_tests.rs"
text = (root / path).read_text()
start = text.index('    let actor = id("operator:agentd-revoke");')
end = text.index('    let request = PromptRuntimePrepareRequest {', start)
part = text[start:end].replace('let mut registry = pipeline', 'let registry = pipeline', 1)
old = '        registry\n            .revoke_factor_final_use('
if part.count(old) != 1:
    raise SystemExit("missing governed revoke test call")
part = part.replace(old, '        drop(registry);\n        pipeline\n            .revoke_factor(', 1)
(root / path).write_text(text[:start] + part + text[end:])
path = "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs"
replace(path, '    assert_eq!(manifest["schema"], 3);', '    assert_eq!(manifest["schema"], 4);\n    assert_eq!(manifest["state"]["schema"], 4);\n    assert_eq!(manifest["state"]["relations"], serde_json::json!([]));')
replace(path, '        "schema",\n    ] {', '        "schema",\n        "inner-schema",\n        "missing-relations",\n    ] {')
replace(path, '            "schema" => value["schema"] = 4.into(),', '            "schema" => value["schema"] = 5.into(),\n            "inner-schema" => value["state"]["schema"] = 5.into(),\n            "missing-relations" => {\n                value["state"].as_object_mut().must("state object").remove("relations");\n            }')
path = "codex-rs/hepta-agentd/src/prompt_final_use.rs"
replace(path, '            DurableRegistryError::CapacityExceeded | DurableRegistryError::StorageFull => {', '            DurableRegistryError::CapacityExceeded\n            | DurableRegistryError::StorageFull\n            | DurableRegistryError::Core(codex_hepta_prompt_registry::Error::CapacityExceeded) => {')
replace(path, '#[cfg(test)]\n#[path = "prompt_final_use_tests.rs"]', '#[cfg(all(test, unix))]\n#[path = "prompt_final_use_tests.rs"]')
print("Strict V4 fixtures and governed lifecycle facade corrected; qualification pending")
