# Reproduce the conservative HCSN study

Sections 1–3 **restore and analyze existing evidence; they do not train a model**. Run from the repository root in a checkout containing this guide and its accompanying evidence.

The work is reviewed in [draft PR #4362](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4362). Record the exact checkout commit; the PR head can advance.

| Item | Immutable reference |
|---|---|
| Execution/source seal | [78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5) |
| Successful hosted raw evidence | [a0de582931981b3742433475ecf5565409854a5c](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/a0de582931981b3742433475ecf5565409854a5c) |
| Successful Actions run | [41059620366](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41059620366) |
| Frozen model/analysis identities | HOSTED_PROTOCOL.json → source_files_sha256, 124 files |
| Hosted archive | artifacts/hosted002/hosted_attempt.json and 145 adjacent XZ parts |
| Whole archive SHA256 | 0a320b3d74ecb2db9081d6bba22e37a9f858a35e12d5cb39b72b9017a935cd49 |

The hosted archive contains 1,289 files and 47,241,400 compressed bytes. Later PR commits add reports, replay receipts and the separately preserved original-abort ASCII archive; those additions are not retroactively part of a0de5829.

## 1. Environment

Use Linux x86-64 and **CPython 3.12.14** with an isolated environment. Here python means that environment's interpreter.

~~~bash
python -c 'import sys; assert sys.version_info[:3] == (3, 12, 14), sys.version'
python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
python -m pip install --no-cache-dir numpy==2.3.5 scipy==1.17.0

export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export HCSN_PACKAGE=experiments/hcsn_conservative_acceleration_v1
~~~

Evidence analysis does not require a hosted container or GitHub identity. The formal hosted container is recorded in HOSTED_EXECUTION_PLAN.json.

## 2. Restore both evidence archives

Restore the hosted archive directly into results. The protocol references registered data and proof files at these relative paths:

~~~bash
python -m experiments.hcsn_free_boundary_v1.archive restore \
  --manifest "$HCSN_PACKAGE/artifacts/hosted002/hosted_attempt.json" \
  --destination "$HCSN_PACKAGE/results"
~~~

The restorer verifies every part, the whole archive and every member. It accepts identical existing files and rejects different content. Keep parts beside their manifest. This restores checkpoints, predictions, registered inputs, execution logs, native journals and recovery states; analysis replay needs no original CREMA-D media download.

The original comparison001 stopped with **7 successful jobs, 2 failed jobs and 61 unstarted jobs**. Restore its separate ASCII/base64 supplement, reusing 22 byte-identical registered input files:

~~~bash
python "$HCSN_PACKAGE/artifacts/comparison001_aborted_text/restore.py" \
  --destination "$HCSN_PACKAGE/results/comparison001" \
  --shared-data-from "$HCSN_PACKAGE/results/comparison002_hosted"
~~~

The shared-data argument is the **cohort root**, not its data subdirectory. The command verifies/restores 134 non-data files plus 22 shared-data files and preserves the abort. Its gzip archive SHA256 is c34002b119d2073cd8ec1c78149241750b218101ac10fd623c72ce4f8801115e. See that archive's MANIFEST.json, DATA_REUSE_AUDIT.json and RESTORE_VALIDATION.json.

A checkout of a0de5829 alone may lack this later ASCII supplement. Use the later immutable PR commit containing this guide and the supplement; the hosted archive remains independently available at a0de5829.

## 3. Replay the frozen analyzer

Use a new output directory; increment its suffix for a second replay.

~~~bash
python -m experiments.hcsn_conservative_acceleration_v1.analyze \
  --protocol "$HCSN_PACKAGE/HOSTED_PROTOCOL.json" \
  --study "$HCSN_PACKAGE/results/comparison002_hosted" \
  --output "$HCSN_PACKAGE/results/reproduction_analysis001"
~~~

The analyzer checks saved tensors, checkpoint/selection hashes, validation-only selection, test-access order, metrics, initial parameters, minibatch streams and gradients. It runs no optimizer. Expect complete=true, valid_jobs=70 and errors=[].

Compare all result fields except the replay's own CPU/wall:

~~~bash
python - <<'PY'
import json
from pathlib import Path

base = Path("experiments/hcsn_conservative_acceleration_v1/results")
original = json.loads((base / "comparison002_hosted_analysis/ANALYSIS.json").read_text())
replay = json.loads((base / "reproduction_analysis001/ANALYSIS.json").read_text())
assert replay["complete"] and replay["valid_jobs"] == 70 and replay["errors"] == []
for value in (original, replay):
    for key in ("analysis_cpu_seconds", "analysis_wall_seconds"):
        value["separate_costs"].pop(key)
assert replay == original
print("Saved-evidence analysis matches, excluding replay CPU/wall.")
PY
~~~

An existing successful local replay is documented in results/local_evidence_replay001/RUNNER_REPLAY_RESULT.json. It is a replay of the frozen analyzer, not another training replicate or a separately implemented analyzer.

The old incomplete cohort requires its original protocol and explicit partial mode:

~~~bash
python -m experiments.hcsn_conservative_acceleration_v1.analyze \
  --protocol "$HCSN_PACKAGE/PROTOCOL.json" \
  --study "$HCSN_PACKAGE/results/comparison001" \
  --output "$HCSN_PACKAGE/results/reproduction_aborted_analysis001" \
  --allow-partial
~~~

## 4. Optional: repeat trained runtime checks, without training

Use fresh output directories. The existing selected weights have SHA256 8679b9aecfe237055c449c92e46510b9832f8ccae03833a38657073c17ce665c.

~~~bash
export HCSN_NATIVE_TMP="$(mktemp -d)"
python -m experiments.hcsn_free_boundary_v1.restore_native \
  "$HCSN_NATIVE_TMP/continuous_host"

for HCSN_MODE in stream native native-causal; do
  python -m experiments.hcsn_conservative_acceleration_v1.runtime "$HCSN_MODE" \
    --output "$HCSN_PACKAGE/results/reproduction_$HCSN_MODE-001" \
    --backend accelerated \
    --profile stable \
    --config "$HCSN_PACKAGE/results/hosted_finalize001/MODEL_CONFIG.json" \
    --checkpoint "$HCSN_PACKAGE/results/comparison002_hosted/runs/fixed__selective_copy__hcsn_accelerated__98031/selected.npz" \
    --binary "$HCSN_NATIVE_TMP/continuous_host"
done
~~~

Restoration verifies the Linux x86-64 owner's binary SHA256 1dc702aea6a448ad84407aeb71dc8f23066205fab79fe7c6859fc02c55e6f7a5. The neural operator remains Python/PyTorch. To measure total runtime cost, wrap each complete command in an outer wait4 receipt as hosted/runner.py does; standalone RESULT files contain nested native/resume clocks, not total worker cost.

## 5. Optional full training: the exact hosted entrypoints

**This section starts new computation and is unnecessary for evidence replay.** The original entrypoints were:

~~~bash
python -m experiments.hcsn_conservative_acceleration_v1.hosted.runner prepare
python -m experiments.hcsn_conservative_acceleration_v1.hosted.runner train
python -m experiments.hcsn_conservative_acceleration_v1.hosted.runner finalize
~~~

These require a genuine fresh GitHub-hosted execution, matching checkout/GITHUB_SHA, published plan and source hashes, exact versions and resource limits. Do not invent GitHub environment variables to bypass these checks.

The authoritative [workflow at the execution seal](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/78b98ed8dd66294a3de6abce2fa0bbbd2c24f8d5/.github/workflows/hcsn-conservative-hosted.yml) specifies:

- Standard ubuntu-24.04, with image python:3.12.14@sha256:6dc02694c53fde08b0e39de9273a708d2f2a612f77dc173a64835c3f7a40ee35.
- Docker options --memory=8g --memory-swap=8g --cpus=2 --cgroupns=private.
- One numerical thread per worker and the unchanged two-worker memory guard.
- Data restore, numerical validation, model/runtime tests and train-only preflight before registration.
- Registration artifact preservation before all 70 jobs; independent analysis and trained runtime checks after complete 70/70 acceptance.

A checkout already containing HOSTED_PROTOCOL.json/results is not a fresh training workspace. Do not delete evidence or dispatch the evidence-bearing branch to force the old launcher through. An additional full run needs a fresh public registration/output namespace and corresponding immutable publication identity. Preserve original sources, budgets and outcomes, and identify the new run's timing and previously observed data. The publisher also refuses a branch that moved beyond its execution seal.

## Interpretation

Read CONTRACT.md and reports/HOSTED_RUNTIME_AUDIT.md. The dual channels are local regenerative policy/intervention values, not literal financial call/put prices or a classification-optimal QVI. Causal runtime tests use an unlabeled panel and engineering midpoint threshold; they establish the value-message-to-action path, not optimal task stopping. Refractory state is propagated and recovered, without an isolated reset-specific task benefit in this panel.

Complete worker CPU already includes nested native/resume costs. Persistent state bytes exclude weights, training activations and optimizer state. This study does not measure energy, GPU throughput, a native neural kernel or multimodal foundation-model advantage.

