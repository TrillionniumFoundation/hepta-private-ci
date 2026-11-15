# Four-amplitude Adam and fresh-process restoration intent

New identity: `hcsn-adjoint-four-amplitudes-adam-resume-20261112-c06d-stage1`.
Base is immutable #6248 source `975a169df5f3a1dd51b81ddd51b0a338592a0e0f`.
This stage is INTENT/HOLD until its own exact-source hosted evidence exists.
It does not modify or rerun #6248, and inherits no optimizer/restoration credit.

The four optimized objects are the raw CPU FP64 active probability, signed
content, phase probability and phase signed-content tensors. Physics, actual
uniform N=7 / graded N=12 geometry, query times and phase supports remain fixed.
The probability API is an unnormalized nonnegative finite measure with the
declared ambient linear extension; no normalization or projection is hidden.
All post-update probabilities and all tensors must remain finite and in domain.
There is no model-network/full-prior, migration, support, delay or physics AD.

Each step draws a target from a fixed retained baseline plus small independent
Python, NumPy and Torch noise. All three RNG streams affect actual loss/gradient.
The four raw tensors use one Adam optimizer, lr=1e-4, betas=(.9,.999), eps=1e-8,
weight decay zero, foreach=False and fused=False. One optimizer.step counts as
one actual invocation for this four-tensor group. Invocation counters advance
before the call; completed-update counters are reported separately so a thrown
optimizer call cannot disappear from failure cost accounting. The loss is the mean squared error
of all seven output fields against that target; this is a synthetic numerical
restoration gate and supplies no task-quality improvement claim.

For each geometry, distinct freshly executed Python processes run:

1. Continuous two Adam steps, publishing checkpoints after steps one and two.
2. An independently seeded actor runs step one and publishes its complete state.
3. A new process loads that published step-one checkpoint and runs step two.

Both completed paths evaluate the next loss and gradient without an optimizer
update. This diagnostic consumes RNG in a saved/restored scope and restores
the preceding gradient buffers, leaving the canonical step-two state unchanged.
The next target, output, loss and all four gradients must match exactly.

Every checkpoint contains all four current parameters and gradient buffers,
the complete Adam state_dict and param groups, integer step/cursor, Torch CPU
RNG bytes, Python RNG state and NumPy RNG state (encoded as safe primitives),
original four input tensors, and original actual Q/k/u/r/nodes/d/q/query/support
snapshots. It binds the exact complete source manifest and runtime fingerprint.
No custom class or NumPy object is pickled; loading uses weights_only=True.
Validation of required Adam state/source/runtime/snapshot/cursor occurs before
any resumed forward or optimizer update. No implicit Adam reset is permitted.

Comparison is of the entire logical payload, recursively including tensor
dtype, shape, stride, storage offset and bytes, and all non-tensor metadata.
This is an optimizer boundary with no live autograd graph or DDE dense-history
checkpoint; ephemeral Tensor version counters are not serialized.
Torch ZIP files need not have identical packaging bytes; original file bytes
and hashes are retained independently. All Adam moments and step counters
must be present and restored, rather than just comparing parameters.

Two negative controls use the shared uniform N=7 protocol:

- Omit Adam from an otherwise unchanged valid step-one payload. A fresh actor
  must reject it before any forward/adjoint/optimizer step, with an explicit
  expected rejection result and unchanged input checkpoint bytes.
- Copy the valid step-one checkpoint to a published destination. A fresh actor
  loads it, actually computes Adam step two, writes/fsyncs the complete new
  pending checkpoint, records its work, and exits with os._exit(73) immediately
  before os.replace. The published old checkpoint must remain byte-identical.
  This tests a process crash on the same running OS, not power loss or
  storage-controller directory durability. The pending payload must equal the continuous step-two payload semantically.
  The ordinary fresh resume actor then loads the preserved old published file,
  performs step two and its next-gradient probe, establishing real recovery.

Publication uses a fresh same-directory pending file, fsync, os.replace and a
directory fsync. The crash control bypasses cleanup hooks; it must not be an
assertion-only simulation. The original and pending PT files and all actor
stdout/stderr, arrays, source/runtime bindings and exit identities are retained.

Exact total budget for a complete successful gate: thirteen forwards, thirteen
adjoints and nine real Adam updates. Eight updates are the two continuous and
two split paths; the ninth is the unpublished crash-control step. The two
post-step next-gradient probes per geometry add four forwards/adjoints and
zero updates. The omit-Adam actor contributes zero forwards and zero updates.
Each numerical actor admits at most three forwards/adjoints and two updates;
the controller independently verifies all actor totals. External whole-job
timeout is ten minutes. Stored payload and post-solve step checks are not hard
process-RSS or solver-time bounds. No earlier run/key is reused.

Source, SPEC, REQUEST and a complete source digest inventory must be remotely
frozen and independently reviewed before the one new hosted admission. Any
RED or interrupted job remains an independent immutable attempt; no outcomes
are manufactured by omitting Adam, skipping failure paths or changing identity.

Even a PASS qualifies only these four initial tensors, fixed small models,
same exact runtime/source, Adam settings and tested process/publication boundary.
It grants no large-grid, cross-runtime, full-network, historical-training,
full-prior/migration or model-adoption qualification. Global HCSN remains HOLD.

Before Popen, every controller admission is persisted as STARTING with an
UNKNOWN launch effect, a nonce and reserved maximum work. A returned PID
updates that intent to SPAWNED. An unresolved STARTING intent has unknown
work even if its PID was never recorded. Only a definite prelaunch failure
or a reported Popen spawn exception is marked terminal with no child and
zero known calls. Every spawned actor retains its PID, started/terminal
state and actual exit code. A missing, malformed or
unbound actor RESULT leaves its cost UNKNOWN and stops further admissions.
In that case exact total actual_calls is null; only separately labeled
observed totals and the unknown actor bounds are reported. No unreported
actor is counted as zero. This is a controlled generated-fixture schema,
not hostile-checkpoint validation or dependency-binary attestation.
