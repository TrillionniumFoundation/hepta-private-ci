# Independent parametric-memory implementation review

Reviewer: `/root/action_verification`  
Repository: `/workspace/scratch/1d69f04ee9f4/hepta-private-ci`  
Branch: `codex/memory-parametric-cell-loop-20261023`  
Review context date: 2026-10-23

## Completed independent validation

| Check | Actual result | Scope |
| --- | --- | --- |
| Parametric unit discovery in recovered runtime | 26 methods passed, 4.410 s, exit 0 | Evolution had 3 methods when this process imported it. Model 9, owner 9, transport 5. |
| Newly added nochange regression | 1 method, 4 policy scenarios passed, 1.058 s | Covers regression, same score losing an original correct item, continuation, and qualifying split. |
| Real decoder network/lifecycle integration | Exit 0; 6 network and 3 lifecycle fresh worker subprocesses | Actual tiny Llama/PEFT writes, saves, loads, owner calls and source revocation. |
| Global optimizer-hook counterexample after fix | Write rejected, foreign parameter remained 7.0, hook calls 0 | Before fix the same concrete counterexample accepted the write and changed the foreign parameter to 8.0. |
| Latest source whitespace check | `git diff --check` exit 0 | Root owns final formatting and commit. |

Root separately reported a full latest 27-method unit pass. The 27-method single-run result is not claimed as this reviewer's execution.

## Integration evidence and reproduction

`integration_smoke.py` preserves the exact Python body previously executed inline. `integration_observed.json` transcribes the completed tool output, including process exit status. Temporary model/adapters/journals were deliberately scoped to a `TemporaryDirectory` and removed on normal exit, so they are not represented as retained artifacts.

Run from the repository directory:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/parametric-runtime-1d69f04ee9f4:scripts/memory_cell \
/workspace/scratch/1d69f04ee9f4/parametric-venv/bin/python -B \
/workspace/scratch/1d69f04ee9f4/parametric-review-20261023/integration_smoke.py
```

The integration built a real tiny parent adapter and four trained descendants. For consumer-path coverage it explicitly chose `nochange`, then verified that all four routed nochange queries read the original parent manifest; all three arms were actually read in six fresh worker processes. This explicit choice is a test input, not evidence that natural model performance selected nochange.

Lifecycle execution used three further fresh worker processes for corrected, rebuilt and unknown-key diagnostic reads. Revoking one source rejected the parent/corrected slot and all four learned descendants before any model forward. The test also exercised frontier persistence across owner restart, clean replay from the base, exclusion of deleted roots, and publication at owner generation 2. It made no accuracy claim for the randomly initialized tiny model.

## Review findings closed

1. **Optimizer global callback escape:** a real counterexample modified an unrelated tensor. The writer now rejects global pre/post optimizer hooks at entry and before every optimizer step; the independent counterexample now fails before the callback.
2. **Training versus generation budget:** source values plus EOS must fit the 16-token raw generation budget.
3. **Verified ancestry:** ordinary reads/writes compare the current adapter digest with its expected state. Shuffling is confined to the closed diagnostic worker and recorded as a changed consumed state.
4. **Acquisition inventory:** extra tokenizer/chat-template files cannot silently alter the pinned decoder profile.
5. **Regressing candidates replacing the parent:** selection now retains the parent when neither continuation nor split satisfies preservation requirements. Four specific policy cases passed.
6. **Nochange consumer omission:** the network now reads all three arms, including the nochange parent artifact; the real fresh-process integration covered this path.
7. **Selected network absent from the overall quality gate:** the protocol now predeclares selected-network accuracy at least 0.75 and preservation of nochange accuracy. The runner reads the already chosen arm's final metrics and requires both conditions without changing selection. Static verification confirmed this after the root fix.

## Other reviewed boundaries

`parametric_metrics.binding_specificity` measures symmetric swapped-target margins using real full-vocabulary decoder logits with the adapter disabled/enabled. Same-prompt logit differences equal corresponding log-probability differences because normalization cancels. It does not generate, train or select candidates. `exact_kv_baseline` executes SQLite writes and reads, retains unresolved queries and reports real allocated-page bytes; it does not assert unmeasured ideal accuracy.

Warm-start split children retain every learned parent source root. Splitting therefore does not reduce the source-revocation blast radius in this implementation. Clean-base replay is the explicit recovery mechanism. The owner is a durable local research owner; the worker is a fresh interpreter with closed JSON input, not an operating-system sandbox or a distributed consensus implementation.

## CI wiring delivered

`.github/workflows/hepta-parametric-memory-shadow.yml` is a separate, single-job shadow workflow. It uses the repository's pinned checkout/setup/upload actions, exact source identity, Python 3.12, torch 2.5.1 CPU and fixed requirements. It runs parametric units plus the evolution/process regressions; downloads the pinned public base; runs confirmation with a nonzero exit on mechanism failure; uploads reports, adapters and the acquisition sidecar but not the base checkpoint. It does not change existing production gates or the existing four-checkpoint matrix.

Workflow checks completed earlier: YAML and semantic trigger/action/artifact assertions, `bash -n` for all six shell blocks, and `git diff --check`. This document does not claim an executed GitHub Actions result.

## Remaining evidence belongs to the root run

No additional implementation blocker was found in the reviewed scope. The source-frozen, real SmolLM2 confirmation and remote CI must determine actual recall, correction and selected-network gates. Passing tiny mechanism tests does not establish storage compression, statistical unlearning, general memory capability or deployment acceptance.
