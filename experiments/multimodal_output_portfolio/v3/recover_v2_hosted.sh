#!/usr/bin/env bash
# Recovery adapter only: SOURCE_CHECKOUT REQUEST_JSON OUTPUT_ROOT.
# The frozen v2 launcher is not invoked; GITHUB_REF is never rewritten.
set -Eeuo pipefail
umask 077
[[ $# == 3 ]] || { printf 'Usage: recover_v2_hosted.sh SOURCE_CHECKOUT REQUEST_JSON OUTPUT_ROOT\n' >&2; exit 64; }
task_source_dir="$1"; task_request="$2"; task_output="$3"
mkdir -p -- "$task_output"
task_output="$(CDPATH= cd -- "$task_output" && pwd)"
(set -o noclobber; date -u +%Y-%m-%dT%H:%M:%SZ > "$task_output/recovery-started.txt") || exit 73
task_stage=environment; task_python=""; task_source=""; task_start="$SECONDS"
task_finish() {
  local task_code="$?"
  trap - EXIT
  printf 'stage=%s\nexit_code=%s\nelapsed_seconds=%s\noriginal_launcher_executed=false\n' "$task_stage" "$task_code" "$((SECONDS - task_start))" > "$task_output/recovery-outcome.txt"
  if [[ -n "$task_python" ]]; then
    "$task_python" - "$task_output" "$task_stage" "$task_code" "$task_source" "$((SECONDS - task_start))" <<'PY' || true
import json, os, sys
from pathlib import Path
out, stage, code, source, elapsed = sys.argv[1:]
record = dict(schema="hepta.ndu-v2-hosted-recovery.receipt.v1", stage=stage,
              exit_code=int(code), elapsed_seconds=int(elapsed), source_commit=source,
              completed=stage == "complete" and code == "0", execution_tier="hosted-cpu",
              smoke_only=True, original_launcher_executed=False,
              original_run_replaced=False, dedicated_gate_satisfied=False,
              external_assignment_verified=False,
              external_assignment_attestation="requires independent Actions job record",
              event={key: os.environ.get(key) for key in
                     ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
              runner={key: os.environ.get(key) for key in
                      ("RUNNER_NAME", "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH")})
Path(out, "recovery-receipt.json").write_text(json.dumps(record, indent=2) + "\n")
PY
  fi
  exit "$task_code"
}
trap task_finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
task_python="$(command -v python3.12)"
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_EVENT_NAME:-}" == push ]]
[[ "${GITHUB_REPOSITORY:-}" == TrillionniumFoundation/hepta-private-ci ]]
[[ "${GITHUB_REF:-}" == refs/heads/research/ndu-feedback-generation-v3 ]]
[[ "${RUNNER_ENVIRONMENT:-}" == github-hosted && "${RUNNER_OS:-}" == Linux && "${RUNNER_ARCH:-}" == X64 ]]
[[ -n "${RUNNER_NAME:-}" && "${GITHUB_RUN_ID:-}" =~ ^[0-9]+$ && "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
"$task_python" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
task_stage=source_and_request
task_source_dir="$(CDPATH= cd -- "$task_source_dir" && pwd)"
task_dir="$task_source_dir/experiments/multimodal_output_portfolio/v2"
task_adapter_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_adapter_repo="$(git -C "$task_adapter_dir" rev-parse --show-toplevel)"
task_source="$(git -C "$task_source_dir" rev-parse HEAD)"
[[ "$task_source" == c5c6b9df0a83a9a2f95d5583b95909829a982b06 ]]
[[ "$(git -C "$task_adapter_repo" rev-parse HEAD)" == "$GITHUB_SHA" ]]
[[ -z "$(git -C "$task_source_dir" status --porcelain --untracked-files=all -- experiments/multimodal_output_portfolio .github/workflows/ndu-controlled-generation-v2.yml)" ]]
[[ -z "$(git -C "$task_adapter_repo" status --porcelain --untracked-files=all -- experiments/multimodal_output_portfolio/v3/HOSTED_RECOVERY_REQUEST.json experiments/multimodal_output_portfolio/v3/recover_v2_hosted.sh .github/workflows/ndu-v2-hosted-recovery.yml)" ]]
"$task_python" - "$task_request" "$task_adapter_repo" "$task_dir" "$task_output" <<'PY' 2>&1 | tee "$task_output/request-validation.log"
from datetime import datetime, timezone
import hashlib, json, sys
from pathlib import Path
request_path, adapter_repo, source, output = map(Path, sys.argv[1:])
if request_path.resolve() != (adapter_repo / "experiments/multimodal_output_portfolio/v3/HOSTED_RECOVERY_REQUEST.json").resolve():
    raise ValueError("request must come from the checked-out recovery commit")
request = json.loads(request_path.read_text())
expected = dict(schema="hepta.ndu-v2-hosted-recovery.request.v1",
    implementation_commit="c5c6b9df0a83a9a2f95d5583b95909829a982b06",
    protocol_sha256="2a5a206024c3837223e1db83a4515a4d2ba0a0416d48c482989cc5130bdf97cf",
    execution_request_attempt=2, request_branch="research/ndu-feedback-generation-v3",
    execution_tier="hosted-cpu", runner_label="ubuntu-slim", smoke_only=True,
    recovery_of_run_id=39899251197, recovery_of_hosted_job_id=120236739119,
    original_run_attempt=1, recovery_kind="new_workflow_same_frozen_source",
    entry_point="experiments/multimodal_output_portfolio/v2/run.py",
    adapter="experiments/multimodal_output_portfolio/v3/recover_v2_hosted.sh",
    original_launcher_executed=False, original_run_replaced=False,
    dedicated_gate_satisfied=False)
if any(type(request.get(key)) is not type(value) or request[key] != value
       for key, value in expected.items()):
    raise ValueError("recovery request differs from the fixed source/protocol/hosted contract")
if datetime.fromisoformat(request["created_at"]).utcoffset() != timezone.utc.utcoffset(None):
    raise ValueError("request timestamp must be timezone-aware UTC")
protocol = (source / "protocol.json").read_bytes()
if hashlib.sha256(protocol).hexdigest() != request["protocol_sha256"]:
    raise ValueError("protocol bytes differ from the frozen v2 request")
(output / "validated-request.json").write_text(json.dumps(request, indent=2) + "\n")
(output / "protocol.json").write_bytes(protocol)
print("Validated separate recovery request; fixed v2 source and protocol are unchanged.")
PY
export HEPTA_EXPERIMENT_SOURCE_COMMIT="$task_source"
task_stage=dependencies
task_venv="$(mktemp -d "$RUNNER_TEMP/hepta-v2-recovery-venv.XXXXXX")"
"$task_python" -m venv "$task_venv" > "$task_output/dependencies.log" 2>&1
task_python="$task_venv/bin/python"
PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --no-input --no-cache-dir --disable-pip-version-check --only-binary=:all: --retries 2 --timeout 30 --index-url https://pypi.org/simple --report "$task_output/numpy-install.json" numpy==1.26.4 >> "$task_output/dependencies.log" 2>&1
PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --no-input --no-cache-dir --disable-pip-version-check --only-binary=:all: --retries 2 --timeout 30 --index-url https://download.pytorch.org/whl/cpu --report "$task_output/torch-install.json" torch==2.5.1 >> "$task_output/dependencies.log" 2>&1
"$task_python" - <<'PY' > "$task_output/runtime.json"
import json, os, platform, sys
import numpy as np
import torch
if np.__version__ != "1.26.4" or torch.__version__.split("+")[0] != "2.5.1" or torch.version.cuda is not None:
    raise RuntimeError("pinned CPU dependencies not satisfied")
if torch.from_numpy(np.zeros(1, dtype=np.float32)).numpy().shape != (1,):
    raise RuntimeError("NumPy/Torch CPU interoperability failed")
print(json.dumps(dict(python=sys.version, numpy=np.__version__, torch=torch.__version__,
                     platform=platform.platform(), cpu_count=os.cpu_count(), device="cpu"), indent=2))
PY
"$task_python" -m pip freeze > "$task_output/pip-freeze.txt"
task_stage=tests
"$task_python" -W error -m unittest discover -s "$task_dir/.." -p 'test_*.py' -v 2>&1 | tee "$task_output/tests.log"
PYTHONPATH="$task_dir/.." "$task_python" -W error -m unittest discover -s "$task_dir" -p 'test_*.py' -v 2>&1 | tee "$task_output/v2-tests.log"
task_stage=experiment
"$task_python" "$task_dir/run.py" --output "$task_output/run" --tier hosted-cpu --smoke 2>&1 | tee "$task_output/experiment.log"
task_stage=completion_validation
"$task_python" - "$task_output/run" "$task_source" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
completion = json.loads((out / "completion.json").read_text())
runtime = json.loads((out / "runtime-start.json").read_text())
if (completion.get("execution_completed") is not True or completion.get("smoke_only") is not True
        or completion.get("source_unchanged") is not True or runtime.get("source_frozen") is not True
        or runtime.get("tier") != "hosted-cpu" or runtime.get("source_commit") != sys.argv[2]):
    raise RuntimeError("frozen v2 hosted smoke completion receipt failed validation")
print("Hosted smoke completed; this is not confirmatory efficacy or dedicated execution.")
PY
task_stage=complete
