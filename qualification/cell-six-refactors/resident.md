# Joint generation: shared resident proposal worker

This change adds an explicit resident transport for the existing Joint generation worker. It reuses immutable numerical assets and an initial public encoding while retaining the existing Cell state, control and publication owners. It does not establish high-frequency fleet capacity or qualify a trained model.

## Selection and ownership

The public API remains `JointGenerationProcessWorkerV1`, exported by `hepta-neuron`:

| Host construction | Required manifest profile | Helper invocation |
| --- | --- | --- |
| `open(config, clock)` | `joint-generator-proposal-linux-v1` | One `hepta-joint-propose` process per operation |
| `open_resident(config, clock)` | `joint-generator-resident-linux-v1` | One lazily started `hepta-joint-propose --resident-v1` process per worker instance |

Use `worker.profile()` when constructing the corresponding admitted manifest. All existing source, executable, device, component, schema and frozen-weight bindings must still match; changing the profile string alone does not select a different transport or qualify an artifact. The clock must share the existing owner's epoch.

The existing inference/control owner can share an `Arc<JointGenerationProcessWorkerV1>` through `CellGenerationWorkerV2` and its existing controlled generation ports. Sharing applies to the same admitted immutable weights **and public packet**. Different assets require an explicit new worker. There is no product default configuration entry in the current runtime that automatically selects this mode; existing owners must select `open_resident` explicitly.

The helper owns no Cell journal, mutable Cell session, output destination or publication grant. Every request still supplies its complete predecessor state, output prefix, command and request digest. The existing journal alone commits successor state, output, receipts and cost. Agentd retains its Fleet identity, control-file owner, journal and independent witness.

Implementation: [worker API](../../codex-rs/hepta-neuron/src/cell_joint_generation.rs), [resident transport](../../codex-rs/hepta-neuron/src/cell_joint_resident.rs), [helper service](../../codex-rs/hepta-infer-worker-host/src/joint_generation/resident.rs), [numerical proposal adapter](../../codex-rs/hepta-infer-worker-host/src/joint_generation/proposal.rs).

## What is reused

The first dispatched request supplies bounded weights/public bytes. The helper validates canonical packets and the selected numerical profile, then retains the parsed model and public tensors. Subsequent requests omit those assets; replacement assets on an established connection are refused. The deterministic public-input encoding is cached on first use and cloned into each new Cell state. Later transitions never mutate this cache.

The executable remains pinned through the opened file descriptor, with content checks before and after exchanges. The host must keep that artifact immutable in place. This preserves the existing identity boundary and also retains its hashing overhead.

There is no Joint microbatch implementation, new tensor kernel, vectorization claim or automatic pool scheduler in this change. Computation is serialized per shared worker. Existing owner admission and queue limits remain responsible for bounding callers; pipe channels have capacity one and each frame is bounded.

## Concurrency, cancellation and failure

One exchange at a time holds the resident transport. Callers waiting for it check their own cancellation, deadline and clock monotonicity. Checks are repeated after executable hashing/initial packet preparation and immediately before submitting a frame to the writer queue.

- A cancellation/deadline before any frame is submitted returns no new state/output and zero request IPC. It preserves an already healthy shared model. If the child was started but received no initial frame, the next request still sends the initial assets.
- After a frame is submitted, cancellation, deadline, invalid response or uncertain transport failure permanently invalidates that session. There is no automatic respawn or request replay.
- For a submitted frame, a known terminal failure/cancellation requires observing both child termination and completion of its pipe threads within the bounded termination grace. Failure to establish that observation returns an error; the existing owner retains the operation as unknown.
- An invalid request digest, checksum, response length, prefix bound or phase timing cannot become a successor proposal. The session is checked while still exclusively held, before another Cell can submit work.
- Reusing a poisoned session fails. The host must resolve existing owner outcomes and explicitly open a replacement worker. Interrupting the sole active exchange can therefore affect availability for later callers sharing that worker.

The helper's stderr has a lifetime bound. Child custody and reaping reuse the existing process owner. A worker error does not authorize clearing a pending journal admission.

## Cost evidence and its limits

The real-process parity test compares exactly equal successor state, output delta and disposition between single-operation and resident paths. It also checks observed pipe bytes:

- First resident request: single-operation bytes plus **8 bytes**, from the request and response length headers.
- Subsequent resident requests: single-operation bytes minus the exact weights/public packet lengths, plus the same 8 framing bytes.

These are assertions over measured IPC bytes in the tests, not a throughput benchmark. Successful child phases remain disjoint; remaining measured wall time includes transport/control work and shared-worker contention. CPU, energy and unmeasured storage costs remain unknown. Cold loading is incurred by the request that performs it; this does not by itself establish a comparable amortized task or fleet cost.

No latency, throughput, energy or speedup multiple is claimed. Continuous execution benchmarks, cold/warm comparison policy, resident-memory accounting and Joint microbatch/tensor work remain outstanding.

## Reproducible qualification

Use a clean committed checkout with the repository Rust toolchain, `just` and `cargo-nextest` available. The helper must come from Cargo's actual `compiler-artifact` record. Neuron and Agentd accept both `CARGO_BIN_EXE`/`NEXTEST_BIN_EXE` and hyphen/underscore aliases; tests never guess a `target/debug` path.

From the repository root, the focused resident suite can be run as follows. Keep the evidence directory outside the checkout so the helper's clean-source checks remain meaningful.

```bash
resident_evidence="$(mktemp -d "${TMPDIR:-/tmp}/hepta-resident.XXXXXX")"
python3 scripts/hepta_cell_test_helpers.py \
  --package codex-hepta-infer-worker-host \
  --output-dir "$resident_evidence/helpers"
python3 - "$resident_evidence/helpers/env.json" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

environment = os.environ.copy()
environment.update(json.loads(Path(sys.argv[1]).read_text()))
subprocess.run(
    [
        "just", "test", "--locked",
        "-p", "codex-hepta-neuron",
        "-p", "codex-hepta-agentd",
        "-p", "codex-hepta-infer-worker-host",
        "-E", "test(resident)",
        "--test-threads", "2",
    ],
    env=environment,
    check=True,
)
PY
```

Coverage includes helper framing/asset replacement, exact content parity and IPC counts, concurrent Cell isolation, cancellation/deadline before and after dispatch, failed-session refusal, and Agentd's actual control → journal → output acknowledgement → service-reopen path. Fixtures contain fixed legal synthetic tensors; they do not establish learned-model quality or adoption.

For the coordinated package gate and durable evidence, use [run_native.py](run_native.py) with the exact committed `--source-sha` and an external fresh `--output-dir`. It records helper identities, commands and outcomes. The coordinated native gate at `cb6f0a4a180677213988f6a4cc25c8431dfe5805` passed all 959 executed tests in the four scoped packages, including the real resident helper, worker and Agentd service/reopen paths. See [the exact source and raw records](verification.md); this is software-path evidence, not a throughput, energy or trained-model qualification.
