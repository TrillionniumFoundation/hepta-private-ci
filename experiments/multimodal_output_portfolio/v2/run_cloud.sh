#!/usr/bin/env bash
# OUTPUT_ROOT TIER REQUEST_JSON [--smoke]; request and source have distinct SHAs.
set -Eeuo pipefail
umask 077
[[ $# -ge 3 && $# -le 4 ]] || { printf 'Usage: run_cloud.sh OUTPUT_ROOT TIER REQUEST_JSON [--smoke]\n' >&2; exit 64; }
task_output="$1"; task_tier="$2"; task_request="$3"; task_smoke="${4:-}"
task_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p -- "$task_output"
task_output="$(CDPATH= cd -- "$task_output" && pwd)"
(set -o noclobber; date -u +%Y-%m-%dT%H:%M:%SZ > "$task_output/launcher-started.txt") || exit 73
task_stage=arguments; task_source=""; task_python=""; task_environment=false
task_finish() {
  local task_code="$?"
  trap - EXIT
  printf 'stage=%s\nexit_code=%s\nrequested_tier=%s\nsource_sha=%s\n' "$task_stage" "$task_code" "$task_tier" "$task_source" > "$task_output/launcher-outcome.txt"
  if [[ -n "$task_python" ]]; then
    "$task_python" - "$task_output" "$task_stage" "$task_code" "$task_tier" "$task_source" "$task_environment" <<'PY' || true
import json, os, sys
from pathlib import Path
out, stage, status, tier, source, asserted = sys.argv[1:]
record = dict(schema="hepta.ndu-controlled-generation.launcher.v2", stage=stage,
              exit_code=int(status), requested_tier=tier, source_sha=source,
              environment_assertions_passed=asserted == "true", dedicated_runner_verified=False,
              external_assignment_attestation="required" if tier == "dedicated-cloud" else "not_applicable",
              runner={k: os.environ.get(k) for k in ("RUNNER_NAME", "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH")},
              request_commit=os.environ.get("GITHUB_SHA"), run_id=os.environ.get("GITHUB_RUN_ID"),
              run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"))
(Path(out) / "launcher-receipt.json").write_text(json.dumps(record, indent=2) + "\n")
PY
  fi
  exit "$task_code"
}
trap task_finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
[[ "$task_smoke" == "" || "$task_smoke" == --smoke ]]
[[ "$task_tier" == local-cpu || "$task_tier" == hosted-cpu || "$task_tier" == dedicated-cloud ]]
task_stage=python
task_python="$(command -v "${HEPTA_V2_PYTHON:-python3.12}")"
"$task_python" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)'
task_stage=environment
if [[ "$task_tier" != local-cpu ]]; then
  [[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_EVENT_NAME:-}" == push ]]
  [[ "${GITHUB_REPOSITORY:-}" == TrillionniumFoundation/hepta-private-ci ]]
  [[ "${GITHUB_REF:-}" == refs/heads/research/ndu-controlled-generation-v2 ]]
  [[ "${RUNNER_OS:-}" == Linux && "${RUNNER_ARCH:-}" == X64 ]]
  if [[ "$task_tier" == dedicated-cloud ]]; then
    [[ "${RUNNER_NAME:-}" == desktop && "${RUNNER_ENVIRONMENT:-}" == self-hosted && -z "$task_smoke" ]]
    # run.py's local assertion gate; external Actions assignment is still required.
    export HEPTA_DEDICATED_RUNNER_VERIFIED=1
  else
    [[ "${RUNNER_ENVIRONMENT:-}" == github-hosted && "$task_smoke" == --smoke ]]
  fi
fi
task_environment=true
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
task_stage=source
task_source="$(git -C "$task_dir" rev-parse HEAD)"
task_repo="$(git -C "$task_dir" rev-parse --show-toplevel)"
[[ -z "$(git -C "$task_repo" status --porcelain --untracked-files=all -- experiments/multimodal_output_portfolio .github/workflows/ndu-controlled-generation-v2.yml)" ]]
"$task_python" - "$task_request" "$task_source" "$task_dir/protocol.json" "$task_output" <<'PY'
import hashlib, json, re, sys
from pathlib import Path
request_path, source, protocol_path, output = sys.argv[1:]
request = json.loads(Path(request_path).read_text())
required = {"schema", "implementation_commit", "protocol_sha256", "requested_runner", "runner_group", "execution_tiers", "execution_request_attempt"}
if not required <= request.keys() or request["schema"] != "hepta.ndu-controlled-generation.request.v2":
    raise ValueError("missing or invalid request fields")
if not re.fullmatch("[0-9a-f]{40}", request["implementation_commit"]) or request["implementation_commit"] != source:
    raise ValueError("requested and checked-out source SHAs differ")
if not re.fullmatch("[0-9a-f]{64}", request["protocol_sha256"]) or request["protocol_sha256"] != hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest():
    raise ValueError("protocol bytes differ from explicit request")
if (request["requested_runner"] != "desktop" or request["runner_group"] != "trillionnium-android-gpu"
        or request["execution_tiers"] != ["hosted-cpu", "dedicated-cloud"]
        or type(request["execution_request_attempt"]) is not int or request["execution_request_attempt"] < 1):
    raise ValueError("invalid runner selectors, tiers or attempt")
Path(output, "validated-request.json").write_text(json.dumps(request, indent=2) + "\n")
Path(output, "protocol.json").write_bytes(Path(protocol_path).read_bytes())
PY
export HEPTA_EXPERIMENT_SOURCE_COMMIT="$task_source"
task_stage=dependencies
task_venv="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/hepta-controlled-v2-venv.XXXXXX")"
"$task_python" -m venv "$task_venv" > "$task_output/dependencies.log" 2>&1
task_python="$task_venv/bin/python"
PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --no-input --no-cache-dir --disable-pip-version-check --index-url https://pypi.org/simple numpy==1.26.4 >> "$task_output/dependencies.log" 2>&1
PIP_CONFIG_FILE=/dev/null "$task_python" -m pip --isolated install --no-input --no-cache-dir --disable-pip-version-check --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 >> "$task_output/dependencies.log" 2>&1
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
task_arguments=(--output "$task_output/run" --tier "$task_tier")
[[ -z "$task_smoke" ]] || task_arguments+=(--smoke)
"$task_python" "$task_dir/run.py" "${task_arguments[@]}" 2>&1 | tee "$task_output/experiment.log"
task_stage=complete
