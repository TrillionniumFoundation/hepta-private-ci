#!/usr/bin/env bash
set -euo pipefail

branch="codex/neuron-runtime-five-phase-closure-v2"
workflow=".github/workflows/neuron-runtime-gate-fix-once.yml"
script="scripts/neuron_runtime_apply_gate_repair.sh"

if [[ -n "${GITHUB_SHA:-}" ]]; then
  test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"
fi
test -z "$(git status --porcelain --untracked-files=all)"

python3 - <<'PY'
from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    file = Path(path)
    value = file.read_text()
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    file.write_text(value.replace(old, new))


replace(
    "codex-rs/hepta-infer-core/Cargo.toml",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\n",
    "[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\nfs2 = \"0.4.3\"\nserde = { workspace = true, features = [\"derive\"] }\nserde_json = { workspace = true }\n",
)
replace(
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "use std::path::Path;\nuse std::path::PathBuf;\n",
    "use std::path::Path;\nuse std::path::PathBuf;\n\nuse fs2::FileExt;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "        file.try_lock().map_err(|_| Error::WriterUnavailable)?;\n",
    "        file.try_lock_exclusive()\n            .map_err(|_| Error::WriterUnavailable)?;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "use std::fs::OpenOptions;\nuse std::fs::TryLockError;\n",
    "use std::fs::OpenOptions;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "use std::str::FromStr;\n\nuse codex_hepta_types::AuthorityPosture;\n",
    "use std::str::FromStr;\n\nuse fs2::FileExt;\n\nuse codex_hepta_types::AuthorityPosture;\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "        match file.try_lock() {\n            Ok(()) => Ok(Self(file)),\n            Err(TryLockError::WouldBlock) => Err(NeuronFeatureStoreError::Busy),\n            Err(TryLockError::Error(error)) => Err(error.into()),\n        }\n",
    "        match file.try_lock_exclusive() {\n            Ok(()) => Ok(Self(file)),\n            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {\n                Err(NeuronFeatureStoreError::Busy)\n            }\n            Err(error) => Err(error.into()),\n        }\n",
)
replace(
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "        let _ = self.0.unlock();\n",
    "        let _ = FileExt::unlock(&self.0);\n",
)
replace(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    '''        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
''',
    '''        ServerNotification::AgentMessageDelta(delta)
            if delta.thread_id == output.thread_id && delta.turn_id == output.turn_id =>
        {
            if delta.delta.len() > MAX_OUTPUT_BYTES.saturating_sub(output.output.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            output.output.push_str(&delta.delta);
        }
        ServerNotification::ItemCompleted(completed)
            if completed.thread_id == output.thread_id
                && completed.turn_id == output.turn_id =>
        {
            if let ThreadItem::AgentMessage { text, .. } = &completed.item
                && output.output.is_empty()
            {
                if text.len() > MAX_OUTPUT_BYTES {
                    return Err("output byte limit exceeded".to_string());
                }
                output.output.push_str(text);
            }
        }
        ServerNotification::ThreadTokenUsageUpdated(usage)
''',
)

tests = Path("codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs").read_text()
for needle in (
    'assert!(messages.iter().any(|message| message.contains("result")));',
    'assert!(messages.iter().all(|message| !message.contains("delta")));',
):
    if needle not in tests:
        raise SystemExit(f"missing durable final-use assertion: {needle}")
PY

rustup toolchain install stable --profile minimal --component rustfmt
rustup toolchain install 1.88.0 --profile minimal
(
  cd codex-rs
  cargo +stable check -p codex-hepta-infer-core
  cargo +stable fmt --all
)

git diff --check
rm -f "$workflow" "$script"

python3 - <<'PY'
import subprocess

allowed = {
    ".github/workflows/neuron-runtime-gate-fix-once.yml",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-agentd/tests/fixtures/neuron_runtime_process_fault_harness.rs",
    "codex-rs/hepta-infer-core/Cargo.toml",
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "codex-rs/hepta-neuron/src/lib.rs",
    "scripts/neuron_runtime_apply_gate_repair.sh",
}
lines = subprocess.check_output(
    ["git", "status", "--porcelain=v1", "--untracked-files=all"], text=True
).splitlines()
paths = {line[3:] for line in lines if len(line) >= 4}
unexpected = sorted(paths - allowed)
if unexpected:
    raise SystemExit(f"unexpected repair changes: {unexpected}")
required = {
    ".github/workflows/neuron-runtime-gate-fix-once.yml",
    "codex-rs/hepta-infer-core/Cargo.toml",
    "codex-rs/hepta-infer-core/src/durable_control.rs",
    "codex-rs/hepta-infer-core/src/neuron_feature_store.rs",
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs",
    "scripts/neuron_runtime_apply_gate_repair.sh",
}
missing = sorted(required - paths)
if missing:
    raise SystemExit(f"expected repair changes absent: {missing}")
print("bounded repair paths:")
for path in sorted(paths):
    print(path)
PY

python3 -m unittest discover -v -s scripts/neuron -p 'test_*.py'
(
  cd codex-rs
  cargo +stable fmt --all -- --check
  cargo +stable check -p codex-hepta-infer-core -p codex-hepta-infer-worker-host
  cargo +1.88.0 check -p codex-hepta-infer-core -p codex-hepta-infer-worker-host
  cargo +stable test -p codex-hepta-infer-worker-host native_app_server -- --nocapture
)

test -z "$(git diff --check)"

git config user.name hepta-qualification
git config user.email qualification@invalid
git add -A
git commit -m "fix(neuron): restore MSRV locking and final output observation"
git push origin "HEAD:${branch}"
