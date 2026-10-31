# R10 preread task owner

This is a Linux research executable that owns the **task decision before packet
I/O**, while retaining the real R9 frozen FullHX decoder, finite-state physics,
and Hepta `NeuronRuntime`. It does not activate production authority.

## Build and source provenance

`../integration/prepare_native.py` creates the isolated fresh-build workspace.
Use its generated `just test` and `just build` recipes. No cached executable or
replacement mock runtime is accepted as native evidence. The builder restores
the three original Hepta crates from its recorded upstream source inventory.

`main.rs` imports, without editing, these R9 source modules:

| Module | R9 source Git blob |
| --- | --- |
| `cell.rs` | `2c3371a9834f4ca5e2036eb43aa5bf8a31d5d962` |
| `content.rs` | `3cba4036c10b908bb5ded4fc836a08c1c49355d6` |
| `native.rs` | `c8b40ee8cc757609a76baf101e7a07247288c3de` |
| `owner.rs` | `7ffe8043b87d8292c7044de3f618f1f6c36f2672` |
| `schedule.rs`, included by `owner.rs` | `19ce333b1659a19bdfac6bfb28fba328cbbfbafe` |

Their reference repository commit is
`e7eaa5e0be835269636216c8fe8b1ae2f1a22361` on
`research/hcsn-five-track-r9-20261031`. The fresh builder additionally binds all
actually compiled source bytes into `HEPTA_TASK_NATIVE_SOURCE_DIGEST`.

The R10 changes form three reviewable stages: task contract/policy/schema;
composite owner/storage/CLI; and integration tests/qualification/documentation.
Each new production Rust module remains below 500 lines. No upstream Cargo
manifest or R9 historical source is changed by these modules.

## Interface

```text
hcsn-owner-preread CONFIG.json OWNER_DIR ACKNOWLEDGED_TASK_SHA256
```

`OWNER_DIR` must already be a private regular directory. The initial
acknowledgement is 64 zeroes. After each successful action, the caller saves
`receipt.task_after` externally and supplies it on restart.

The configuration has these fields:

```json
{
  "parameters": [0.2, -0.3, 0.4, -0.1, 0.5, 0.2, 0.4, -0.2, 0.3, 0.5, -0.1],
  "family": "distribution",
  "seed_hex": "ad",
  "content_model": "/absolute/path/fullhx.json",
  "content_model_sha256": "<actual SHA256>",
  "tick_micros": 50000,
  "task": "<Config object from ../value/task.py>",
  "payloads": [{"path": "/absolute/path/packet.json", "sha256": "<actual SHA256>"}],
  "policy": {"kind": "q_table", "entries": {"<state_key>": [0.7, 0.6, 0.5]}}
}
```

The illustrative string in `task` must be replaced with the actual object.
There is one payload descriptor per public packet metadata record. Payload
paths and hashes are executor inputs and are never passed to `Policy::decision`.
The policy interface accepts only the public `Config` and `State`.

One JSON command is accepted per standard-input line:

```json
{"operation":"snapshot"}
{"operation":"decide","task_before":"<acknowledged digest>"}
{"operation":"decide","task_before":"<acknowledged digest>","requested":"READ"}
```

The last form explicitly overrides the policy for controlled action
interventions. Its requested action still passes the same legality guard and
cost accounting. It is not counted as an autonomous learned-policy decision.
Successful decisions return `{"ok":true,"receipt":...}`. A rejected request
returns `{"ok":false,"error":...}`. The receipt contains public state, action,
observation, cost, ledger entry, composite digest, and the unmodified real R9
receipt when native physics executes. Snapshot reports the last acknowledged
public state and does no packet I/O.

## Task and physics semantics

`task_contract.json`, `contract.rs`, and `../value/task.py` define the shared
finite binary task. `READ` takes the first unconsumed arrived packet, spends one
budget unit and one task tick, and pays `read_cost`. On a failed read it also pays
`failure_cost`, appends `x`, and retains the previous posterior. A successful
read appends the actual frozen FullHX binary logit decision and updates Bayesian
log odds using the public reliability. Failed reads still consume their packet.

`WAIT` spends one tick and pays `latency_cost`. After a read, no next read is
allowed until `recovery_until = clock_after + refractory_ticks`. `STOP` is legal
from every nonterminal state, including the initial state. It pays `stop_cost`,
takes no task time, and answers the current posterior argmax, with ties choosing
one. Only an external evaluator holding the private truth assigns correctness.
The owner never receives that truth. An illegal requested action becomes STOP
before payload access, with `invalid_cost + stop_cost`.

Every READ or WAIT makes one real R9 `Owner::step`, with duration `tick_micros`
and driver `2 * posterior_before - 1`. The fixed five-state cell and native
checkpoint are therefore jointly advanced with the task clock. STOP publishes
only the task checkpoint and retains the native frontier. Its `inner` receipt
is null, so it makes no false claim that physics advanced at termination.

Public `failure_probability` informs the teacher/baselines. The owner does not
sample an artificial failure flag. Its `x` must result from an actual failed
packet read/decode/native-preparation attempt. A qualification world can realize
its preselected exogenous failure using a missing or invalid payload at the
execution boundary, after selecting the action.

Q-table entries are exported predictions indexed by the exact visible state
key. They may originate from DP, ordinary features, matched smooth features, or
analytic features. At native inference time they are table lookups, not a native
implementation of an MLP or an exact continuum free-boundary solver. The maximum
is computed over legal actions, with ties within `1e-12` resolved in the order
STOP, WAIT, READ. `one_read` and `fixed_threshold` public-state baselines are also
available.

## Persistence and incomplete effects

The composite checkpoint binds the task, policy, payload manifest, initial
physics identity, frozen model digest, source digest, and latest R9 pair digest.
It includes the full task state, exact IEEE paid-cost/log-odds encodings,
deadline, pending packet metadata, and action ledger. Recovery checks the
external digest, replays the ledger, verifies pending metadata, then invokes the
original R9 recovery and verifies native sequence equals task clock.

After action selection, an intent is created and synced **before** the first
payload access. A successful native commit is followed by an atomically
published task checkpoint and removal of the synced intent. No receipt is
returned before this sequence completes. A failed read can be settled through
one content-free native commit so that time, budget, and failure cost persist.
The original content operation is never retried. If the native owner itself
fails or any publication is incomplete, the composite owner remains poisoned.

An outstanding intent, pending checkpoint, stale acknowledgement, changed
binding, or inconsistent native frontier fails closed on recovery. The program
does **not** promise exactly-once behavior after arbitrary crash timing or
automatically reconcile an unacknowledged side effect. The intent and journals
are retained for explicit reconciliation. Failed reads have unknown payload
byte counts rather than an invented zero-byte measurement.

## Required evidence

`task_tests.rs` exercises real FullHX reads and real native commits, restart,
missing-payload WAIT/STOP, paid read failure, illegal action, stale digest,
changed contract, outstanding intent, and deadline masking. `qualify.py` supplies
the process-level multi-policy/physics-family comparison against the Python
teacher. Fresh compiler results and qualification reports determine pass/fail;
the existence of these sources alone is not evidence that either passed.

The at-most-four-packet binary task, declared observation model, frozen synthetic
FullHX packets, and Linux storage backend are explicit research limits. Native
execution does not establish task utility improvement, a general multimodal
encoder advantage, production readiness, or superiority to Transformers.
