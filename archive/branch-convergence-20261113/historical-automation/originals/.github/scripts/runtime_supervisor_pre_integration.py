#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]

# Keep the test-only digest import distinct while the integration generator
# removes the newly inserted module-level import. rustfmt normalizes it later.
protocol_path = root / "codex-rs/hepta-supervisor/src/daemon_protocol.rs"
protocol = protocol_path.read_text()
old_import = (
    "    use crate::ProductionMutationStatus;\n"
    "    use codex_hepta_contracts::Sha256Digest;\n"
)
new_import = (
    "    use crate::ProductionMutationStatus;\n"
    "    use codex_hepta_contracts::{Sha256Digest};\n"
)
count = protocol.count(old_import)
if count != 1:
    raise RuntimeError(
        f"daemon_protocol test import context changed: expected 1, found {count}"
    )
protocol_path.write_text(protocol.replace(old_import, new_import, 1))

# The signed and ordinary mutation handlers intentionally share an identical
# three-line prelude in the source. Teach the first generator patch to replace
# only the first occurrence; after that, the second occurrence is again unique
# and retains the stronger replace_once assertion.
integration_path = root / ".github/scripts/runtime_supervisor_integration.py"
integration = integration_path.read_text()
helper_marker = "\ndef replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:\n"
if integration.count(helper_marker) != 1:
    raise RuntimeError("integration helper insertion point changed")
replace_first_helper = '''
def replace_first(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count < 1:
        raise RuntimeError(f"{path}: expected at least one replacement, found 0: {old[:160]!r}")
    write(path, content.replace(old, new, 1))

'''
integration = integration.replace(
    helper_marker,
    replace_first_helper + helper_marker,
    1,
)
call_prefix = (
    "replace_once(\n"
    "    \"codex-rs/hepta-supervisor/src/daemon.rs\",\n"
    "    '''    let agent_id = fence.agent_id.clone();\n"
    "    let accepted_state_digest = fence.state_digest.clone();\n"
    "    let mut supervisor = state.supervisor.lock().await;\n"
    "''',\n"
)
call_count = integration.count(call_prefix)
if call_count != 2:
    raise RuntimeError(
        f"mutation generator prelude changed: expected 2, found {call_count}"
    )
integration = integration.replace(
    call_prefix,
    call_prefix.replace("replace_once(", "replace_first(", 1),
    1,
)
integration_path.write_text(integration)
print("runtime.supervisor generated import and mutation patches disambiguated")
