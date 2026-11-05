# Native Bellman engineering replay of a frozen structural policy

This package tests migration of the already-scored J policy from [the frozen own-law experiment](../ndu_policy/README.md) to HeptaRuntime's `weight_bellman_plan` MCP method. It uses all **320 already-exposed TEST worlds** from the same five renewal fits. It creates no new scientific candidate, independent holdout or efficacy qualification. Direct weight editing failed in the preceding experiment; its structural Bellman result must not be relabeled as a weight-edit result.

## Completed execution and acceptance

The graph export, unique actual-MCP corpus execution and first frozen independent verifier/replay all completed successfully. Every one of the 320 regenerated J row tables matches its frozen scientific SHA256 identity. The corpus contains **246,160 DAG nodes and 277,892 directed branches**, with at most 1,564 nodes and 1,824 branches per world.

The independent verifier checks **928,200 legal Q values**, all 246,160 legal masks and selected actions, and all 320 expected trajectories. Maximum absolute Q error is **zero** against both the original own-law reference and an independent scalar DAG solver. Every selected action matches exactly, without a near-tie exemption. Reexecuting the 320 original J trajectories from the actual Rust Q arrays gives **zero maximum per-world utility difference**. The native provenance and complete outer execution gates also pass. See [the complete result](replay_r1/run/RESULTS.json), [all per-world comparisons](replay_r1/run/comparisons), and [all trajectory replays](replay_r1/run/replay).

This establishes native migration compatibility for this frozen finite program and these already-exposed worlds. It creates no new efficacy qualification, independent test sample, actual packet execution, production qualification or economic net-value claim. Per-group descriptive means use a different summation routine from the original experiment and can differ in the last displayed decimal despite identical per-world utility.

The export and acceptance protocol SHA256 is `cbe10113183af4d0039126e36cbfcb09d426ddc41062604d2c1e145f8b5d8879`, frozen at `2026-11-05T00:57:24.153062+00:00`. Its source hashes identify `build_graph.py`, `export_graphs.py` and immutable `bridge_io.py`. The complete export worker consumed **138.206351 CPU seconds**, **138.278052 wall seconds**, and **111,501,312 bytes peak RSS**, including imports and final writes. The 300 CPU-second and 600 wall-second caps were not reached. [The outer receipt](export_r1/PROCESS_RECEIPT.json) is separate from the internal timer.

The native execution protocol is `8b6d771876f175670cc03fa32806f5f82bc66d09cd4e4863aae3fdfe7e70d3fe`, binding the qualified binary `a576b51e3fcb3d3a657e9d723bf2a9bfa579a3f6912178ee6e71a14c4ccd9854` and Bellman source `254de61b7a169ab0a01583feb9562051fa9d477d89d98683263c52ea5545a4a7`. Six local qualification commands completed successfully before execution. Their actual records and 14-file source manifest are retained under [native_corpus](native_corpus), not replaced by identity strings. The verifier freeze was written at `2026-11-05T01:57:23.070573+00:00`, before the native corpus started; its SHA is `47bcc34be9ebec1e267084bfc35a81121d37529ad16ee52e7f96d9df6e63d82c` and it binds verifier source `90cf929ae8058c6b604a2ca03d3dcde4ce15a2ae3fbde8a2854e528aa8e7a77d`.

## Inputs and trust boundary

The exporter reads the five exact incumbent C models and the 320 saved public schedules from `../ndu_policy/execution_r1/run`. C's analytic transition/observation model is unchanged from its original checkpoint. It invokes `planning.compile_own` from the frozen scientific source, verifies every original J table SHA, and exports only:

- Own-law observation/failure probabilities.
- Legal finite-state successors.
- Original incremental costs.
- Own-law terminal submission values and STOP value zero.

No environment-truth transition, truth posterior, expected continuation Q, reference action, fitted regression target or scientific utility is passed to the native solver. Own-law terminal values are legitimate graph payoffs. Expected complete Q arrays and selected actions are stored separately under `references/` for verification. Only the ten files under `requests/` and the small `REQUEST_HANDOFF.json` are transferred to the isolated native input directory. The transfer uses create-only writes, verifies every file's SHA256 and size, and does not transfer references.

The Python exporter attests which checkpoint/public schedule produced the graph. The native generic solver authenticates and validates the graph it receives; it does not independently reconstruct or authenticate the checkpoint's physical law. These are separate trust boundaries. The exact canonical-Python argument SHA and native typed-Serde request SHA use different serialization rules and are retained separately. The Python verifier independently reconstructs the actual argument serialization and complete JSON-RPC line and checks their hashes. It only checks that the reported Serde digest has the required 64-hex format and retains it; it does **not** independently reproduce Serde's canonical digest. Independent input binding comes from the raw request/argument hashes plus the fixed native source and binary identities. Neither serialization hash is substituted for the other.

## Why every Markov key has two DAG nodes

The frozen Oracle caches future values at a canonical state with zero sunk charges. Its saved J table, however, queries Q at the first full state encountered by the enumeration, which can have nonzero accumulated charges. In real arithmetic the sunk costs cancel. In F64, `(old_charges + fee) - old_charges` can differ from the same increment at zero charges. A sufficiently close action tie can therefore change if a native port silently normalizes all those queries.

The graph explicitly preserves both forms:

1. **Canonical value nodes** use `Oracle._state(key)` with zero charges. All future references point to these nodes.
2. **Representative query nodes** use the exact enumerated state used by the frozen J table. They apply its original fee subtraction and point to the canonical value nodes for all successors.

There are 123,080 Markov keys and therefore 246,160 graph nodes. Canonical nodes are sorted by decreasing tick, followed by representative nodes in the same key order. Every successor index is strictly less than its source index. This is a finite acyclic graph of the same already-frozen program; it is not a new policy or a relaxed action comparison. Both layers must pass the original Q tolerance and **exact action equality**. There is no near-tie exemption.

## Frozen native interface

The method is `weight_bellman_plan`. Its argument is exactly:

```json
{"states":[{"actions":[null,null,null,null,null,null]}]}
```

Each state's six slots follow STOP, WAIT, READ, REPAIR, SUBMIT-0 and SUBMIT-1. A slot is `null` if illegal, a terminal payoff, or a continuation:

```json
{"kind":"terminal","value":0.0}
```

```json
{"kind":"continue","branches":[{"probability":1.0,"successor":0,"reward":0.0,"fee":0.01}]}
```

The all-null example shows only the object shape; a real request must contain at least one legal action per state. Each state has at most two continuation actions; a continuation has one to three branches. Every field is mandatory, unknown fields are rejected, values must be finite, probabilities and fees must be nonnegative, and successor indices must point backward. The native contract limits a request to 4,096 states, 24,576 branches and 8 MiB of canonical request JSON. The observed maximum request argument is 418,509 bytes.

Probabilities are never renormalized. In input branch order, the continuation recurrence starts from positive zero and, for each nonzero probability, adds:

```text
probability * ((child_value + reward) - fee)
```

The exporter always supplies reward zero. Zero-probability branches remain in the request but are skipped in the arithmetic, matching the frozen Oracle. There is no fused multiply-add or reassociation. Probability-sum error must be at most `1e-12`; the maximum observed export error is `1.9606538614880265e-13`. The chosen action is the first legal maximum, updated only by strict greater-than comparisons.

The response returns one row per input state, with six Q entries (`null` exactly for illegal actions), a value and an action. It also carries tool version/plan identity, typed request SHA, resource/numerical diagnostics and scope. Complete responses are retained; no best-world filtering is allowed.

## Acceptance and independent replay

`verify_native.py` binds the frozen protocol, exporter manifest, C model/public identities, native execution protocol, complete native process receipt, all ten native response aggregates and each actual request identity. It then checks every canonical and representative state:

- Exact legal mask and exact selected action.
- Every legal Q within `2e-12 * (1 + abs(reference_Q))` of the original own-law reference.
- Reported value equals the native Q maximum.
- The same Q/action constraints against an independent ordinary-scalar graph recurrence.

For every passing world, the verifier builds a lookup policy from the **actual Rust response Q arrays** and reexecutes the original expected-trajectory evaluator. The own-law posterior sidecar supplies the original belief diagnostic; the policy's actions come from the native Q table. No Python Q fallback is permitted. Utility must match the saved scientific J utility within `2e-12 * (1 + abs(original_utility))`.

The intended denominator remains 320. Native RPC failures, absent results and all mismatches remain visible. A missing or failing world cannot be silently replaced or dropped. Exact-action failure remains a failure even if the utility difference happens to be small. All reference tables, graph requests, native responses, comparison failures, costs and partial artifacts are retained.

Before seeing native corpus results, a hand-solvable toy gives utility 0.63 and tests zero-probability handling. Seven negative cases check wrong first action at an exact tie, wrong Q with a consistent reported maximum, an unmasked illegal action, nonfinite data, booleans used as numbers, a missing state and an RPC failure. All four executions of these same toy checks are retained; the final one binds the revised verifier after provenance, transport-identity, inner/outer execution-health and empty-group handling changes. They are repeated source checks, not additional cases, independent scientific replications or checkpoint efficacy experiments.

The completed engineering acceptance reports native equivalence and known-world replay separately from the preceding scientific qualification. It does not establish actual Owner/packet execution, original-law authentication by the native solver, private/live Trader improvement, full-network F32 equivalence, new distribution generalization, energy savings or economic net value.

## Storage, cost and reproducibility

The 320 requests occupy ten deterministic gzip aggregates totaling **2,988,116 bytes**. Complete export plus references occupies 28 files and 8,100,882 bytes. Encoded payloads at least 480,000 bytes are split deterministically into 479,000-byte pieces and bound by a `.parts.json` hash manifest. `bridge_io.raw_bytes`, `read` and `lines` reconstruct and verify these parts. `EXPORT_MANIFEST.json` itself is split; its reconstructed SHA256 is `23ff21d3012e230c3b277b3f0a024599be61140accc5ddff4557c376a297a6f7`.

Export preparation, native compilation, actual MCP execution, transport, Python comparison and J trajectory replay are reported separately. The 138.206351-second export includes reconstructing and auditing the original J program and preparing both reference layers. A later Rust graph-only solve time must not be presented as replacing that entire pipeline. The trajectory replay loads native Q outputs; it does not invoke Rust at every visited state. Instrumented lookup time is therefore not a native inference benchmark.

| Completed phase | Complete worker CPU seconds | Wall seconds | Memory observation |
|---|---:|---:|---|
| Graph/reference export | 138.206351 | 138.278052 | 111,501,312 bytes peak RSS |
| Actual native MCP driver and waited descendants | 37.789511 | 75.133058 | 948,220 KiB maximum descendant peak RSS |
| Independent comparison and all J trajectories | 52.947453 | 52.973096 | 212,090,880 bytes peak RSS |

The three disjoint process intervals total **228.943315 CPU seconds**. This is not a full project, training or deployment cost: it excludes Rust compilation/qualification, tool transport, LLM work, energy and the small supervisor setup/publication intervals explicitly outside the measurements. Native internal timing overlaps the 37.789511-second outer interval and is not added again. The memory observation belongs to the complete native harness/process lifecycle and is not a measurement of the standalone Rust solver's steady memory. Rust build and test costs are retained in its separate qualification receipt.

Both directions of transfer retain SHA verification receipts. Download first attempted to place an entire compressed group in one local shell argument; the operating system rejected that command as too large before any group file was written. The transfer then used bounded, version-pinned chunks with independent chunk and full-file SHA checks. This transport correction did not rerun any graph, native request or trajectory and is recorded in [NATIVE_DOWNLOAD_RECEIPT.json](NATIVE_DOWNLOAD_RECEIPT.json).

For a full new native execution, make a fresh sibling source directory containing only the scripts and acceptance protocol. This leaves the published evidence and freeze files unchanged while preserving the relative source-package paths:

```bash
mkdir ../native_bellman_replay_independent
cp ./*.py PROTOCOL_FROZEN.json ../native_bellman_replay_independent/
cd ../native_bellman_replay_independent
```

Then export from the sibling frozen scientific package:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python run_stage.py export \
    --science ../ndu_policy \
    --joint ../../wsp_20261104/joint \
    --protocol PROTOCOL_FROZEN.json \
    --output independent_export
```

The native owner supplies a separately frozen `EXECUTION_PROTOCOL.json`, source/build identity and actual MCP runner. It must use the exported graph requests, preserve all planned 320 worlds, and retain the full ten response aggregates with `NATIVE_CORPUS_MANIFEST.json`. In a fresh working copy, freeze the verifier source and native execution identity before inspecting corpus results (the published freeze must not be overwritten):

```bash
python check_verifier.py
python freeze_verifier.py \
  --acceptance PROTOCOL_FROZEN.json \
  --native-protocol native_execution_protocol.json \
  --exported independent_export/run \
  --output VERIFIER_FREEZE.json
```

Then execute the native corpus under that native protocol and perform the independent comparison/replay:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python run_stage.py replay \
    --science ../ndu_policy \
    --joint ../../wsp_20261104/joint \
    --protocol PROTOCOL_FROZEN.json \
    --exported independent_export/run \
    --native native_corpus_output \
    --output independent_native_replay
```

Every output directory must be new. Original freezes and receipts remain immutable. Full independent reproduction requires the exact native execution identity or a new, explicitly recorded engineering source freeze before that reproduction's results are inspected. This does not authorize altering the original scientific evidence or claiming a fresh holdout.
