# Typed trainable memory: bounded integration

This research stack connects a typed source authority, real adapter training,
independent TCP workers, and an independently scored natural CI domain trial.
It extends the existing `memory_cell` / `memory_cell_population` experiments;
it does not replace their negative results or qualify production deployment.

## Components

| Directory | Responsibility | Evidence boundary |
| --- | --- | --- |
| `memory_cell_service` | Source revisions, immediate overlay, durable outbox, leases, immutable parameter versions, conflict and withdrawal admission | `semantic` and `procedural` are stable identities; a type name does not prove a capability |
| `memory_cell_domain` | Pinned natural failure / repair / success data, real LoRA candidates, learned routing, retrieval controls and cost accounting | A short repair-ID prediction is not an executed debugging procedure |
| `memory_cell_network` | Source-bound authority, authenticated TCP, checkpoint transfer, placement CAS, durable fences and restart behavior | The local integration uses independent processes on one physical host |
| `memory_cell_system` | Real pretrained lifecycle trial, retained receipts, exact-source identity and integrated hosted checks | Synthetic facts establish finite mechanism behavior, not future-task advantage |

The source service owns truth revisions. A query can read a new event from the
explicitly labelled source overlay immediately. Parameter reads are separately
admitted and preserve raw model output. They never substitute an overlay value
for the decoder response. Corrections and withdrawals invalidate a stale
parameter binding before a new checkpoint is available. The current baseline
rebuilds from the frozen base using every remaining unconflicted fact. This is
expensive but gives an auditable recovery path; efficient selective unlearning
is not claimed.

The network authority reads that same source service. Workers receive no source
values through the frontier RPC. A logical `(scope, cell_id, role)` remains
stable while a placement generation changes its physical executor. A stale
placement, withdrawn ancestor, authority outage or in-flight frontier change
denies or discards the answer. HMAC authenticates transport messages; the local
HTTP implementation is not an encrypted public-network deployment.

## Mechanism checks

Install the pinned CPU runtime in `../memory_cell/requirements.txt`, with
`torch==2.5.1` from the official CPU wheel index, then run from the repository:

```sh
bash scripts/memory_cell_system/run_tests.sh
```

These tests use tiny trained decoders and actual loopback TCP processes. They
check publication crashes, bounded retries, lease expiry, source CAS, immediate
reads, raw parameter generation, migration, fencing, withdrawal and recovery.
They are behavior checks, not a memory-capacity benchmark. POSIX directory
flushes are exercised; sudden machine power-loss recovery remains unverified.

The scoped `hepta-memory-system-shadow.yml` checks the exact PR head, installs
a pinned CPU runtime, and retains source, runtime and test logs. It does not
merge the stack, run a production deploy or promote a scientific conclusion.

## Real pretrained lifecycle

Acquire the model with the existing `prepare_parametric.py` command. The base
and tokenizer digests are checked by that module; an arbitrary model path is
not accepted as a substitute for the pinned base. Use a new output directory:

```sh
python -B scripts/memory_cell_system/system_trial.py \
  --model /absolute/path/to/pinned-smollm-135m \
  --output /absolute/path/to/new-lifecycle-run
```

The fixed protocol performs 32 background optimizer updates and three clean
256-update publications (800 total), rank 8, seed 2718 and learning rate 0.001.
Eight initial synthetic facts receive a ninth while training is in progress.
The superseded attempt must not publish. Independent fresh-process adapter,
disabled-adapter and shuffled-weight reads use held-out wording. The same
checkpoint then executes on two independent workers before and after migration.
The run exercises conflict, correction, withdrawal, clean replay, restart and
authority outage with real pretrained weights.

The receipt separates engineering gates from parameter-control gates. Initial,
corrected and retained accuracy must each reach 0.75; the initial adapter must
exceed disabled and shuffled controls by at least 0.50; the specifically
corrected fact must decode to its new value. Both groups must pass for exit 0.
Source overlay accuracy is excluded. All raw text, token IDs, prompt identities,
training receipts and checkpoint hashes remain available when a gate fails.
The transport key is temporary and removed when the process group closes.

Freeze all `scripts/memory_cell*/*.py` files and Git HEAD during a run. The
runner compares their complete identity before and after execution. Formatting,
committing or changing even another memory experiment during that interval
invalidates the source-identity gate. A previously existing output directory
is rejected rather than overwritten.

## Natural domain and fair comparisons

See `../memory_cell_domain/README.md` for the producer and training command.
The first development cohort has three independent historical CI incidents.
More templates, model reads and artificial unknowns do not increase that count.
Its validation and future partitions are empty. Its results must not be used
as evidence for capacity pressure, an unseen future cohort or procedural repair
execution.

The domain runner compares continued training, a larger adapter, a data-driven
split, a random split and strong source retrieval. Expanded and split candidates
match adapter bytes, optimizer updates and input tokens. Router, gradient,
inference, source and base costs remain separately recorded; this is not an
assertion that total system cost matches. Retrieval is eligible to win the
source-only selector. Raw held-out scores, when available, cannot choose an arm.

## Acceptance still required

This stack makes the four-phase proposal executable and falsifiable. The
research target remains a future-task advantage over strong retrieval under
the same total resource budget, followed by incremental value from learned
splitting and connections. Qualification needs independent task groups,
adequate capacity pressure, executed task outcomes, frozen development choices,
and uncertainty over independent groups. True multi-host failure recovery,
privacy and source locality, consensus or resilient authority replication,
net storage compression and production integration are separate acceptance
items. A passing finite mechanism trial does not close them.
