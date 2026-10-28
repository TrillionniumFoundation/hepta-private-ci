# Original-owner free-boundary readout experiment

This is a source-composed research host using the original `AgentdNeuronOwner`,
`NeuronRuntime`, `SparseJournal`, `FileAnchorWitnessStore`, inference-control
receipt types, sparse recurrence, and eligibility computation. Its native source
baseline is PR #4064 at `fb9281e4a7ccfc4034281ed6310adea7e50f4474`.

The host exercises a separately identified finite-state stopping readout. It is
not the complete Agentd daemon, a production deployment, an end-to-end trained
SNN, or evidence that sparse activations learned the task. The readout uses the
observed grid state and remaining time. Native activations and eligibility are
real original-runtime outputs, but they are not substituted for those inputs.

## Composition and authority

`Port::execute_feature` evaluates the registered encoder and stopping readout
while constructing the original inference-control receipt with the exact model,
weights, tokenizer, preprocessing, quantization, runtime, and device tuple. The
versioned readout is retained as a research sidecar; it does not change the native
checkpoint or receipt schemas. `Session::observe` invokes the real owner tick,
checks its authority and abstention, then acknowledges a checkpoint-bound event.

Native authority remains `DENY_ALL`. An explicit `RESEARCH_PERMIT.json` scopes
the host to user-authorized local synthetic observations and outcome files under
one run directory. It grants no external effects, daemon activation, production
permission, or model promotion. Native abstention takes precedence over a
proposed stop: no payoff is awarded for an abstained native tick.

The calibration proof exhaustively checks finite encoder-domain validity.
Prediction equals the registered encoded drive. Its zero finite-domain errors
are **not task-success confidence**, semantic calibration, or production
qualification. Native calibration expiry and resource gates remain active.

## Registered task and references

`PROTOCOL.json` fixes the numerical assumptions, starts, seeds, arms, tie rule,
admission gates, and claim boundaries before scientific execution. The math
module exports the complete transition rows and value table. Transition rows
already include survival; missing mass is an absorbing kill with zero recovery.
Continuation charges its running fee once and discounts the next value once.

All three arms receive identical current state, remaining time, complete known
model, and available actions. None receives future random draws.

| Arm | Decision | Numerical work during a model call |
| --- | --- | --- |
| `free_boundary` | Frozen optimal table lookup | Constant table access |
| `exact_dp` | Recompute one Bellman row using the same preceding value table | One transition-row dot product |
| `constant_threshold` | Tuned fixed lower-abstain/upper-stop pair, with deadline handling | Constant comparisons |

Exact DP parity is an engineering invariant, not an advantage claim. The fixed
pair is selected by expected utility on the complete declared model, using a
predeclared bounded grid, before sampled trajectories. Its early abstention
action avoids an artificial disadvantage from a missing action. In fixed-policy
receipts, `value` and `continuation` remain **optimal-reference diagnostics**;
they are not represented as the fixed policy's own expected value.

This finite Gaussian-bin decision-time MDP is distinct from the continuous
diffusion stopping oracle. The exported table is a numerical Bellman solution.
It is not an exact continuous free-boundary solution or a learned policy.

## Durable behavior

Every accepted unique observation advances the original sparse runtime once
and appends the host event before acknowledgment. The event binds observed
state/time, evidence digest, original checkpoint, native disposition, readout,
and resource receipt. An exact retry returns that acknowledgment without a new
owner tick; a conflicting retry rejects before state mutation.

STOP or ABSTAIN creates a terminal acknowledged event. Later unique observations
are rejected, so later inference and task-transition work are actually avoided.
The separate observed-kill record is also durable. Neither path erases or resets
the original native checkpoint. A native transition without a durable host
acknowledgment poisons the live session and requires reconciliation; the host
does not manufacture a successful retry.

Cold restore validates the event chain against the original sparse computation,
readout and witness frontier, then invokes original journal recovery. Truncated
or altered events fail closed. The run closes and restarts the process after the
first surviving continuation where available; the auditor later reopens every
complete episode and verifies that replay leaves committed bytes unchanged.

## Build and verification

Run these commands from the repository root. Use the installed Rust toolchain
path for `--compiler`. A new build fetches only checksum-verified packages from
the repository lock, then builds offline. It does not modify Cargo policy,
production sources, or the old study.

```bash
python -m experiments.free_boundary_neuron.owner.build \
  --repository "$PWD" \
  --destination "$PWD/experiments/free_boundary_neuron/owner/runs/build01" \
  --compiler /tmp/hepta-ci-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin
```

To rebuild changed research-host source against already verified dependencies,
repeat the command with `--reuse-dependencies`. This preserves previous build
receipts and logs, checks the compiler and lock identities, checks the original
source copies, and uses `cargo build --offline --locked`. It does not run Cargo
tests. The resulting binary and receipt are:

```text
owner/runs/build01/target/debug/examples/free_boundary_host
owner/runs/build01/BUILD_RECEIPT.json
```

Behavioral fixtures use an 11-state, four-step profile, distinct from scientific
trajectories. They exercise actual native execution, stop cancellation, retry
idempotence, conflicting retries, calibration expiry, cold recovery, corrupted
and truncated ledgers, and the sampled-driver/auditor composition. Adversarial
auditor fixtures reject a missing whole paired context, duplicates, parameter
drift, and all-fallback parity.

```bash
FREE_BOUNDARY_NATIVE_BINARY="$PWD/experiments/free_boundary_neuron/owner/runs/build01/target/debug/examples/free_boundary_host" \
python -m unittest \
  experiments.free_boundary_neuron.owner.test_native \
  experiments.free_boundary_neuron.owner.test_audit -v
```

## Registered run and independent audit

The umbrella workflow commits and seals all executable inputs before generating
the authoritative math table and running scientific trajectories. Both runner
and auditor verify the source seal; the runner additionally checks the build
receipt against the current original/native and research-host source bytes.
Do not reuse or overwrite an existing destination.

The following commands continue the fresh `reproduction001` attempt from the
[top-level runbook](../README.md), after its source seal and mathematical export
exist. The registered historical paths under `results/owner/run001` are evidence,
not fresh execution destinations. This block stops if its new owner destination
already exists or if an earlier command fails.

```bash
(
set -e
study="$PWD/experiments/free_boundary_neuron"
attempt="$study/results/reproduction001"
test -f "$attempt/SOURCE_SEAL.json"
test -f "$attempt/math/readout_affine_v1.json"
test ! -e "$attempt/owner"
python -m experiments.free_boundary_neuron.owner.run \
  --binary "$study/owner/runs/build01/target/debug/examples/free_boundary_host" \
  --model "$attempt/math/readout_affine_v1.json" \
  --destination "$attempt/owner" \
  --source-seal "$attempt/SOURCE_SEAL.json" \
  --build-receipt "$study/owner/runs/build01/BUILD_RECEIPT.json"

python -m experiments.free_boundary_neuron.owner.audit \
  --root "$attempt/owner" \
  --model "$attempt/math/readout_affine_v1.json" \
  --binary "$study/owner/runs/build01/target/debug/examples/free_boundary_host" \
  --source-seal "$attempt/SOURCE_SEAL.json" \
  --output "$attempt/owner/AUDIT.json"
)
```

There are 56 paired contexts and 168 episodes. Each natural episode directory
contains its complete original journal/witness, event ledger, immutable identity,
full RPC record, physical process receipt, and separately measured audit replay.
The auditor requires the exact registered roster and identity bindings; an
`INDEX.complete` flag alone is insufficient. It reconstructs rewards and
transitions independently and reports native abstentions separately from
voluntary abstentions. All-native-fallback or an unexercised stop/continue path
fails the execution gate even if the arms agree perfectly.

## Cost interpretation and evidence limits

Counters distinguish actual owner ticks, journal replay, independent event-chain
kernel validation, model calls, readout Bellman terms, full-table validation,
encoder-domain checks, failed requests, bytes, and allocation peaks. Native
process user/system CPU, process wall time, RPC timing, Python orchestration,
threshold tuning, and independent audit are separately recorded. Global math
table-generation costs are recorded by the math export and belong in the
combined study accounting. Cargo invocation times and dependency identities are
recorded separately. Historical dependency acquisition, toolchain and workspace
preparation, and build CPU were not timed; they are not included in a measured
project-wide total. See the [build timing scope](../results/owner/build/history/README.md).

Recorded retry receipts retain the original timing fields for identity, but
those old timings are not charged again as new native work. The retry's actual
RPC overhead is charged. Every open and recovery revalidates the complete table;
these costs can dominate a short task and are included. The task running fee is
a declared utility cost, not measured hardware energy. CPU and bytes do not
establish joule savings. Avoided future tick opportunities are a bounded
counterfactual count; comparisons use the other actually executed arms.

Results are descriptive engineering evidence on the declared model. Negative or
neutral utility/cost differences remain results. Parameter replacement is frozen
within a run; a future learned implementation needs a new compatible bundle,
next-snapshot identity, and separately registered evaluation.

## Review and staging map

The implementation can be reviewed in these coherent groups; no original native
source is changed.

1. `PROTOCOL.json`, this README, and `build.py`: scope, pinned composition,
   dependency identity, and reproducibility.
2. `port.rs` and `profile.rs`: finite readout, exact model receipt, native numeric
   configuration, and narrowly scoped encoder calibration.
3. `events.rs`: acknowledgment binding, exact retry, event validation, and
   checkpoint/witness consistency.
4. `session.rs` and `free_boundary_host.rs`: original owner composition, durable
   stopping, research permit, and cold restoration.
5. `common.py` and `run.py`: transport, complete accounting, paired trajectories,
   fixed-policy tuning, and actual compute cancellation.
6. `audit.py`, `test_native.py`, and `test_audit.py`: independent reconstruction,
   full native replay, exact roster, and adversarial admission checks.

Build trees and engineering scratch output under `runs/` are reproducible local
material. Curated results must retain their true scope and hashes; a selection of
traces must never be labeled a complete raw run.
