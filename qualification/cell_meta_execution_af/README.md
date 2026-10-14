# A–F Cell / Meta Network / Execution evidence gate (shadow only)

This is **one read-only conformance checker**, not another Neuron, NDU, Selector,
Cell Split execution owner, inference driver, model loader, or Codex fork.
It compares declared evidence for the six requested experiments without changing
any runtime, deployment, authority, selected model, routing, or Git branch.
It does **not** produce independently authenticated scientific evidence.

## Exact coverage

| Gate | Registered arms | Mandatory structural checks |
| --- | --- | --- |
| A / local learning | `no_change`, `frozen_head`, `learning_head` | Two prospective independent task sets; frozen cutoff; complete paired arms; real invocation counters; Brier/ECE/OOD/retention/negative transfer |
| B / split efficacy | `unsplit`, `shared_head`, `child_heads` | Both future windows versus *both* no-split baselines; resource-aware **net** NDU utility; do not confuse cell accuracy with physical cutover permission |
| C / Meta Network | `fixed_graph`, `learned_router`, `adaptive_depth` | Equal registered budget, fixed candidate set/objective, comparable task sets, separately measured learned policies |
| D / meta-learning | `no_adaptation`, `fixed_rule`, `learned_rule` | Unseen task families, prospective adaptation, distinguish learned update rules from separately tuned fixed optimizers |
| E / placement | `in_process`, `shared_worker`, `per_cell_process` | All 64/256/1024/4096 Cell scales × fixed/varying active concurrency; identical attempted-request trace and host; genuine backend/cpu/RSS/GPU/queue/p95/p99/lock/CAS/signature/CNS/WAL/recovery counters; failure accounting |
| F / Codex boundary | `full_codex_agent`, `app_server_provider`, `direct_effect` | Same task suite on same host as E, each with permitted/denied effects; real terminal observation and separate original effect-owner receipt; direct effect cannot hide model calls |

Separate Cell Split **safety** gate requires one fenced coordinator ledger,
original CAS/migration/bootstrap/CNS/Supervisor owner signed receipts and current
readbacks, independent Final-use/Selector flags, and three crash-recovery cases.
A complete split *safety* envelope is not a demonstration of learning benefit.
A proposed learning improvement also requires two prospective windows and the
canonical independent Evaluator/Selector. Neither gate grants runtime authority.

The `source_sha` / `source_tree` refer to the exact *experiment candidate*;
`objective_sha256`, frozen `no_change_sha256`, `budget_sha256`, and
`source_dataset_sha256` are common immutability anchors. The `future_1` and
`future_2` source-task set digests must be distinct. All arms in a comparison
must use the same `task_set_sha256` within each window. Each observation row
supplies independent episode count/ESS, pre-label prediction commitment,
outcome receipt, model bundle, actual training/inference bytes and real model
invocation count. `net_utility_lcb/ucb` **must already include** the declared
training, inference, migration, communication and risk costs under the fixed
NDU profile; this reader does not recompute an unauthenticated utility function.
An interval reported in JSON is not proof that the estimator or observer is
independent, preregistered or statistically sound.

Source bindings this checker **does not replace**:

- Neuron/Head inference and real shared features: `codex-rs/hepta-infer-core`, `codex-rs/hepta-infer-worker-host`, draft #1498.
- Independent causal evaluation and learning artifacts: existing `learning.eval`, `learning.ledger`, `learning.artifacts`, `utility.ndu` owners.
- Safe Cell Split original effects and recovery: `hepta-operator-acceptance`, the one Cell Split execution owner, signed custody/Selector; drafts #1764/#1776.
- Codex execution: `hepta-codex-adapter` + existing App Server and **separately authorized** effect owner; the current native inference caller is model-only and must not be counted as tool execution.
- Related experimental branches: A/B/C shadow #1779, Encoder study #1772, Stem E1–E6 screening #1783 and resource #1761. Do not overwrite or implicitly combine their unreviewed source.

## Run

Run the adversarial fixture suite (requires Python 3.10+; no external packages):

```sh
python3 -m unittest discover -v -s qualification/cell_meta_execution_af -p 'test_*.py'
```

Inspect an **externally assembled** JSON envelope (no fabricated evidence):

```sh
python3 qualification/cell_meta_execution_af/gate.py /path/to/actual-af-observations.json --out /tmp/af-shadow-report.json
```

The envelope has `schema: "hepta.cell-meta-execution.af.v1"` and fields
`candidate`, `studies` (A–D), `resources` (E), `codex` (F), `split_safety`.
The synthetic `synth()` fixture in `test_gate.py` documents exact row fields;
its hashes, run counters and successes are invented **test values**, not results.
Do not export those values as evidence or use `synth()` to fill missing rows.

Exit status `2` means blocked or incomplete; exit status `0` means only
`shadow_structural_review_only`. Even status `0` always prints
`authority_posture=DENY_ALL`, `physical_split_permitted=false`,
`production_selection_permitted=false` and `model_promotion_permitted=false`.
All successful self-tests, valid-looking digests, positive utility intervals and
`real_worker_executed=true` fields remain self-assertions until original-owner
signed readback, trusted source provenance, separate observer and target-host
measurement are actually verified outside this checker. Code does not run a model,
load an artifact, contact an issuer, authenticate signatures, or measure hardware.

## Required next real gates

1. First obtain exact-SHA source/merge CI for the existing owner PRs. Fail closed on missing, failed or cancelled checks; synthetic cases cannot replace those checks.
2. Prove **actual** immutable model/Encoder invocation, frozen no-change predictions before labels, independent outcomes and two nonoverlapping future windows. Independently validate ESS >= 400 and negative-transfer/retention/profile-specific calibration/abstention floors.
3. Prove one real CAS → child migration/bootstrap → CNS route cutover → Supervisor generation fence, with original signed effect receipts, independent trusted anti-rollback custody, power-loss/restart reconciliation and zero duplicate effects.
4. On **one named target host**, run all E placements, both load profiles and four scales, with exact shared attempted input traces and original telemetry. Do not treat 4,096 registered Cells as 4,096 simultaneous model invocations.
5. Compare Codex Agent, Codex model-only App Server followed by independently authorized effect, and direct effect under the same task inputs, policy and host. Observe both allowed and denied actions, including original effect-owner readback; turn completion alone cannot prove the effect happened.
6. The existing independent NDU Evaluator / Selector decides on **real** future-window net utility, not this checker. Production activation/release always belongs to the pre-existing owners and gates.

No automatic merge, production cutover, Cell/Encoder promotion, package extraction,
new global authority or autonomous self-iteration is proposed by this harness.
