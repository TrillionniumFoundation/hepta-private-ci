# Historical trained Joint replay qualification

The unchanged proposal entry from PR #4929 loads and executes a real historical
trained Joint descendant. The accepted run is `replay-r3`: **48 native child
processes, 40 successful proposals, eight intentional rejections, and 64 passing
checks**. This qualifies the numerical helper and its request/response ABI with
trained weights. Agentd ownership, cancellation and durable adoption are separate
gates.

## Asset and source identity

| Item | Pinned identity |
| --- | --- |
| Helper source | `7391c3dc3b0a496b62be4c6cf2769d2ae0c9db75` |
| Historical model/export source | `18dac3ccd30317893ad922792c12400390522f00` |
| Recovered `adapter.pt` | `33c1aa759bddb5e9b33b906e1796de7a6f89e5b5916711f99033584b3cbafb97` |
| Native `weights.hps` | `41ce6de8a9095e1ef6b8756c3117a160ed40acfad8b297390de95083664d223e` |
| Native `public.hps` | `86c55417fdf2abdd065fc9828c40260aed0ded4a0d607c551e15b2f6b5fd2c00` |
| Executed helper | `a400ef5dabddc44e2290d7abf6136ae492355dab059d99f580c4d5de9ba40253` |

The checkpoint comes from the published, chunked
`v3/packaging/bundles/open_text_final_20261030` archive under the historical
experiment root. Its verified historical receipts record 16 optimizer updates.
The complete Joint state contains 67 tensors and 596,985 parameters. The prior
recovery stage used `torch.load(weights_only=True)`, strict state loading and the
unchanged historical exporter; the complete Joint tensor digest remained
unchanged after export. This qualification verifies and consumes those exact
checkpoint, packet and provenance bytes and performs **zero new training
updates**. The helper consumes the native packet, not the PyTorch container.

The original selected parent checkpoint has SHA256
`9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc`.
Its bytes were not recovered by this work. The descendant's relation to that
parent is recorded in the historical training receipt; this is not a claim that
both checkpoints are interchangeable. Optimizer resume and the separately
trained prefix/frozen language model path are not qualified.

`TRAINED-DESCENDANT.json` pins all asset and provenance files. The copied
`trained_asset_provenance` records retain the full historical manifest, protocol,
report, export receipt and recovery receipt. `recovery-source.py.txt` is the
recovery implementation snapshot; the replay harness does not execute it.

The input is historical mechanism sample `[3]` from
`v3-native-implementation`. It is synthetic task input. Real trained parameter
provenance does not convert this sample into natural language/image/audio/video
evidence. The emitted text is the symbolic `action=1;sound=2` record, not an
open-domain language result.

## What the accepted run checks

The same seed (`17`) and explicit action sequence are run twice for each of the
mean and SplitMix samplers:

1. Initialize, then refine the shared state.
2. Commit 16 audio units as an irreversible prefix.
3. Refine image, audio, video and text state, then verify.
4. Stop and flush the remaining output.

Every continuation uses state and prefix bytes reloaded from a completed
predecessor on disk in a fresh helper process. State, emitted prefix and stopped
status must be byte-identical between repeats. Timing fields are retained in raw
responses but excluded from deterministic numerical equality. The harness
validates checksums, the echoed request identity, frame boundaries, contiguous
modality cursors and final output completeness after every proposal.

Both samplers additionally reject continuation after stop, altered committed
prefix bytes, altered weight packets and altered public packets. Repeated Auto
calls from the same initialized state exercise the trained actor/critic path and
must return identical numerical results. The generated media differ between the
two sampler modes. Exact before/after hashes confirm that input assets and the
executable did not change.

The fresh-process reload checks do not establish fsync durability, recovery after
host failure, owner-adoption atomicity, or cancellation while an Agentd request
is in flight. Those require the existing lifecycle qualification to be rerun
with this pinned descendant. This run also does not establish quality gains,
cross-platform bitwise equivalence, or equivalence to an independent PyTorch
numerical oracle.

## Costs and evidence

The accepted replay took **8.814469289 s** of harness wall time, **6.638179 s** of
child CPU and **2.199150271 s** of harness CPU. Provenance setup is separately
recorded: 0.044154474 s wall, 0.026779 s child CPU, 0.017851643 s harness CPU. The
48 calls transferred **233,992,288 bytes** across stdin/stdout/stderr, including
repeated full weight packets. These are qualification-run measurements, not a
steady-state service benchmark.

The final standalone helper build took 2.443582152 s wall and 6.120445 s child CPU.
`HELPER_BUILD.json` records the compiler, build command, executable, nine exact committed
Rust source files and the hashes of linked native libraries. Build-r2 and
build-r3 produce the same executable digest. No Cargo, Bazel, full-crate or full
workspace gate was run by this qualification.

`evidence/trained-descendant-20261106/INDEX.json` preserves the costs of both
recorded builds and all three recorded replay runs, including development runs.
The initial exploratory compilation and earlier inspections were not
instrumented, so the index is not a complete task-cost total. Energy, physical
disk traffic, isolated per-helper peak RSS, historical training cost and Agentd
cost remain unmeasured. The `RUSAGE_CHILDREN` RSS high-water field covers all
harness children, including source-provenance Git reads; it must not be presented
as isolated helper memory.

The evidence archive retains every raw response, stderr stream, successor state,
committed prefix, emitted modality payload, step receipt, build receipt and the
accepted harness source. Its `FILE-INDEX.json` binds each archived file's size and
SHA256. The readable accepted `RESULTS.json` and `HELPER_BUILD.json` are also present
alongside the archive. Whole-call wall time already encloses the child's disjoint
codec/encoder/inference/planning phases; adding both would double count.

## Reproduction

From the repository root, build the unchanged std-only helper with the explicit
Linux Rust compiler whose identity should be recorded for the new run:

```sh
python3 qualification/neuron-generation-bridge/build_replay_helper.py \
  --source-root . \
  --rustc /absolute/path/to/rustc \
  --output /absolute/path/to/new-build
```

Supply the exact recovered checkpoint and native export paths to the replay:

```sh
python3 qualification/neuron-generation-bridge/trained_replay.py \
  --source-root . \
  --executable /absolute/path/to/new-build/hepta-joint-propose \
  --build-receipt /absolute/path/to/new-build/BUILD.json \
  --checkpoint /absolute/path/to/adapter.pt \
  --weights /absolute/path/to/export/weights.hps \
  --public /absolute/path/to/export/public.hps \
  --manifest qualification/neuron-generation-bridge/TRAINED-DESCENDANT.json \
  --output /absolute/path/to/new-replay
```

Output directories must be new. The harness checks committed source, matching
build receipts, executable/library identity, exact pinned assets and the saved
provenance before executing the action sequences. It uses only Python's standard
library and the already exported historical artifacts.
