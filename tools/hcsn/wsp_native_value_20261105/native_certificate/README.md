# Native exact continuation certificate

This package adds `weight_continuation_certificate` to HeptaRuntime. It verifies a
supplied separation witness for a **fixed TRAIN continuation head subproblem**
using exact integers. It does not search for a witness, train or edit a model,
execute the hidden representation, evaluate task value, or install a checkpoint.

The source baseline is HeptaRuntime
`990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7` (PR #93). The five real witnesses come
from the prior TRAIN certificate in `hepta-private-ci` PR #4823, pinned to
`85f507fb2e1c9e8ad9941451641bb4ec3f1dccb4`. That research already established
these certificates with Python exact arithmetic. The contribution here is an
independent Rust arithmetic implementation, a bounded read-only MCP interface,
explicit input identities, and reproducible native qualification. A repeated
certificate is not a new model-quality improvement.

The seven Rust/Cargo build-input changes and the fixed math/schema notes are
published in HeptaRuntime draft PR #94, commit
`bc38fb82244b946907886704b3c677bf00761cb9`. Publication alone does not qualify a
test, a native execution, or a model improvement. The observed qualification
below remains tied to the exact bytes, frozen binary and execution receipts.

## Exact scope

The checkpoint's first three affine output rows supply the 147-component center
`C`: 48 hidden coefficients followed by a bias for each of WAIT, READ and REPAIR.
The submitted 49-component hidden rows, legal-action masks, six supplied teacher
scores, and nonnegative witness multipliers supply the linear system and its
witness. Each comparison asks the submitted teacher's first legal maximum to
weakly outrank one distinct legal continuation competitor. The radius is fixed:
`R² = ||C||² / 4`.

For `v = Aᵀy` and `d = -vᵀC`, the ideal-real certificate requires both `d > 0`
and `d² > R² ||v||²`. A second verdict subtracts a conservative binary64
rounding allowance before repeating the exact sign and squared comparison. The
two verdicts are retained separately. Exact equality is not a certificate;
failure to certify is not a feasibility result. See [MATH.md](MATH.md).

A positive result excludes satisfying every submitted weak ordering within
this original ball and this fixed representation. It does **not** exclude a
useful partial repair, a larger radius, a different hidden representation,
better task utility, another policy family, or unrestricted neural networks.
The F64 result additionally depends on the stated execution semantics. The
primitive does not probe hardware rounding, FMA contraction, or flush-to-zero.

## Identity and trust boundary

The native verifier hashes the raw checkpoint JSON bytes and obtains `C` from
those bytes; callers cannot supply a different independent center. The existing
`serde_json/float_roundtrip` feature is retained, and qualification compares all
735 center binary64 encodings against Python's reading of the same five raw
checkpoints. It validates declared checkpoint metadata and the finite output
head. It does not parse or reexecute `w1`, `b1`, hidden activations, or the full
checkpoint execution graph.

Each witness binds its row identity, supplied state/table digests, hidden bytes,
teacher-score bytes, legal mask, target, competitor, and multiplier. Repeated
comparisons are rejected. Repeated source rows with different competitors must
have identical state, table, hidden, teacher scores, mask, and target metadata.
The supplied teacher scores must make the target the first legal maximum.

Expected hashes are caller supplied. Hash equality is content binding, not a
signature, trusted source authentication, or proof that a checkpoint or program
generated the submitted features or scores. The protocol/source/old-record
digests are echoed as declarations. The prior Python exporter/replay work is a
separate layer. This Rust primitive certifies only the submitted mathematical
system. Every successful response explicitly denies source authentication,
hidden/teacher reexecution, new holdout/task-value qualification, whole-network
impossibility, production eligibility, and weight mutation.

## Resource and API boundaries

The tool accepts at most 8,192 rows, 1 MiB of checkpoint JSON, and 8 MiB of its
canonical typed request. Output is limited to 512 KiB. Binary64 encodings have
fixed width; all arithmetic has a bounded exponent range. Two blocking workers
are admitted at once; each owns its permit until the worker actually exits.
Workers check a 30-second cooperative deadline at row boundaries and before and
after final arithmetic. A single bounded integer operation is not preempted.

The request byte limit is enforced after MCP transport/Serde deserialization;
it is not a transport allocation guarantee. The tool has no file, network,
model-write, process-launch, optimization, or installation capability. The MCP
registration advertises a read-only, idempotent operation.

## Reproduction

The package already includes the complete five-fit raw requests and independent
references in `inputs/`. An acceptor can use these directly for qualification,
freeze and native MCP execution; downloading the earlier large research package
is not required. All output paths below must be new, and the dependencies
specified by `Cargo.lock` must already be available in the Cargo cache for the
locked offline software gates.

The historical local qualification runner deliberately requires the PR #93
baseline HEAD plus the exact seven-file source overlay. To repeat that layout
from a clone containing both commits, create a new worktree and restore only
the published build inputs. This does not change an existing checkout:

```bash
git -C /path/to/HeptaRuntime worktree add --detach /new/path/runtime \
  990f85e46bedb8f49c0e6d0029ea6f9afbf6eac7
git -C /new/path/runtime restore \
  --source=bc38fb82244b946907886704b3c677bf00761cb9 -- \
  Cargo.toml Cargo.lock src/mcp/mod.rs src/mcp/server.rs \
  src/mcp/weight_certificate.rs src/mcp/weight_certificate_exact.rs \
  src/mcp/weight_certificate_tests.rs
```

Place this experiment's Python files under
`/new/path/runtime/experiments/weight/native_certificate_20261105/`. The
published PR #94 tree supplies the same build inputs; the baseline-HEAD check
is an experiment-layout assertion, not a requirement that the resulting
working source be unmodified.

```bash
cd /new/path/runtime
python3 -B experiments/weight/native_certificate_20261105/run_local_qualification.py \
  --root /new/path/runtime \
  --target /new/path/target \
  --output /new/path/software-qualification

python3 -B experiments/weight/native_certificate_20261105/freeze_protocol.py \
  --root /new/path/runtime \
  --qualification /new/path/software-qualification/RESULT.json \
  --inputs /path/to/native_certificate/inputs \
  --output /new/path/execution-protocol.json

python3 -B experiments/weight/native_certificate_20261105/supervise.py \
  --output /new/path/native-corpus-cost --timeout 900 -- \
  python3 -B experiments/weight/native_certificate_20261105/run_corpus.py \
  --binary /new/path/target/debug/hepta-runtime \
  --inputs /path/to/native_certificate/inputs \
  --protocol /new/path/execution-protocol.json \
  --protocol-sha256 SHA256_PRINTED_BY_FREEZE \
  --output /new/path/native-corpus
```

`prepare_inputs.py` is an optional reconstruction and comparison step. It reads
only the pinned prior TRAIN artifacts, recreates the requests/references, and
checks the fresh `Fraction` quantities against the preserved original proofs.
Use the earlier research directory at the pinned commit if performing this
additional provenance replay; do not regenerate witnesses on a holdout:

```bash
python3 -B experiments/weight/native_certificate_20261105/prepare_inputs.py \
  --prior /path/to/hepta-private-ci/tools/hcsn/wsp_followup_20261105 \
  --output /new/path/reconstructed-inputs
```

Compare reconstructed request/reference contents and original-source identities
with the bundled inputs. A new manifest's timing fields are run-specific; the
bundled manifest remains the identity of the recorded execution.

Check each script's `--help` for the exact current interface. Output directories
are create-only; failed attempts must be retained. The protocol binds the
qualified binary, source files, test receipt, driver sources, and input
manifest before corpus execution. The driver pins the binary, calls actual
stdio MCP, retains every response including malformed cases, and compares
exact rational quantities and center bits with `reference.py`.

Software verification covers both feature configurations, all `weight_*`
library tests, strict all-target Clippy, formatting, and the CLI build. This
local test selection is not a claim that every repository test ran. Record
whole-process CPU/wall/RSS with the supervising process as well as the driver's
self CPU and per-RPC wall times; those are different cost scopes.

## Files

- `src/mcp/weight_certificate.rs`: typed request, content binding, limits and MCP
  entry point.
- `src/mcp/weight_certificate_exact.rs`: exact integer arithmetic.
- `src/mcp/weight_certificate_tests.rs`: analytic and malicious-input tests.
- `reference.py`: independent Python `Fraction` arithmetic.
- `prepare_inputs.py`: complete five-fit exporter and prior-proof comparison.
- `run_local_qualification.py`, `freeze_protocol.py`, `run_corpus.py`: software
  gates, identity freeze and actual native MCP qualification.
- `supervise.py`: whole child-process CPU/wall/RSS receipt and preserved logs.
- [SCHEMA.md](SCHEMA.md): exact encodings and response interpretation.
- [QUALIFICATION.md](QUALIFICATION.md): observed results, costs, failures and
  remaining limitations. Only recorded executions qualify as passes.
