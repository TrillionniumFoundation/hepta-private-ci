#!/usr/bin/env bash
# Execute only on the repository's existing dedicated desktop runner.
# Usage: bash run_cloud.sh OUTPUT_ROOT
set -Eeuo pipefail
umask 077

task_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_output="${1:-${HEPTA_EXPERIMENT_OUTPUT:-}}"
if [[ $# -gt 1 || -z "$task_output" ]]; then
  printf 'Usage: bash run_cloud.sh OUTPUT_ROOT\n' >&2
  exit 64
fi
mkdir -p -- "$task_output"
task_output="$(CDPATH= cd -- "$task_output" && pwd)"
task_stage=initialization
task_reason=""
task_verified=false
task_source_sha=""
task_source_matches=false
task_expected_sha="${HEPTA_EXPERIMENT_EXPECTED_SHA:-${GITHUB_SHA:-}}"
task_python=""
task_dependency_environment=not_checked
task_experiment_exit_code=null
task_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

task_json_string() {
  local task_value="$1"
  task_value="${task_value//\\/\\\\}"
  task_value="${task_value//\"/\\\"}"
  task_value="${task_value//$'\n'/\\n}"
  task_value="${task_value//$'\r'/\\r}"
  task_value="${task_value//$'\t'/\\t}"
  printf '"%s"' "$task_value"
}

task_finish() {
  local task_exit_code="$1"
  trap - EXIT
  if [[ "$task_exit_code" != 0 && -z "$task_reason" ]]; then
    task_reason="Unexpected failure during ${task_stage}; inspect retained logs."
  fi
  {
    printf '{\n  "schema": "hepta-output-portfolio-launcher-v1",\n'
    printf '  "requested_execution_tier": "dedicated-cloud",\n'
    printf '  "dedicated_runner_verified": %s,\n' "$task_verified"
    printf '  "runner_group_selector": "trillionnium-android-gpu",\n'
    printf '  "runner_label_selector": ["self-hosted", "linux", "x64"],\n'
    printf '  "runner_name": '; task_json_string "${RUNNER_NAME:-}"; printf ',\n'
    printf '  "runner_environment": '; task_json_string "${RUNNER_ENVIRONMENT:-}"; printf ',\n'
    printf '  "runner_os": '; task_json_string "${RUNNER_OS:-}"; printf ',\n'
    printf '  "runner_arch": '; task_json_string "${RUNNER_ARCH:-}"; printf ',\n'
    printf '  "github_run_id": '; task_json_string "${GITHUB_RUN_ID:-}"; printf ',\n'
    printf '  "github_run_attempt": '; task_json_string "${GITHUB_RUN_ATTEMPT:-}"; printf ',\n'
    printf '  "source_sha": '; task_json_string "$task_source_sha"; printf ',\n'
    printf '  "expected_source_sha": '; task_json_string "$task_expected_sha"; printf ',\n'
    printf '  "source_sha_matches": %s,\n' "$task_source_matches"
    printf '  "python_executable": '; task_json_string "$task_python"; printf ',\n'
    printf '  "dependency_environment": '; task_json_string "$task_dependency_environment"; printf ',\n'
    printf '  "protocol_device": "cpu",\n'
    printf '  "started_at": '; task_json_string "$task_started"; printf ',\n'
    printf '  "finished_at": '; task_json_string "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; printf ',\n'
    printf '  "stage": '; task_json_string "$task_stage"; printf ',\n'
    printf '  "failure_reason": '; task_json_string "$task_reason"; printf ',\n'
    printf '  "exit_code": %s,\n' "$task_exit_code"
    printf '  "experiment_exit_code": %s\n}\n' "$task_experiment_exit_code"
  } > "$task_output/launcher-receipt.json"
  printf 'Launcher stage=%s exit_code=%s dedicated_runner_verified=%s\n' \
    "$task_stage" "$task_exit_code" "$task_verified"
  if [[ -n "$task_reason" ]]; then printf '%s\n' "$task_reason" >&2; fi
  exit "$task_exit_code"
}
trap 'task_finish "$?"' EXIT
trap 'task_reason="Launcher interrupted by SIGINT"; exit 130' INT
trap 'task_reason="Launcher interrupted by SIGTERM"; exit 143' TERM

task_fail() {
  task_reason="$1"
  exit "${2:-78}"
}

task_stage=runner_identity
[[ "${GITHUB_ACTIONS:-}" == true ]] || task_fail "A GitHub Actions runner assignment is required."
[[ "${GITHUB_REPOSITORY:-}" == TrillionniumFoundation/hepta-private-ci ]] \
  || task_fail "Unexpected repository; dedicated project identity is unverified."
[[ "${GITHUB_REF:-}" == refs/heads/research/ndu-output-portfolio-20261021 ]] \
  || task_fail "Only the registered research branch may execute this pilot."
[[ "${GITHUB_EVENT_NAME:-}" == push || "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]] \
  || task_fail "Unexpected workflow event."
[[ "${RUNNER_NAME:-}" == desktop && "${RUNNER_ENVIRONMENT:-}" == self-hosted \
    && "${RUNNER_OS:-}" == Linux && "${RUNNER_ARCH:-}" == X64 ]] \
  || task_fail "Required runner identity is desktop / self-hosted / Linux / X64."
[[ "${HEPTA_DEDICATED_RUNNER_GROUP:-}" == trillionnium-android-gpu ]] \
  || task_fail "The expected dedicated runner group selector was not provided."
[[ -n "${RUNNER_TEMP:-}" && -d "$RUNNER_TEMP" && -w "$RUNNER_TEMP" ]] \
  || task_fail "RUNNER_TEMP is absent or not a writable directory."

task_stage=source_verification
task_source_sha="$(git -C "$task_dir" rev-parse HEAD)"
[[ "$task_expected_sha" =~ ^[0-9a-f]{40}$ && "$task_source_sha" == "$task_expected_sha" ]] \
  || task_fail "Checked-out source SHA differs from the workflow's expected SHA."
git -C "$task_dir" diff --quiet -- . || task_fail "Experiment source has unstaged modifications."
git -C "$task_dir" diff --cached --quiet -- . || task_fail "Experiment source has staged modifications."
task_source_matches=true
task_verified=true
export HEPTA_EXECUTION_TIER=dedicated-cloud
export HEPTA_DEDICATED_RUNNER_VERIFIED=1
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1

task_stage=python_discovery
task_python="${HEPTA_EXPERIMENT_PYTHON:-python3}"
task_python="$(command -v -- "$task_python")" \
  || task_fail "HEPTA_EXPERIMENT_PYTHON or python3 could not be located."
"$task_python" --version > "$task_output/python-version.txt" 2>&1 \
  || task_fail "The selected Python interpreter could not start."
cat "$task_output/python-version.txt"

task_collect_runtime() {
  "$task_python" - "$task_dir/protocol.json" > "$1" <<'PY'
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

receipt = {
    "python": sys.version,
    "python_executable": sys.executable,
    "platform": platform.platform(),
    "machine": platform.machine(),
    "logical_cpu_count": os.cpu_count(),
    "protocol_device": "cpu",
    "libraries": {},
}
cpuinfo = Path("/proc/cpuinfo")
if cpuinfo.is_file():
    for line in cpuinfo.read_text().splitlines():
        if line.startswith("model name"):
            receipt["cpu_model"] = line.split(":", 1)[1].strip()
            break
try:
    receipt["physical_memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
except (ValueError, OSError):
    receipt["physical_memory_bytes"] = None
for name in ("numpy", "torch"):
    try:
        module = importlib.import_module(name)
        receipt["libraries"][name] = {"version": module.__version__, "import_ok": True}
        if name == "torch":
            receipt["cuda"] = {
                "torch_build": module.version.cuda,
                "available": module.cuda.is_available(),
                "device_count": module.cuda.device_count(),
                "device_names": [module.cuda.get_device_name(i) for i in range(module.cuda.device_count())],
            }
    except Exception as error:
        receipt["libraries"][name] = {"import_ok": False, "error": str(error)}
if shutil.which("nvidia-smi"):
    try:
        probe = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        receipt["nvidia_smi"] = {
            "exit_code": probe.returncode, "stdout": probe.stdout, "stderr": probe.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        receipt["nvidia_smi"] = {"error": str(error)}
else:
    receipt["nvidia_smi"] = {"available": False}
protocol = Path(sys.argv[1])
if protocol.is_file():
    receipt["protocol_sha256"] = hashlib.sha256(protocol.read_bytes()).hexdigest()
print(json.dumps(receipt, indent=2))
PY
}

task_collect_runtime "$task_output/hardware-runtime-initial.json" \
  || task_fail "Could not collect the initial hardware/runtime receipt."
"$task_python" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' \
  || task_fail "Pinned dependencies require Python 3.10-3.12; select HEPTA_EXPERIMENT_PYTHON explicitly."

task_dependencies_ready() {
  "$task_python" - <<'PY'
import numpy as np
import torch

assert np.__version__ == "1.26.4", "NumPy must be 1.26.4"
assert torch.__version__.split("+")[0] == "2.5.1", "PyTorch must be 2.5.1"
assert torch.from_numpy(np.zeros(1, dtype=np.float32)).numpy().shape == (1,)
print("Pinned NumPy/PyTorch versions and CPU interoperability verified.")
PY
}

task_stage=dependencies
: > "$task_output/pip-install.log"
if task_dependencies_ready >> "$task_output/pip-install.log" 2>&1; then
  task_dependency_environment=existing_pinned_interpreter
else
  task_venv="$(mktemp -d "${RUNNER_TEMP%/}/hepta-output-portfolio-venv.XXXXXX")"
  "$task_python" -m venv "$task_venv" >> "$task_output/pip-install.log" 2>&1 \
    || task_fail "Isolated venv creation failed; see pip-install.log."
  task_python="$task_venv/bin/python"
  task_dependency_environment=isolated_runner_temp_venv
  PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --disable-pip-version-check --no-input \
    --no-cache-dir --index-url https://pypi.org/simple numpy==1.26.4 \
    >> "$task_output/pip-install.log" 2>&1 \
    || task_fail "Pinned NumPy installation failed; see pip-install.log."
  PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --disable-pip-version-check --no-input \
    --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
    >> "$task_output/pip-install.log" 2>&1 \
    || task_fail "Pinned CPU PyTorch installation failed; see pip-install.log."
  task_dependencies_ready >> "$task_output/pip-install.log" 2>&1 \
    || task_fail "Installed dependencies failed version/interoperability checks; see pip-install.log."
fi
task_collect_runtime "$task_output/hardware-runtime.json" \
  || task_fail "Could not collect the final hardware/runtime receipt."
cat "$task_output/hardware-runtime.json"

task_stage=protocol_validation
[[ -f "$task_dir/run_experiment.py" && -f "$task_dir/protocol.json" ]] \
  || task_fail "The registered experiment entry point or protocol.json is missing."
"$task_python" - "$task_dir/protocol.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    protocol = json.load(source)
seeds = protocol.get("seeds", [])
assert len(seeds) == 3 and len(set(seeds)) == 3 and all(type(seed) is int for seed in seeds), "Three distinct registered seeds are required"
print("Registered protocol:", protocol["protocol_id"], "seeds:", seeds)
PY
cp -- "$task_dir/protocol.json" "$task_output/protocol.json"
[[ ! -e "$task_output/run" ]] || task_fail "Output run directory already exists; existing evidence will not be overwritten."

task_stage=experiment
set +e
"$task_python" "$task_dir/run_experiment.py" \
  --output "$task_output/run" --execution-tier dedicated-cloud \
  2>&1 | tee "$task_output/experiment.log"
task_pipeline_status=("${PIPESTATUS[@]}")
set -e
task_experiment_exit_code="${task_pipeline_status[0]}"
[[ "$task_experiment_exit_code" == 0 ]] \
  || task_fail "The experiment failed; partial results, checkpoints, and logs are retained." "$task_experiment_exit_code"
[[ "${task_pipeline_status[1]}" == 0 ]] || task_fail "Experiment output could not be fully written to experiment.log." 74
task_stage=complete
