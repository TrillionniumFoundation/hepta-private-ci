# Hepta Neuron E0–E4: execution evidence gate (qualification only)

This directory contains a **no-authority** POSIX host measurement collector and an execution-matrix validator. It does not train DecisionCells, dispatch models, approve topology changes, evaluate task outcomes, or establish production readiness. It is an **experimental execution overlay** aligned with the existing [adaptive experiment registry](../../docs/learning/EXPERIMENTS.json), [neural biomimicry specification](../../docs/learning/NEURAL_BIOMIMICRY_SPEC.md), and [causal/longitudinal evaluation specification](../../docs/learning/CAUSAL_LONGITUDINAL_SPEC.md). Its E0–E4 stage arm names are local trial labels, **not** newly accepted canonical experiment IDs or proof that the registry was programmatically consumed.

## Stage mapping

| Stage | Frozen comparison arms | Real evidence still required |
| --- | --- | --- |
| E0 | `no_change` | Real selected encoder/tokenizer/head, Q24 neuron consumer, actual task outcomes, complete CPU/RSS/GPU and request latency |
| E1 | `multi_head`, `fixed_moe`, `dynamic_moe`, `cell_graph` | Matched unique/trainable parameters, data, budgets, active compute and route/loop observations |
| E2 | `no_change`, `continue_training`, `wider_head`, `split`, `merge`, `distill` | Real artifact CAS/migration/cutover/fences; signed independent future-time utility and negative transfer |
| E3 | `fixed_circuit`, `adaptive_circuit`, `cell_ablation` | Held-out task families, compositional success, real cost and failures |
| E4 | `64`, `256`, `1024`, `4096` | Concurrency sweeps, true process-tree RSS, GPU, power, request-level p95/p99, microbatch throughput and crash recovery |

**Precedence:** E1 requires E0 accepted by an independent owner; E2 requires E1 and real lifecycle receipts; E3 requires E2; E4 only after the previous stages satisfy their scientific and resource gates. This tool does not attest those dependencies. A complete arm matrix is merely an *execution inventory*, not efficacy evidence.

## On a named target host

1. Create a *private, untracked* `manifest.json`. For **E0**, it requires the following shape (paths here are illustrative and **must point to actual, nonempty on-host files**):

   ```json
   {
     "shared": {
       "encoder": "/secure/actual-encoder-weights",
       "tokenizer": "/secure/actual-tokenizer",
       "dataset": "/secure/frozen-requests-and-split",
       "objective": "/secure/frozen-objective",
       "runtime": "/secure/runtime-build-or-configuration"
     },
     "arms": {"no_change": "/secure/selected-head-or-adapter-weights"},
     "commands": {
       "no_change": ["/path/to/qualified-neuron-runner", "--manifest=/secure/actual-model-manifest", "--benchmark-workload", "/secure/frozen-requests-and-split"]
     },
     "e0_model": {
       "model_manifest": "/secure/actual-model-manifest",
       "preprocessor": "/secure/actual-preprocessor",
       "quantization": "/secure/actual-quantization-profile",
       "normalizer": "/secure/actual-normalization-profile",
       "calibration": "/secure/actual-calibration",
       "device_manifest": "/secure/actual-device-observation",
       "license_sbom": "/secure/actual-license-and-sbom"
     }
   }
   ```

   For E1–E4, use exactly `shared`, `arms` and `commands`. All registered arms must have an on-disk candidate and an exact, non-shell command list. The tooling pins executable bytes, argv, and file arguments that already exist at freeze time. The same command is required for every trial within an arm. Runtime-loaded files or network models not represented by frozen paths require additional external owner evidence. **A file labeled "model" is not proof it contains a real model.** Never include credentials in command arguments or store private inputs in Git.

2. Freeze the exact source commit/tree, host, selected performance environment (CPU thread settings and GPU visibility), artifacts, commands and trial counts *before* observing holdout outcomes:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py freeze \
     --stage E0 --repetitions 1 \
     --manifest /secure/manifest.json --out /secure/e0-plan.json
   ```

   Submit that plan digest to a separate independent evaluator/immutable registry. A local digest is **not** an authenticated plan registration. Pilot plans from experimental schema v1 are not reinterpreted as v2; refreeze a new plan.

3. Run the previously frozen command for each trial with no post-hoc substitution:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py run \
     --plan /secure/e0-plan.json --arm no_change --trial 0 --timeout 120 \
     --sample-group-rss --out /secure/e0-run-0.json -- \
     /path/to/qualified-neuron-runner \
     --manifest=/secure/actual-model-manifest \
     --benchmark-workload /secure/frozen-requests-and-split
   ```

   `HEPTA_NEURON_EXPERIMENT_TRIAL` is set to the frozen trial index in the child environment. For a matched arm comparison, use the same preregistered trial population, task families and budgets. Never cherry-pick fast or successful trials; retain all failed attempts in an external immutable evidence owner as well.

4. Audit **only the execution inventory**:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py audit \
     --plan /secure/e0-plan.json --receipts /secure/e0-run-0.json
   ```

   The audit rejects missing/duplicate `(arm, trial)` slots, changed commands and binaries, mismatched source/host/environment, tampered logs and failed runs. For whole-child-process wall time, it reports p50 only with at least 3 samples, p95 with at least 20 and p99 with at least 100. Those are **process-level observations including startup**, not model-internal request latency or independent experimental episodes. E4 additionally requires real concurrency and GPU/power/throughput instrumentation outside this tool.

5. The existing independent `learning.eval`, `learning.ledger`, `learning.artifacts`, Neuron, inference and model owners must supply real authenticated model load/invocation, genuine Neuron Tick/Checkpoint/CAS and external task outcomes, matched unique/trainable parameters and compute, future-time holdouts, NDU value, retention and rollback. **Nothing in this collector can issue those receipts or approve a Cell Split.**

## Limitations and refusal semantics

- `run` executes a **caller-explicit trusted native command** (not a sandbox) and records observed process wall time, direct-child CPU/RSS via POSIX `wait4`, an executable digest checked before and after, and raw stdout/stderr SHA-256. Timeout/output-budget overruns kill the child's process group. Model/provider access, token accounting and worker identity must be authenticated by existing owners.
- Optional `--sample-group-rss` measures a **Linux procfs sample lower bound** over visible processes with the child's process group ID, at approximately 100 ms intervals. It can miss short peaks, inaccessible processes, processes that change groups, or workloads launched in external services. It adds sampling overhead. Do not substitute it for full process-tree peak or GPU memory measurement.
- GPU, power, model-internal inference p95/p99, FLOPs, throughput, parameter counts, effect outcomes, and scientifically matched task/compute budgets remain **unmeasured by this collector**. A complete arm matrix is not E0/E1/E2/E3/E4 acceptance.
- Local plan/run SHA-256 digests detect unrecorded byte drift but **are not signatures or independent evidence**. A malicious writer can recompute them. Commands can import non-pinned runtime components; a loaded artifact need not be the frozen file unless the trusted inference owner provides that binding. Source weights, parameters and principal scopes are not inferred from filenames.
- The test suite uses temporary Git repositories and controllable subprocesses for **gate correctness only**, not true model training, inference efficacy or AGI performance. No experiment result from fixtures may be promoted or advertised as target-host capacity.

## Tests

```sh
python3 -m unittest discover -v -s tools/hepta-neuron-experiments -p 'test_*.py'
```