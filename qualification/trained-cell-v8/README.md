# V8 full-state research admission and bounded numerical parity

This change closes the interface between a future frozen research evaluation,
the complete optimizer/controller payload, and the existing immutable research
artifact owner. It does not install a scientific profile, accept an actual V8
candidate, grant production authority, or activate an Agentd selector.

The previous frozen implementation is commit
`d2f8a56c5219718f1841b4e9f92d2ad6dbb8fd49`. Its historical worktree, numerical
results and V5/V6 scientific rejections remain unchanged. Shared files in this
new branch receive explicit version dispatch; the old V7 wire decoder and its
historical whole-file parity limits remain supported as V7 only.

## What is new

`admission-driver` accepts a host-installed profile and its independently
configured SHA256. One parser handles different registered policy censuses
without copying a new version-specific scientific parser. The scientific family
is fixed to AG News and DBpedia, linear and gated heads, seeds 7/17/29, and 32
actual Adam steps. Every required candidate/baseline execution must complete.
All twelve scientific comparisons and all four CPU comparisons are required:
future loss upper bound is strictly below −0.001, old loss upper bound is at
most zero, and total measured CPU ratio is at most three. Missing comparisons,
duplicate execution keys, incomplete required runs, nonfinite measurements and
failed gates cannot prepare a signing proposal.

The profile pins protocol bytes, executed source, runtime, source datasets, run
seal, full controller contracts, reviewer public key and numerical parity header.
The invocation's expected profile digest is trusted host configuration. Passing
a candidate-supplied digest as that argument would abandon this trust boundary.
There is no default profile, file discovery, embedded scientific approval key or
automatic profile installation.

`TrainingHandoffBundleV8` uses `HPTHOF08` and distinct compatibility identity.
It retains the actual V8 controller bytes and the complete θ/m/v, PCG64 state,
optimizer clock, sampler counters, contexts and original warmup identities.
The V8 source contract is explicit:

- `hepta.cell-field-controller.v8` and `hepta.cell-field-controller-contract.v8`;
- exactly 32 registered steps, zero relinearizations, stride 1/2/4/8;
- `risk_effort_box_v8` proposal and `single_ray_then_joint_v8` safety filter;
- full forecast action bytes and digest, separately certified installed prefix,
  original anchors/panels, prefix cursor, receipts and cumulative counters;
- no safety claim for an uncommitted forecast tail, no authority, and no restart
  of a stopped attempt outside its frozen budget.

H1 forecasts and commits one step. Other policies forecast up to eight steps,
install only the configured certified prefix and discard the forecast tail when
replanning. The first filter tries the entire single-ray block; only failure
allows the entire joint filter from the same state and intended block. Native
transport authenticates these identities and structural invariants. It does not
execute that safety algorithm or establish independent held-out retention.
The pinned research loader and independent replay audit own those claims.

## Full-stream numerical parity

V8 uses separate `parity-header.json` and `manifest.json` files. The host profile
pins the header before scientific evaluation. Its full vector/reference stream
hashes, source and head identities, exact row census and framing are immutable.
The later conversion manifest can bind evaluation-specific terminal evidence
without creating a circular pre-evaluation commitment.

The reader supports two task streams of up to 65,536 rows each. It checks exact
regular-file lengths and complete SHA256 identities, then evaluates every row
for every registered head in both parameter versions. Buffers hold at most
1,024 raw rows (3,145,728 bytes) and their references (65,536 bytes). Stream files
are bounded by 1 GiB; metadata is bounded separately. The reader rehashes each
case's consumed bytes during inference, so a change after preflight cannot
silently substitute data. No rows are sampled. Numerical checks cover four
logits, four probabilities, all four possible class NLLs and first-tie argmax;
the streams contain no labels. Absolute numeric tolerance remains `1e-12`.

The inherited signed owner path now dispatches V8 streams explicitly. Both the
initial report adapter and the later prepare/execute path compare the actual
parity manifest with the exact audited conversion bytes. V8 streams cannot be
used to publish a V7 or legacy serving-only payload.

## Host interface and trust boundary

Build the isolated `qualification/trained-cell-v8/admission-driver/Cargo.toml`.
Its CLI accepts:

```text
MODE PROFILE HOST_PROFILE_SHA PROTOCOL EVALUATION GATE
PREDECESSOR_HANDOFF CANDIDATE_HANDOFF CONVERSION_MANIFEST CONTRACTS
[REPLAY_AUDIT STATISTICS_AUDIT] OUTPUT [SIGNATURE]
```

`reject` validates the bound source/evidence/payload family and emits a rejection
without opening an owner or creating a proposal. Structurally invalid payloads
fail even earlier as format/binding errors; this must not be reported as an
executed numerical scientific gate. A stopped controller is one such rejected
transport state.

`prepare` is available only after every scientific, census and completion gate
passes, both independent audit envelopes bind the same evidence, every candidate
cell is the exact evaluated terminal-32 checkpoint with no pending suffix, and
full numerical parity passes. It creates a new research owner containing only
the immutable predecessor and writes the exact native review signing bytes.

An independent local research signer must inspect or recompute the detailed
replay/statistics evidence before signing those bytes. The signature receipt is
`{"proposal_sha256":"...","signature_hex":"..."}`. The private key never
enters this program or repository. `execute` verifies the external pinned key,
900-second validity, exact proposal/request identity and all bound inputs again
before candidate publication. It then reopens the real owner, selects/serves the
typed checkpoint under per-use admission, and verifies explicit predecessor
rollback without rewriting immutable history. Exact retry reconstructs the
original request; changed operations and partial/divergent histories fail closed.

Native code checks the complete comparison family, reported bounds, thresholds,
completion and independently recomputed CPU ratios. It does **not** independently
redo bootstrap statistics or prove dataset independence. Audit-envelope claims
are commitments verified by the external research reviewer. This is local
research trust, not external certification or production approval.

## Evidence required for a genuine positive publication

A future actual candidate still needs a separately frozen, eligible confirmation
protocol; all twelve complete candidate cells; complete source/runtime/dataset
and predecessor identities; all scientific and cost gates passing; independent
full replay and statistics audit receipts; exact terminal-state conversion and
full-stream parity; an explicitly installed host profile; and an external
reviewer signature over that exact proposal. A development fallback, failed
scientific candidate, synthetic passing metrics or a native mechanics fixture
cannot satisfy these obligations.

No current actual candidate is approved by this change. Positive owner fixtures
use clearly synthetic evidence and a fixture reviewer solely to exercise the
existing publication, crash/recovery, reopen and rollback implementation.

## Qualification and scope

`streaming-qualification.json` records a synthetic stream with 67,584,000 raw
vector bytes, one task above the old 16,384-row limit, and 264,000 actual native
predictions across both twelve-head versions. It retains all case counts/hashes,
numeric errors and tail-byte, self-rehashed wrong-tail and truncation rejections.
Regenerable sparse raw streams are removed after the passing test.

`qualify_handoff_profile.py` runs the actual pinned research code over small
synthetic numerical data. Both head modes and all four strides are checked at
steps 0/17/32 through Python → HPTHOF08 → Rust → the original V8 loader. Every
step-17 continuation compares physical actions, receipts, terminal state and
receipt chain. New verification time and cost ledgers are charged separately,
and are not claimed byte-identical to the original controller runtime counters.

The final qualification receipt identifies exact commands, source hashes,
toolchain, test runs, failed ENOSPC attempts and final passing evidence. Tests
run through `just test`, followed by scoped `just fix` and `just fmt` as required
by `AGENTS.md`. This is an isolated source-closure qualification of the actual
neuron/owner crates, not a full repository, Bazel, Agentd or production rollout
qualification. No CI polling or merge is part of this work.
