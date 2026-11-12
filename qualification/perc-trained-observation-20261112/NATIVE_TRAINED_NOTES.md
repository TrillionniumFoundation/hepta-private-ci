# Actual trained acquisition MLP in the native Cell owner

**Engineering result: PASS. Scientific status: HOLD.** The CORD pilot's actual
trained `perc1.acquisition-mlp-head.v1` has executed as Rust FP64 arithmetic inside
`NeuronInferenceControlPort`, through the original `prepare_cell_step` →
`infer_cell_with_clock` → `decide_cell` → `commit_cell_step` path and
`CellOwnerJournalV1`. This is a new trained-head mechanism result beyond the
already executed diagnostic Q24 head in #6072.

The native verification reuses CORD TRAIN row 0. It does not change the completed
Python actor experiment, produce new confirmation tasks, establish task benefit,
exercise ParameterV3, or enroll a profile in ordinary daemon startup.

## What actually executed

The retained CORD head has a 73 → 8 → 2 tanh architecture, 200 optimizer steps,
TRAIN normalization, and the original DEV bias. Its exact raw-byte SHA-256 is
`2a7aa2549d8102fc033e5026b959c804d07ad5f1ae41a0d5d887bffc66668f5e`.
The Rust control computes normalization, both matrix products, tanh, output bias,
gain clipping, cost scaling, and net acquisition value. It receives no externally
computed prediction.

The executed outer qualifier verifies frozen `ACTOR_DONE` artifact hashes and
`PLAN` source pins. It checks the operator source configuration, source catalog,
projection, original document bytes, and original owner binding. It cold reads
the `initial` source receipt, validates the producer wire, reconstructs the
profiled latent prefix and actor OCR, and calls the original candidate builder.
Every resulting feature object must equal its retained TRAIN pair. Only public
features from the TRAIN pairs are used; confirmation labels are not opened.

Three candidates produced 73 FP64 features each. Native output differed from the
NumPy reference by at most **6.661338147750939e-16** in absolute raw-output value.
The frozen Python acquisition policy, Rust FP64 policy, and committed Cell
decision all selected `lower`.

Five separate native processes exercised normal execution, a committed cold
read, simulated lost acknowledgement after real inference, original-result
recovery, and a second committed cold read. They performed **2 actual native MLP
invocations (3 candidate forwards each), 1 original inference readback, and 2 cold replays**. Recovery did not
run the MLP again. The first qualification recorded 427,874,000 ns of driver-body
wall time; the final formatted-source qualification recorded 793,392,176 ns.
These timers start after Python imports, so they exclude interpreter/import setup
and build costs. Subprocess measurements are nested and must not be added to the
driver-body totals. Both runs reused the same TRAIN source; they represent 4
native invocations and 12 candidate forwards across one distinct source, with no
new physical capture callback or independent confirmation.

## Compatibility encoding and selection

The original Cell feature transport accepts at most 512 bounded Q24 scalars.
The unmodified acquisition recipe includes values such as `log1p(4,000,000)`, so
it cannot be passed as raw numeric Q24 without changing the feature contract.

The explicit `perc1.fp64-u22-dictionary-carrier.v1` codec deduplicates IEEE754 bit
patterns and carries each unique value as two 22-bit limbs and one 20-bit limb,
followed by row indices. The real three-candidate case used **432 scalars**. The
codec preserves FP64 values exactly, including the original log-budget feature;
decode must re-encode to the identical canonical carrier. Oversized carriers are
rejected without clipping, substitution, or relaxing the framework limit.

The carrier's numerical Q24 values are transport containers, not latent
magnitudes. The native model reconstructs their FP64 bit patterns before doing
inference. Source, recipe, raw and canonical head, carrier, and decoded feature
digests are bound into the original request/owner chain.

`perc1.fp64-budget-threshold-ordinal-drive.v1` converts the computed FP64 policy
to bounded positive ordinals after checking the budget mask and exact
`net > threshold` condition. This preserves positive margins smaller than half a
Q24 unit and preserves ordering of near-equal FP64 scores. Exact ties retain the
input candidate order, matching `acquisition.choose` and the original Cell's
tie handling. The ordinals are explicitly not logits or calibrated utility.

The prediction channel stores a SHA-256 commitment of the original FP64 output
bits. It is not a learned residual prediction. The ordinary native
`model_output_digest` commits the drive, that bit commitment, and the runtime
receipt. Rewriting an output receipt and its local sidecar cannot replace a
completed journal commitment.

## Build and regression evidence

All three frozen builds verified 115 Rust source files from the exact a558 tree in
`hepta-types`, `hepta-infer-core`, and `hepta-neuron`. No implementation in those
libraries changed. New source modules, copied build sources, builder bytes, and
standalone manifests were frozen and checked before/after compilation.

Build 005 adds hosted-friendly `--source-ref` and `--online` options. It produces
the **identical binary bytes** tested in build 004:
`ccb25bd316e48ee6b2120e8b81c0304231b4a785437d568f5e49e113eb9ce7d8`.
The 11 native contracts passed with zero skips in 1.386 seconds. They cover actual
synthetic optimizer training, FP64 parity, visual-feature-induced ACQUIRE/STOP,
lossless dense input, original capacity refusal, exact/near ties, tiny positive
margins, budget masks, lost acknowledgement, cold replay, and tamper refusal.

Repository `just fmt` subsequently expanded/reordered only `use` declarations in
three Rust files. The final published bytes were frozen and compiled as build
006, producing a different binary hash:
`a8c9afb739a9bcf603d4f6096cbb8f7a89269e19edc9b9b0968870f2d09a2f8c`.
That final binary passed a second actual CORD TRAIN numeric/Cell/durability
qualification, with the same maximum error and the same `lower` selection.
The 11 local unit contracts were not repeated after formatting, as instructed by
`AGENTS.md`; they remain explicitly attributed to build 004/005. The workflow's
final-head native build and full unittest gate are tracked separately. No local
claim here substitutes for that hosted final-head result.

An early builder sampled stage-source hashes after copying sources. That had a
race risk if files changed during compilation. The original early records remain
retained, and retrospective comparison found zero actual copied-source/hash
mismatches. Builds 004–006 remove that risk and retain independent binary copies.

For hosted execution, build **before** the workflow's PERC unittest discovery:

```bash
python scripts/perc1_trained_native.py \
  --repo "$GITHUB_WORKSPACE" \
  --build-dir "$PERC_CI_PRIVATE/trained-native-build" \
  --cargo "$(command -v cargo)" \
  --rustc "$(command -v rustc)" \
  --source-ref "$SOURCE_SHA" --online
```

Set `PERC1_TRAINED_NATIVE_BINARY` to
`$PERC_CI_PRIVATE/trained-native-build/perc1-trained-native` for subsequent steps.
With the existing `PYTHONPATH=scripts`, full `test_perc1*.py` discovery includes
`test_perc1_trained_native`. That module intentionally fails when the required
native binary is absent, rather than silently skipping the native gate.

## Remaining scope limits

The ordinary owner/inference APIs are real, while the host is a standalone
qualification executable. The source encoder in this executable is a lossless
feature carrier; source-image/OCR/wire-to-feature reconstruction occurs in the
executed, frozen Python qualifier. The raw native CLI checks provenance bindings
but cannot authenticate arbitrary caller-supplied hashes without that outer
source-verification chain.

The Cell calibration/OOD profile remains a hand-authored permissive qualification
fixture. It grants no authority and supplies no empirical calibration evidence.
The witness and receipts are local to the same principal, not an independent
attestation service. Memory fields describe retained/parameter bytes and a bounded
scratch estimate, not measured RSS; energy and provider billing remain unknown.

All real source evidence here belongs to an already used, pre-plan exposed TRAIN
source. Fresh independent confirmation remains **0**. The completed pilot's
terminal-task result and its negative comparison against strong controls remain
unchanged.
