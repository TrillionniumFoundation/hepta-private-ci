# Native task bridge: development qualification, 2026-10-31

This package executes a genuinely trained residual policy in Rust through the
real current-main `codex-hepta-neuron::NeuronRuntime`. It closes the mistaken
"no native toolchain" conclusion and qualifies a concrete native model/owner
boundary. It does not activate production or implement the analytic cell physics
in Rust.

## Qualified result

| Check | Evidence | Result |
| --- | --- | --- |
| Exact native source | `SOURCE_IDENTITY.json` | 60 files from main `732e934ba496d90fbe042b8d41d479ef901643e5`, Git blob identities checked before copying/building |
| Actual toolchain | `BUILD_Q24_PROFILE.json` | Rust 1.96.0, Cargo 1.96.0, actual just 1.59.0; isolated offline locked build |
| Required workflow | `FORMAT_Q24_PROFILE.json`, build report | Actual unchanged current-main `just fmt` and `just test` workflows, no fake command wrapper and no direct cargo test |
| Native owner/model tests | `BUILD_Q24_PROFILE.json` | 10 passed, 0 skipped |
| Original float64 compatibility attempt | `qualification_dev03/result/REPORT.json` | **Rejected**: 5/512 action differences at float64 ties; retained unchanged |
| Explicit shared numeric profile | `qualification_dev03/profile_result/REPORT.json` | 512 previously unevaluated development vectors, 0 Python/native profile action differences |
| Actual file/model task parity | `qualification_dev03/task_parity_cached/REPORT.json` | 33 paired cases pass: 16 IID, 16 OOD, 1 real missing-packet case; 134 completed file reads and content invocations; 64 completed-effect restarts |
| Production/physics/effect authority | All reports | `production_activation=false`, `native_physics_executed=false`, `DENY_ALL` |

The selected development policy is a nonzero learned 65-by-64 tanh network
(selected at update 6000), with four residual outputs. Its unchanged checkpoint
file SHA256 is
`fce8e093bef9e6f8f3a55641469463822ea0c3c30827d53ed0aa5c9e033b3cc4`.
This is a numerical and integration qualification, not a claim of heldout
task-utility superiority.

The final native build source digest is
`52df63ce0650c0e806e890b69c88b9202244422a1d1b7304a7af571ab5a1b2b5`.
The final binary SHA256 is
`20f1db337c544e7c2f1ea8c4c29ae7cc87f1d933258490833e6647d793b693a2`.

## Exact responsibility boundary

| Responsibility | Owner in this qualification |
| --- | --- |
| Public feature construction and bounded OneRead prior | Python `task_policy_v2_20261031.planner.OneRead` |
| Frozen normalization, tanh MLP, nonnegative residual, numeric score conversion | Rust `model.rs`, actual `NeuronModelPort` implementation |
| Stable masked action selection | Current-main native sparse kernel, width 5/top-k 1; four actions plus a zero sentinel |
| Native sequence, model/deployment identity, exclusive ownership, durable journal and independent acknowledgement witness | Current-main `NeuronRuntime<FileAnchorWitnessStore>` |
| Actual packet reads and frozen content decoder | Existing Python task owner/`ContentAdapter` |
| Incremental cell propagation, reset and snapshot restoration | Python `recurrent_owner_v2_20261031.CellOwner` |
| Binding external cell/public state to each native tick | Request hashes included in the native tick evidence digest |
| Physical effect settlement and arbitrary-crash exactly-once dispatch | **Not implemented or claimed by this bridge** |
| Production NDU, production OOD calibration, authority/promotion | **Not implemented or claimed by this bridge** |

The external analytic cell in the task parity fixture is used to qualify causal
lifecycle binding. Its five features are **not inputs to this new 65-feature
residual MLP**, so this fixture does not identify an analytic-cell policy effect.
The native sparse temporal decay is zero in this adapter to preserve the frozen
policy's action scores. The adapter therefore does not replace the native neuron
with a native first-passage or regenerative-cell solver.

The inherited calibration fields remain explicitly unestablished worst-case
research bounds. A native signal receipt is not a grant to execute effects.

## One numeric deployment model

`reference.py` is the shared Python contract. Rust implements the same contract
in `contract.rs`, `model.rs`, and the actual native sparse selection kernel.

Contract identifier: **`hepta.task.native-q24-residual.v1`**.

1. Require finite raw input features in `[-8, 8]`; reject outside the envelope.
   Convert each feature to signed Q24 with round-to-nearest, ties away from zero.
   Legal prior scores use the same conversion; illegal prior coordinates become
   zero.
2. Keep checkpoint normalization and weights as float64. Compute
   `x = clip((raw_q24 - mean) / scale, -8, 8)`,
   `h = tanh(x @ w + b)`,
   `q = prior_q24 + max(h @ v + c, 0)`, and set `q[STOP] = 0`.
3. Require legal scores in `[-4, 4)`; reject saturation instead of silently
   clipping. For legal actions, use integer drive
   `round_away((q + 4) * 2**24)`. Illegal actions and the fifth sentinel receive
   zero drive. STOP is always legal, so its positive drive prevents sentinel
   or illegal selection.
4. Select the largest integer drive, breaking ties toward the lowest action
   index in `STOP, SKIP, READ, FIRE` order.

The generic `select_action(scores, feasible)` helper can be shared by bounded
planner, teacher and residual deployment profiles. The residual must additionally
use `infer(checkpoint, raw, prior, feasible)` to match input conversion. Training
and the original float64 selection references remain separate, unchanged
scientific objects.

A deployment model binds both unchanged checkpoint bytes and numeric contract:

```text
SHA256(
    b"hepta.task.deployment-model.v1"
    || bytes.fromhex(checkpoint_sha256)
    || b"hepta.task.native-q24-residual.v1"
)
```

The native head/journal configuration uses this identity; every request must name
the numeric contract, and every receipt returns the deployment identity. The
qualified selected model's deployment identity is
`888c81ced0bba22211ecffb4e92c6a6e3a733f69ee23976b783a05ccc21a8b37`.

### Near ties and quantified error

The first attempt required zero action disagreement with unquantized float64
`numpy.argmax`. It failed: all five disagreements had float64 score differences
of roughly `5.55e-17` to `2.22e-16`. That evidence is retained as rejected.
The corrected deployment contract was then evaluated on the next fixed 512
development rows; it was not fitted to new task outcomes or used to retrain the
checkpoint.

Under the explicit shared profile, maximum score error against the independently
executed Python Q24-input reference was `4.440892098500626e-16`, with zero action
disagreements. Relative to the original float64 scores, maximum observed error
was `1.0665615779448245e-7`; one original float64 tie still selected a different
action. Original float64 action equivalence is expressly false.

For each non-STOP action, the conservative real-arithmetic quantization bound is

```text
2**-25 * (2 + sum_j abs(v[j,a]) * sum_i abs(w[i,j]) / scale[i])
```

It includes feature, prior and final score conversion. This model's maximum
bound is `7.621608845300435e-6`. A float64 top-two legal score gap greater than
twice that bound, plus the stated arithmetic tolerance, guarantees stable
selection under the stated assumptions. No stability claim is made inside that
gap. Envelope rejection, normalization clipping, and a nonfinite input are
separate cases; no hidden saturation is used to make the test pass.

## Native lifecycle tests

The 10 actual Rust tests cover executed nonzero MLP math, legal masked native
selection, STOP tie order, correct restart after the acknowledged frontier,
stale predecessor rejection, duplicate/out-of-order sequence rejection, input
and model identity rejection without durable mutation, independent witness
detection of acknowledged journal loss, exclusive native ownership, invalid
checkpoint shapes, and numeric-contract/saturation rejection without commit.

The 512-vector test restarts the actual process after sequence 256 and injects
an out-of-envelope request. Journal and witness bytes must remain unchanged for
that rejected request.

The 33 task pairs execute real file reads and the inherited frozen decoder. Every
normal rollout restores the Python task owner, Python cell owner and native
process after the first completed action. The negative case renames generated
packet files so the actual read fails; both backends retain its query and elapsed
time charge and report the failed attempt. These restarts happen at acknowledged
completed-effect boundaries. The bridge does not claim safety for interruption
between a native decision commit and an external physical effect.

## Cost evidence

`client.py` records process setup, IPC wall time and bytes, native execution and
MLP wall microseconds, journal bytes, parent CPU, and Linux `wait4` resource usage
for the exact child process. The final full child lifetime includes startup,
model parsing, native commits, recovery and shutdown. Ordinary `/proc` reads in
this managed environment returned placeholder statistics and were discarded;
they are not used as evidence.

The final parity runner converts the Python model to NumPy arrays once per
rollout, so neither backend is charged repeated Python weight parsing per
decision. Each of the 32 normal pairs includes an intentional native process
restart. In this development measurement:

| Backend | Mean complete CPU / normal rollout | Mean wall / normal rollout | Mean completed reads |
| --- | ---: | ---: | ---: |
| Shared-profile Python | 0.020946 s | 0.020972 s | 2.09375 |
| Actual native model/owner bridge | 0.044845 s | 0.058852 s | 2.09375 |

The native path is slower here. These are debug-build integration measurements
with filesystem durability and restart costs, not optimized production latency
or energy results. Combined CPU across all 66 rollouts was 2.118966 s, including
0.693685 s of native child CPU. Model-training costs belong to the policy campaign
and are not hidden inside these inference measurements. No energy saving or net
task-benefit admission is inferred from this fixture.

## Reproduction and handoff

`build.py` requires an exact source checkout/cache matching `SOURCE_IDENTITY.json`,
an unchanged current-main workflow root containing the real justfile and scripts,
an existing Cargo registry cache, the Rust toolchain, and actual just/nextest
binaries. It creates its own generated minimal Cargo harness and target directory.
The three native crate manifests and all 57 Rust files are copied unchanged.
The root workspace harness is deliberately derived and recorded; this is not a
full production-workspace build or its full CI.

Example shape (replace paths with the actual local installations):

```sh
python tools/hcsn/native_task_bridge_20261031/build.py \
  --source-root /path/to/exact-source \
  --workflow-root /path/to/exact-workflow \
  --build-dir /path/to/new-isolated-build \
  --cargo-cache /path/to/cargo-cache \
  --toolchain /path/to/rust-toolchain \
  --tools /path/to/actual-just-and-nextest \
  --report /path/to/new-build-report.json
```

Run `verify_profile.py` with a fixed 512-vector JSON fixture and
`task_parity.py` with a fresh output directory. `NativeClient` and `run_one`
are the integration points for later source-frozen, five-model qualification.
The same source must be validated against each final frozen checkpoint before
any cross-model or deployment-wide claim.

The source-publication allowlist is `PUBLICATION_MANIFEST.json`. Raw receipts,
generated packets, journals, witnesses, earlier attempts and the prior numeric
sources are preserved in the evidence archive; empty stderr files are omitted
from that archive and no binary is required in the source tree.
