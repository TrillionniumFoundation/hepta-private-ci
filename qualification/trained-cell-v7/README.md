# V7 complete checkpoint handoff and exact owner recovery

This additive qualification is based on native PR #3909 at
`63ac6dc8a11bd467f8798db172d563e124d8e939`. It adds a bounded, typed transport for
the complete research training state and a frozen controller plan, then uses the
existing immutable artifact owner, signed scientific review, selector and
snapshot lifecycle. It installs **no genuine V7 scientific acceptance profile**.
V5/V6 rejected scientific evidence is unchanged. Current V7 development uses
historically disclosed labels and cannot obtain scientific or production
authority through this work.

## What the implementation closes

The V5 typed payload preserved serving parameters. The new `HPTHOF07` envelope
also carries the exact optimizer metadata and theta/m/v, PCG64 RNG state, sampler
and external-batch counters, clock and context identities. Every serving theta
bit is checked against its complete state. It retains the original canonical
controller snapshot, immutable warmup and panel anchors, source/configuration
commitments, full resolved plan, cursor, cumulative receipts and counters. A
step17 H8 checkpoint therefore retains the seven remaining actions of the
verified block that began at16.

The outer controller protocol identifies V7 policy semantics. The unchanged
optimizer metadata separately identifies the historical warmup protocol. The
controller code identity is SHA256 of the canonical source filename-to-hash map;
the raw source-map file hash is reported separately. The adapter verifies both
original optimizer source files and every frozen controller source/config file
before loading the actual research implementations.

The native decoder requires an externally supplied envelope digest, checks it
before decoding, bounds all metadata/tensors and rejects trailing bytes. Its
compatibility digest differs from the V5 serving format. Controller wrappers and
original snapshots must agree on clock, cursor, origin, protocol and action
commitments. The Python adapter then uses the existing `CellTrainingState`
save/load and actual `load_snapshot` contract checks. Native transport validation
does not substitute for that pinned host loader. Interrupted inner optimization
is discarded; only committed state plus a frozen verified plan can resume.

Exact-request recovery reconstructs the original baseline registry in memory.
It never derives a new publication request from a registry whose CURRENT may
already contain the candidate. Only the exact signed baseline/candidate
histories and original operation are accepted. External research signatures and
their time window are checked before opening the prepared owner. Altered
payloads, audit evidence or proposals cannot borrow an unfinished operation.

Positive V7 admission additionally requires every cell to be completed at the
exact registered step32, with no pending actions, a completed original controller,
an empty failure ledger and matching committed/receipt counters. The exact
per-cell state, controller, receipt and plan commitments are derived from the
decoded payload and compared to the reviewed conversion map and both independent
audit commitments. That map binds the protocol, report, source candidate bundle
and native candidate bytes. These checks precede any owner write. A valid mid17
transport cannot use terminal32 science, and self-consistently rehashing an
incorrect expected terminal-state map does not evade the comparison.

The owner-aware serving adapter revalidates current admission on each use,
checks the envelope's manifest identity, compatibility and immutable predecessor,
exports the exact complete checkpoints, and explicitly selects the declared
predecessor for serving rollback. Serving rollback does not rewind training.
Restoring training writes a separate research checkpoint and requires the pinned
research loader; it confers no live activation authority.

## Executed qualification

| Qualification | Result | Evidence |
| --- | --- | --- |
| Actual `codex-hepta-neuron` crate | 113/113 tests passed | `logs/native-tests.txt` |
| Final signed terminal-admission/owner/recovery composition | 11 tests passed; one worker is invoked explicitly by its matrix | `logs/terminal-recovery-tests-r3.txt`, `logs/terminal-recovery-junit.xml` |
| Native roundtrip plus existing Python checkpoint/controller loader | All eight linear/gated checkpoints at0/16/17/32 restored exactly | `numerical-qualification.json` |
| Mid-plan continuation | Both step17 cases reproduced the remaining15 updates, seven first-block pending actions, terminal full state and receipt chain exactly | Same receipt |
| Changed state bits, anchors or source closure | All six restore attempts rejected | Same receipt |
| Mid17 substituted for terminal32, or wrong reviewed terminal-state map with all hashes updated | Both reject before owner writes; owner bytes unchanged | Final recovery suite |

The recovery matrix abruptly exits a real child process while holding the
owner's writer fence at Prepared, PayloadDurable, RegistryDurable,
CURRENT-durable-before-WitnessDurable-checkpoint, WitnessDurable and Acknowledged.
The CURRENT window is represented by deleting only the fixture's final phase
checkpoint after the real CURRENT write. Every case recovers the same signed
operation, reopens, serves and rolls back; an exact repeated execute leaves the
entire owner byte inventory unchanged. This is process-crash qualification, not
a claim of power-loss or arbitrary-filesystem fault coverage.

The positive owner fixtures have synthetic measurements, reports and explicitly
public fixture keys. The numerical qualification uses real Adam/controller/native
implementations over synthetic input vectors. Neither is scientific acceptance
of an actual V7 candidate. The genuine V5/V6 scientific rejection receipts remain
in their earlier immutable qualification directory.

The first numerical attempt correctly stopped on an overly narrow adapter
assumption: the frozen closure contains `real_encoder_candidates.json` as well
as Python files. The corrected adapter verifies bounded basename `.py` and
`.json` entries by their exact hashes. Its second attempt passed. The first
sandboxed `just fix` could not create Cargo's local locking listener; the same
scoped operation succeeded with the required OS permission. Both attempt logs
are retained. The isolated standalone test run also needed its explicit existing
nextest configuration path to resolve the local profile; failed setup attempts
and the successful command are recorded. No criterion or measurement changed.

## Reproduction and source identity

Run from `codex-rs` with the repository's `just` recipes:

```sh
just test -p codex-hepta-neuron --offline
just test --manifest-path ../qualification/trained-cell-v7/recovery-driver/Cargo.toml --config-file .config/nextest.toml --offline
just fix -p codex-hepta-neuron --offline
just fix --manifest-path ../qualification/trained-cell-v7/recovery-driver/Cargo.toml --offline
just fmt
```

Each completed source stage ran its tests before its required fix/format sequence.
The newly requested terminal-admission stage then received its own targeted suite
and final fix/format; tests were not repeated after that final sequence.
`source-tested.json`, `source-terminal-tested.json` and `source-final.json`
distinguish those exact source bytes.
The final core fixer made one local simplification; the standalone fixer made no
changes and reported one unused inherited V5 `reject` helper. The actual four
crate source files are included in the inventory. `workspace-Cargo.toml` and
`workspace-Cargo.lock` record the small qualification workspace; they must never
replace the repository's production workspace files. Rust/cargo1.95.0, just1.59
and nextest0.9.149 were used. The standalone research crate adds no production
workspace dependency and is not a Bazel target.

The numerical entry point is `qualify_handoff_v7.py`; it takes the frozen research
code directory, source-map file, compiled `handoff-check` binary and a new output
directory. `handoff-check INPUT EXPECTED_SHA CONTROLLER_PROTOCOL_SHA NEW_RECEIPT`
performs development-only decoding and exports exact checkpoint bytes. Its
receipt includes the compiled decoder source digests. Actual selected/config00
grid handoff receipts will be added separately after the grid is sealed, without
changing its files or this acceptance boundary.

## Remaining scope and future admission requirements

This qualifies the actual native crate and existing owner/snapshot composition,
not the entire repository, Bazel graph or Agentd product activation. The new
classifier logits/probabilities retain their own typed serving interface; they
do not acquire the unrelated Q24 value/uncertainty semantics.

A future genuinely fresh, frozen scientific profile must independently require
every registered joint task/retention/cost/completion gate, detailed replay and
statistical audit receipts, and an external pinned research-reviewer signature.
The positive adapter already binds the payload's **completed exact evaluated
terminal checkpoint** to the reviewed state family. Generic transport intentionally
accepts valid mid-plan states for diagnostic restoration; positive admission rejects
them. A genuine V7 scientific profile is absent here. Research trust never implies
production trust or activation.

Independent read-only review confirmed the complete-state consistency checks,
original-prefix recovery, predecessor binding and owner-aware per-read/rollback
path. Host trust remains explicit: the host supplies the authentic feature input,
current admission view, externally pinned restore contract and verified source
closure, and cannot treat a copied decoded tensor as a current authorized read.
