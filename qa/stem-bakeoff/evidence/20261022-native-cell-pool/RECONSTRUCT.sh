# Use a fresh checkout with the exact recorded Git tree. The original local
# commit may require the later separately published same-tree commit mapping.
cd /path/to/exact-p41-checkout
test "$(git rev-parse HEAD^{tree})" = 231ed14ea73a71c6d2ac3fe353b1779419154f53
P41_PYTHON=/path/to/p40-compatible-python
P41_INPUT_REBUILD=/tmp/p41-rebuilt-inputs
"$P41_PYTHON" - "$PWD" "$P41_INPUT_REBUILD" <<'PY'
import hashlib, pathlib, shutil, sys
repo, output = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(repo / "qa/stem-bakeoff"))
from multimodal_evidence import restore_evidence
from native_task_head_pool import prepare_inputs
output.mkdir(mode=0o700)
p40 = output / "p40"; p40.mkdir()
shutil.copytree(repo / "qa/stem-bakeoff/evidence/20261022-native-task-head/native-results",
                p40 / "native-results")
restore_evidence(repo / "qa/stem-bakeoff/evidence/20261022-real-multimodal",
    expected_manifest_sha256="2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e",
    output=p40 / "restored")
prepared = output / "prepared"; prepared.mkdir()
prepare_inputs(p40, "22e4560ca4ff2b1c604267c92aed71bbf1417e612018c6760930633ca52395e6", prepared)
raw = (prepared / "requests.jsonl").read_bytes()
assert len(raw) == 16988720
assert hashlib.sha256(raw).hexdigest() == "3bb13eaae37d0d72b245ce65aa28c81b057a542fe555d367a0f7758b392cd214"
print("exact original input stream reconstructed; no prediction or training executed")
PY
# Release build from the same source; this does not execute the resource trial.
# Compiler, linker, paths and environment may change the executable bytes.
cd codex-rs
CARGO_TARGET_DIR=/tmp/p41-rebuilt-target CARGO_INCREMENTAL=0 CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 CARGO_PROFILE_RELEASE_DEBUG=0 CARGO_BUILD_JOBS=2 cargo build --locked --release -p codex-hepta-neuron --example native_task_head_pool --offline
sha256sum /tmp/p41-rebuilt-target/release/examples/native_task_head_pool
# Original: 2673320 bytes, SHA256 42c69fcec3a2b5332893e6a417710df38fbc6cab3ca51ab1afe195db2fe4fc31.
# A different rebuilt digest identifies a NEW executable, not the retained original.
