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

1. Create an *untracked, local* `manifest.json`, with exactly two keys: `shared` and `arms`. `shared` must map `encoder`, `tokenizer`, `dataset`, `objective`, `runtime` to **nonempty actual files**. `arms` must map every arm in the chosen stage to its **actual on-disk candidate weight/artifact bytes**, not a made-up digest. Preserve training budgets, dataset split, model preprocessing and actual per-arm parameter inventory separately under the existing learning/evaluation owners. Do not put private data, model weights or the generated plan into public git history.
2. Freeze after the source checkout, model artifacts, objective and dataset are selected, *before* observing holdout outcomes:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py freeze \
     --stage E0 --manifest /secure/manifest.json --out /secure/e0-plan.json
   ```

3. Submit that frozen plan digest to an **independent evaluator and immutable plan registry**. A local JSON digest alone is *not* a trusted signature or proof of preregistration. For each arm, call its real, bounded executable (no shell interpolation). For instance:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py run \
     --plan /secure/e0-plan.json --arm no_change --timeout 120 \
     --out /secure/e0-run-001.json -- /path/to/qualified-neuron-runner --benchmark-workload /secure/task.json
   ```

4. Audit **only the execution inventory**:

   ```sh
   python3 tools/hepta-neuron-experiments/measure.py audit \
     --plan /secure/e0-plan.json --receipts /secure/e0-run-001.json
   ```

5. Let the existing independent `learning.eval` and `learning.artifacts` owners consume frozen datasets, signed outcomes, no-change baselines, real Tensor/Worker/model receipts, support and fairness diagnostics. They—not this collector—decide whether an experiment supports a model or Cell-structure change. No automatic selection, self-authorization, production activation, merge or release is performed here.

## Limitations and refusal semantics

- `run` actually executes a child process and records its exit, wall duration, **direct child** CPU and peak RSS via POSIX `wait4`. It binds the executable and raw stdout/stderr bytes by SHA-256, checks log sizes while the child runs, kills its process group on timeout/log-budget breach, and fails on nonzero exit, source drift, artifact drift or wrong host. The command is **not sandboxed**; only run trusted binaries within existing authorization envelopes, with no production credentials in the benchmark environment.
- Direct child RSS is not full process-tree peak memory. GPU, power, warm inference latency distributions, backend FLOPs, throughput, parameter count, and outcomes are **not measured** by this collector. Do not substitute a successful run for these missing metrics; E0/E4 therefore remain *unqualified* until real provider/target-host meters are attached.
- Plan and receipt hashes provide accident/tamper detection and byte binding, **not authenticity**. The independent observer must attach an externally verifiable signature/identity and genuine future-time holdout evidence. Logs may contain sensitive data; retain securely, do not upload as public artifacts.
- `audit` checks exactly the registered arms, run status, source/artifact/host identity and logs. Its `execution_matrix_complete=true` field **never** means parameter fairness, causal uplift, AGI, scale benefit, operator acceptance, topology cutover or a green production gate.
- The test suite uses ephemeral git repositories and mock command-line processes for fail-closed *control* verification. These are **not** model performance or efficacy tests.

## Tests

```sh
python3 -m unittest discover -v -s tools/hepta-neuron-experiments -p 'test_*.py'
```
