# Actual-checkpoint late-information weight programming

**Status: COMPLETED_WITH_PROTOCOL_DEVIATION. No deployment.**

The source-bound experiment finds a temporal information barrier in three real
SmallHCSN research checkpoints. An explicit new graph connection plus a small
analytic weight program solves a declared wait-then-compare task. Random64 and
four-coordinate BP64 also solve it, and BP has better cross-entropy. Ordinary
RAVDESS retention rejects unconditional use. Rollback must restore the graph
and request route as well as weight bytes; one parent has identical weights
before and after editing but different behavior under the changed graph.

Read [RESEARCH_RESULT.md](RESEARCH_RESULT.md) for exact scope, negative controls,
limits, source hashes and the complete results. The original protocol promised
a full-forward parity gate before fitting; the implementation ran it only after
candidates were sealed. Later parity passes do not fix that chronology. The
immutable [deviation note](PROTOCOL_DEVIATION_01.md) preserves this limitation.

## Evidence and extraction

The 355-file archive contains all actual inputs, predictions, native traces,
candidate and inverse weight files, source seals, objective trajectories and
process receipts. `EVIDENCE_MANIFEST.json` pins every file and all archive
pieces. Chunking keeps individual Git blobs below 450,001 bytes. Pieces are
ordered fragments of one gzip archive, not separate gzip streams.

From this directory, using Python 3.12 or later:

```sh
python3 unpack_evidence.py /absolute/new/path/wsp_evidence
python3 /absolute/new/path/wsp_evidence/neuron_experiments/verify_recorded_results.py
```

The first command refuses to reuse an existing destination and checks all chunk,
compressed-archive, uncompressed-archive and member hashes before extraction.
The second command requires NumPy and checks 21 final metric rows, sealed F32
candidates, balanced quote pairs and exact task-scoped retention. It executes
zero model forwards and zero fits. Original results remain untouched.

The archive layout retains the relative paths expected by the executed scripts:

- `neuron_experiments/`: executed Python sources, protocols, complete outputs,
  frozen native executables and review notes.
- `prior_evidence/nov26/neuron_audit/`: the exact restricted checkpoint decoder,
  three public research checkpoints and the historical TRAIN/DEV/RETAIN caches.
- `prior_evidence/native_mcp/runtime/fullmodel_mcp_qualification_v3/packet/encoded_inputs/`:
  source-bound public research input encoding and reference profile.
- `runtime_source_frozen/`: the native evaluator, trace implementation and small
  standalone research crate, frozen from the matching later binary build.

No pocket4 account, trading dataset, credentials or trader checkpoint is included.
Historical old TEST data is excluded because this experiment never used it.

## Executed source and optional replay

Python used NumPy and SciPy. Native binaries target Linux x86-64. The exact
temporal binary SHA is
`2cf06e6f9974bd77eb5a9c955f90805f04740df72269855af5411d15111305b9`;
the exact bridge/rollback binary SHA is
`825e5200a83a6ff86485bfa161913440d1d3ea25c10cc4377d480c25c2ce660c`.
Both executables are retained. The source snapshot is for the later bridge
binary. Its manifest explicitly records that source freezing occurred after
execution, although the source had not changed since that matching build.
The earlier temporal binary does not have a separately complete build-source
snapshot; retaining the executable preserves its exact replay identity.

The standalone Rust crate builds from `runtime_source_frozen` using Rust 1.95
and its pinned Cargo.lock:

```sh
cargo build --release --locked --manifest-path qualification/weight_trace_runtime_20261128/Cargo.toml
```

Build hashes may vary with compiler/build location. Use the included frozen
executables for exact original artifact identity. The full native command
contract is documented in the frozen crate's README. Inputs and candidates may
be replayed into a **new output filename**; profiles and all source digests must
be supplied, and existing evidence is never overwritten.

For a full reproduction, make a separate new work directory containing the
executed source files and `prior_evidence` subtree but no result directories.
Copy the frozen temporal binary to
`runtime_wsp_audit/qualification/weight_trace_runtime_20261128/target/release/hepta-smallhcsn-trace-research`
in that new directory and run `neuron_experiments/temporal_probe.py`. Replace
only that executable with the frozen bridge binary, then run
`neuron_experiments/late_cue_experiment.py` and `neuron_experiments/graph_rollback.py`.
Scripts refuse to recreate an existing result directory. A replay is a
reproduction on the already known test, not a new holdout or a retroactive
correction of the recorded protocol deviation.

## Source and dataset provenance

Parents: `TrillionniumFoundation/hepta-private-ci` commit
`bc4912ea657864d33b36a57da0b50eb35bee90af`, centered RAVDESS seeds 47/83/137.
Complete parent hashes are in the report and source seals.
Native base: `TrillionniumFoundation/hepta-runtime` commit
`ea22a98ca65be8644923a3d5b57069174384dbc3`, with the explicit research trace and
graph extension preserved in the archive. Its Apache-2.0 license is included.

RAVDESS is the public research dataset by Livingstone and Russo (2018),
https://doi.org/10.5281/zenodo.1188976, distributed under CC BY-NC-SA 4.0.
Only the pre-existing numeric research caches used here are included; the new
late-quote task is synthetic. No result is an estimate of future market utility.
