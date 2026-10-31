# Native Hepta content and streaming research backend

This executable runs the complete small `JointGenerator` inference computation
in Rust: image/audio/video/token encoders, shared fusion and initial slots,
all configured recurrent Hepta layers, modality adapters, all four output
heads, actor, continuation critic and delivery critic. Python exports selected
weights and conducts an independent differential comparison. No Python/Torch
process is called by the executable.

The backend is an additive **Linux research implementation**. It does not
modify the original Rust neuron owner, V1/V2 profiles, wire formats or gates.
It does not implement training, open-domain text/audio/video generation or a
general NDU solver. The native policy uses the trained actor; it does not
replace the actor with a digest/constant diagnostic head.

## Reviewable implementation stages

1. `codec.rs`, `math.rs`, `model.rs`, `state.rs`: bounded, checksummed export,
   complete FP64 forward inference and a named state format. These can be
   reviewed and qualified independently of any durable streaming adoption.
2. `stream.rs`, `main.rs`: actual prefix commits, immutable chunk records,
   compare-and-swap admission, recovery and native media encoding. This adds a
   distinct streaming contract around the already qualified content backend.
3. `../native_bridge.py`, `../test_native_bridge.py`: weight export, actual
   subprocess execution, original Torch differential references and fault tests.

The multi-module change is larger than the repository's routine change-size
target because both the tensor kernel and a new durable output format need
independent implementations. Each module remains under 500 lines. No Cargo
dependency or production workspace manifest is changed.

## Numeric and randomness contracts

The mathematical structure and tensor shapes match the pinned parent model.
Actual float32 weights are promoted exactly to FP64 for native inference.
Differential evidence compares against both original Torch `double()` and
original float32 computation, separately. This is a new numeric profile;
bitwise equivalence to a float32 accelerator is not claimed.

The first-passage operator retains the original approximation: frozen
coefficients over each 0.5 interval, killed first moment, interval-end reset
and recursive mean propagation. It has no continuous renewal, refractory
clock, sampled neuronal spikes or task-value neuronal free boundary.

Two delivery laws are explicit:

- `mean`: sigmoid/tanh of media means and categorical argmax. This is a
  deterministic deployment law, not the original stochastic training law.
- `splitmix-normal-v1`: counter-indexed SplitMix64 uniforms and Box-Muller
  Gaussian media noise with sigma 0.035, plus categorical label sampling.
  It preserves the declared Gaussian/categorical distributional construction,
  not Torch's PRNG bit stream. Given one content state, seed and absolute output
  position, sampling is independent of how the stream is divided into chunks.

The random key also binds the full state's step count and modality. A verify
or STOP transition advances that count even when emission means do not change;
uncommitted positions can therefore use a fresh random key after either action.
Chunk-partition invariance is conditional on an unchanged complete state. This
is an explicit native delivery profile, not equivalence to Torch final-bundle
sampling or proof of equivalence between streaming and buffered utilities.

The model package binds `allow_initial_stop` and
`suppress_redundant_verify`. The second option only applies to the same fixed
public observation and unchanged content. A newly arriving observation requires
a new input/version contract. It is not silently treated as already verified.

## State, commits and recovery

Each journal record includes complete context, shared and modality states,
all content/voltage/adaptation/event tensors, feedback, step/STOP/verification
state, weight and public-input identities, sampler/seed, per-modality cursors,
and every already committed output byte. The record is checksummed, linked to
its predecessor and written through a synchronized temporary file and atomic
no-replace hard link. The event directory is synchronized before success.

Every mutating command requires the exact expected predecessor. Linux `flock`
provides process ownership and is released by the operating system on exit or
crash. Immutable content-addressed chunk bytes are synchronized before their
journal commit. A crash before journal publication leaves an uncommitted chunk;
recovery does not advance its output cursor. A crash after publication recovers
the committed successor and rejects a retry with the old predecessor.

Recovery runs in a genuinely new native process. It verifies both SHA-256 and
the full semantic transition sequence by independently replaying the selected
model from its pinned input. Missing/reordered records, changed weights,
changed input and modified committed chunks fail. Trailing uncommitted temporary
files are ignored. Hashes provide identity/integrity, not external authentication
or a production anti-rollback witness; deleting a whole suffix cannot be detected
without an independently retained expected head. Callers must retain that head
when rollback detection is required.

The test supplies a caller-retained witness. No automatic external witness
service or separately durable witness store is implemented. A Python object's
`head`, or a copy stored only beside the journal, does not independently survive
all session-storage loss. Tests inject native process exits; they do not simulate
power loss, filesystem/controller failure or distributed storage behavior.

Commit units are image rows (16), PCM samples (1024), video frames (4), and the
two text fields. Already committed bytes cannot be overwritten by later content
updates. STOP prevents further content transitions but permits pending prefix
completion from the fixed stopped state. Complete output export requires STOP
and all four completed prefixes.
PNG, PCM WAV, timed GIF and UTF-8 are encoded by Rust and independently reopened
by Pillow/wave in the tests. GIF has an exact per-frame palette for this 16x16
profile; it is not a high-resolution video codec implementation.

The trained actor does not yet receive committed-prefix features. Therefore
this work qualifies actual generation and immutable streaming/recovery, **not
an optimally trained streaming policy or cross-modal coherence after partial
delivery**. Joint utility of streamed mixtures requires its own training and
outcome evaluation.

## Build and execution

No dependency download is needed. Use a verified installed Rust compiler:

```bash
rustc --edition=2024 -O -C target-cpu=generic main.rs -o /tmp/hepta-native
```

The Python `build_native` helper records compiler/version, source digests,
command and binary hash. The packet exporter accepts only the fixed model
tensor inventory and one public input; target labels never enter the model.
The source tests invoke the complete original Torch model as the independent
reference, with actual parameter updates before export.

```text
native init    WEIGHTS PUBLIC SESSION SEED SAMPLER
native inspect WEIGHTS PUBLIC SESSION OUTPUT_PACKET REMAINING_FRACTION
native step    WEIGHTS PUBLIC SESSION EXPECTED_HEAD ACTION
native auto    WEIGHTS PUBLIC SESSION EXPECTED_HEAD REMAINING_FRACTION
native commit  WEIGHTS PUBLIC SESSION EXPECTED_HEAD MODALITY COUNT
native status  WEIGHTS PUBLIC SESSION [EXPECTED_HEAD]
native export  WEIGHTS PUBLIC SESSION OUTPUT_DIRECTORY AUDIO_RATE FRAME_MS
```

Fault-test-only commit arguments `after_chunk` and `after_event` cause genuine
native process exit at the named persistence boundary. They are never enabled
implicitly. An acknowledged head must be retained outside the session for
independent rollback detection. Prefix bytes become committed when their event
is published; external transport acknowledgment is a separate future boundary.

Every command currently reloads weights and replays the full bounded journal.
This intentionally exercises independent-process recovery. Python records the
whole child CPU/wall time, including these costs. It does not demonstrate
faster serving than Torch or favorable total lifecycle economics. A resident
native service and its cache/owner lifecycle need separate implementation and
measurement.

## Evidence scope

The final nine-test integration run passed all declared tests in 15.528 seconds
(`evidence/UNIT_TESTS.log`), including
five mode/boundary/depth combinations with genuinely updated weights, complete
state/head differential checks, native action execution, initial STOP,
immutable partial output through later content changes, new-process restore,
actual codec readback, two crash points, stale CAS, live-writer exclusion,
weight/chunk corruption, sampler chunk-partition invariance, and whole-suffix
loss detected using a separately retained predecessor witness. The ninth test
checks the V3 repeated-verification mask against original Torch: committing a
prefix does not invalidate verification, while an actual content revision does.

`evidence/BOOTSTRAP_DIFFERENTIAL.json` preserves the first untrained
width-8/depth-2 development comparison. Its purpose is numerical debugging,
not a trained efficacy result. The separate nine-test run performs real
supervised updates before comparing five architectures. The final trained
checkpoint qualification below is separate from this bootstrap fixture.

`evidence/pilot_trained_20261031/` qualifies the actual 596,985-parameter
seed-17/width-32/`dual.joint.dynamic` checkpoint from the interrupted pilot
matrix. Its checkpoint SHA-256 is
`92b9ed2953a027b5eb8524371a06be8b73c45d0e36af29246792480299589e3e`.
All state/head errors were at most `4.44e-15` against original Torch FP64 and
`8.21e-7` against original Torch FP32. Native trained actor dispatch agreed
with the original model's initial STOP decision. A separate forced content
trajectory preserved partial prefixes through later revisions and recovered
them in fresh native processes; all four independently decoded final media
matched the committed bytes. This is engineering evidence for an explicitly
superseded pilot checkpoint, not the final frozen experiment or an efficacy
result.

### Final frozen trained checkpoint

`evidence/frozen_trained_20261031/` is the separate completed qualification
of the final frozen matrix's seed-17/width-32/`dual.joint.dynamic` checkpoint.
The selected file and report independently agree on SHA-256
`9032b0750ea07c9ad5f9d0fb657d0ce16fd67ccacde1a653908207cbfdb542dc`.
The frozen top-level V3 source manifest was rechecked and still matched after
this run.

| Check | Observed result |
| --- | --- |
| Actual trained parameters | 596,985 |
| Complete state/head maximum absolute error, Torch FP64 | 3.997e-15; tolerance 1e-9 |
| Complete state/head maximum absolute error, Torch FP32 | 7.703e-7; tolerance 5e-5 |
| Trained native actor decision | Initial STOP; agrees with original Torch |
| Forced content/stream trajectory | All six named actions, then STOP; original committed prefixes preserved |
| Independent PNG/WAV/GIF/UTF-8 readback | All decoded bytes equal the committed prefixes |
| Stream commands, each a new native process | 22; 2.3625 CPU seconds / 2.4097 wall seconds |
| Whole qualification process | 10.3869 CPU seconds / 7.3581 wall seconds |

The whole-process measure includes Python/Torch imports, Rust compilation,
independent reference computation, native execution and evidence writes. The
standard-library outer launcher's own startup/report assembly is explicitly
excluded. `PROCESS.json` records that scope, return code and source hashes;
`RESULTS.json` records each native call's full cost, compiler/binary identity,
tensor-by-tensor errors, exact trained actor dispatch and final media hashes.
These measurements do not compare serving efficiency with Torch. The forced
stream trajectory is an implementation test, not the selected actor's rollout.

The native binary SHA-256 is
`c0bdd8732fb582347cda08e0dc23bffb63dd52231f0f82a9622472280fe54bab`.
Its complete final streamed journal head is
`0baf7bcf067c411fb8ed5439b6b837ff265050f1475313562c1dfc78e6a1227b`.
The evidence retains the full native event/chunk chain, exact public input and
all delivered media. Reconstruct weights from the named training checkpoint
using the packet exporter; the evidence avoids duplicating the FP64 weights.

Reproduce with the fixed checkpoint and a new evidence directory:

```bash
python -B -m experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.native_generation.qualify_external \
  --checkpoint experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/evidence/matrix_frozen_20261030/seed-17-width-32/dual.joint.dynamic/MODEL.pt \
  --output /tmp/hepta-native-new-qualification \
  --rustc /absolute/path/to/rustc
```

This establishes genuine Rust content execution and the declared local prefix
contract. [INTEGRATION.md](INTEGRATION.md) records the remaining production owner
adoption and learned-streaming boundaries with exact inspected callsites.
