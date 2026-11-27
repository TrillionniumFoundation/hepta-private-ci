# HCSN persistence successor: immutable checkpoints and receipt journals

This package builds and tests a new persistence candidate from the exact
archived C2 v4 source. It addresses incomplete checkpoint publication and torn
JSONL reporting. It does not repair, relabel, or resume the original six C2
attempts. Their missing controller result, empty interrupted checkpoints, and
unknown supervision outcome remain historical evidence.

The implementation requires Linux/POSIX process identities and file/directory
`fsync`. It assumes a private output directory and honest storage. It is not a
signature or access-control boundary against a writer who can replace that
directory or rewrite its files.

## Checkpoint publication

`atomic_publish` writes to a unique temporary file in the target directory,
flushes and synchronizes the serialized bytes, validates them, and publishes
the final name through an atomic hard link that refuses an existing target.
The directory is synchronized before success is returned. Empty immutable
artifacts are rejected. An existing valid checkpoint is never overwritten by
this path.

The materialized `immutable_checkpoint` additionally loads the temporary
checkpoint with `torch.load(..., weights_only=True, map_location="cpu")` and
compares the entire supplied tensor, optimizer, RNG and metadata structure
before publication. This verifies serialization of the supplied state; the
original model/data/source admission rules still establish what that state
represents. Mutable checkpoint aliases are separately rebuilt and atomically
replaced after their copied bytes match the immutable source identity.

An exception can occur after a final name became visible. Inspect the retained
identity before deciding what happened; do not blindly repeat a write or a
training effect. An abrupt process exit can leave a `.tmp` file. Such files are
not checkpoints or receipts.

## Receipt authority and terminal semantics

`ReceiptJournal(view_path)` creates a new `view_path.name + ".records"`
directory and an owner containing a UUID, PID, Linux boot ID and process start
ticks. It refuses an existing attempt rather than taking it over.

Each canonical receipt binds its sequence, complete owner SHA256, previous
receipt SHA256 and payload SHA256. The receipt is durably published before the
convenience JSONL view is appended. Append uses cached sequence/head state;
it does not reread every historical receipt on every event. A write exception
blocks subsequent appends, while retaining enough identity to inspect a
possibly committed final receipt without repeating it.

`close()` checks the entire contiguous chain against the owner's committed
history, atomically reconstructs the JSONL view, and publishes
`view_path.name + ".receipt-index.json"`. The index binds the full owner-file
identity, record count, head digest and view byte count/digest. A second close
only validates the existing result. A verification-only controller may close
an empty journal; that creates an empty view and a nonempty index.

`read_receipts` returns a verified prefix and counts retained temporary files.
It never infers that all training attempts terminated. `validate_closed_journal`
requires a consistent chain, index and view without generating or repairing
anything. The runner terminal gate additionally requires exactly one final
`finished` event, with a string status matching the result.

The materialized controller records the actual child's PID/boot/start identity
after `Popen`, retains its observed exit and `wait4` costs, and compares that
identity with the journal owner. Boolean or coerced numeric identities and
unknown exits are rejected. If the child identity cannot be read, the executed
attempt remains subject to cleanup and `wait4`; a successful terminal result
is not inferred. A complete receipt chain remains software evidence, not proof
of sufficient training, numerical qualification or scientific benefit.

## Exact source construction

`materialize.py` verifies the pinned v4 outer archive, embedded tested-source
ZIP and original program-member identities. It applies narrow replacements to
the archived I/O, runner and controller, copies the new persistence modules,
and writes a new program manifest, provenance and `SUCCESSOR.diff` into a new
directory. Original archives and fit directories are untouched.

The command only constructs source. It does not launch training or create an
execution decision. The changed program-manifest identity cannot reuse the
original C2 decision. A separately bound successor experiment must retain all
source, data, model, opportunity and resource identities before its results
can be evaluated.

## Reproduce the software checks

Run these commands from the repository root. Standard-library checks require
Linux/POSIX and do not load a model:

```bash
python -B -m unittest -v \
  proposals.hcsn_persistence_v1.test_atomic_io \
  proposals.hcsn_persistence_v1.test_journal \
  proposals.hcsn_persistence_v1.test_materialize
```

The current classes contain 18 tests: six atomic-publication tests, eleven
journal tests and one materializer test. The journal suite includes an abrupt
subprocess exit after receipt publication, wrong-owner and terminal-semantic
counterexamples, and a measured 3,000-event durability exercise. These tests
do not simulate storage power loss.

With the pinned CPU Torch/NumPy/mpmath runtime from the HCSN science workflow,
run the four synthetic checkpoint/runtime integration tests:

```bash
python -B -c 'import torch, numpy, mpmath'
python -B -m unittest -v proposals.hcsn_persistence_v1.test_runtime
```

Construct a fresh source directory, then use separate Python processes for
the terminal and inherited suites:

```bash
hcsn_successor_root="$(mktemp -d)"
python -B -m proposals.hcsn_persistence_v1.materialize \
  --repository . --output "$hcsn_successor_root/source"
python -B -m proposals.hcsn_persistence_v1.test_successor_terminal \
  --successor "$hcsn_successor_root/source"
python -B -m proposals.hcsn_persistence_v1.run_successor_tests \
  --successor "$hcsn_successor_root/source" \
  --output "$hcsn_successor_root/inherited-tests.json"
```

The terminal CLI executes all eight historical terminal-test methods through
the extended persistence fixture plus seven new methods, for 15 tests. The
inherited CLI separately runs all `ExecutionTests` (11), `ProtocolTests` (8),
`ReportingTests` (4) and `TraceCoverageTests` (5), for 28 tests. Reporting's
internal terminal-fixture reference uses that same extended fixture. Original
test methods, assertions and archived file bytes remain unchanged; business
functions are not replaced. The old terminal class is not separately collected
again. Both CLIs verify that their actual imported modules come from the
materialized source. The inherited summary exposes tests run, failures, errors,
skips, source identities and source changes. A skip does not pass its gate.

The workflow's persistence step runs these groups under the existing pinned
Torch environment and is included in its required outcome tuple. The
[native validation appendix](../../qualification/hcsn_differentiable/evidence/p0p5-persistence-validation-20261111/README.md)
binds the final ten Python source files and **65 distinct passing tests**:
18 standard-library, four Torch/runtime, 15 terminal and 28 inherited tests,
with no skips or source changes across the final invocations.

The first native wrapper, `1a1c906f6e7-135c4-395`, passed the 22 standard-library
and Torch/runtime tests, constructed the successor, and passed all 15 terminal
tests. Its fourth command incorrectly invoked the inherited runner as a script,
so the wrapper exited 1. That failure remains in the evidence. The targeted
follow-up, `1a1c90894e4-135c4-39c`, used the correct `python -m` entry point on
the same source bytes and passed the remaining 28 tests. The first 37 tests
are not counted again. These native results do not establish the outcome of a
hosted GitHub Actions run or an all-green repository CI result.

## Costs and qualification limits

The journal test prints `HCSN_JOURNAL_COST` with append wall time, total local
wall time and process CPU time for 3,000 events. Observed cloud scratch runs
varied with cache state; one warm run used about 0.694 seconds for append and
0.997 seconds including close and verification. These are local software
overheads, not energy measurements or a full training resource comparison.
The materialized runner/controller sample their report clocks after journal
close and artifact identities. Final result-publication tails still need the
outer process envelope; controller, child and archival costs must not be added
twice.

The separate
[original C2 audit and checkpoint replay](../../qualification/hcsn_differentiable/evidence/p2-c2-independent-recovery-20261111/README.md)
supplies development-set reproduction for four original fits; it does not test
a newly trained persistence successor. This package supplies no real C3
training result, all-six original C2 reconstruction, full training-domain
numerical pass, matched scientific gain, storage power-loss qualification or
production adoption. Those remain separate, explicitly measured gates.
