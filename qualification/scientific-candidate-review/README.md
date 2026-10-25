# Scientific candidate publication gate: source qualification

## Result and scope

This is an additive native **publication gate** around the existing
`LearningArtifactOwnerService`. It admits a parameter artifact only after a
host-pinned independent reviewer signs measured task, retention and total-cost
results under a frozen policy. Successful publication remains an immutable
`ArtifactState::Candidate` and returns `DENY_ALL` authority. The existing owner
continues to own writer leases, payload persistence, registry snapshots,
signed `CURRENT`, durable acknowledgements and recovery.

The engineering qualification passed **102 tests, zero failures**, including
10 new gate tests. One existing child-worker test is marked ignored because the
existing process-kill/reopen matrix invokes it; that parent matrix passed.
This is actual owner-crate source compiled in an isolated two-crate workspace.
It is not a full repository or Agentd qualification.

**No research candidate is scientifically accepted by these tests.** Positive
fixtures use synthetic signed measurements and payload strings `baseline` and
`candidate`. This change creates no default product call site, selector,
activation, serving path, NumPy-to-Q24 conversion, or live model update. A real
candidate may remain blocked indefinitely if any independent gate fails.

## Trust and binding

The deployment host constructs `ScientificCandidatePublisherV1` once with its
existing owner service, a frozen `ScientificCandidatePolicyV1` and an approved
reviewer key. The caller of `publish` cannot change those values per candidate.
The host must install the real approved trust root, supply authenticated current
withdrawal frontiers and stamp `request.now` from its trusted clock. This typed
library API is not an untrusted network request boundary.

The policy digest commits the frozen protocol, declared candidate definition,
three comparison definitions, their thresholds and minimum observation counts.
Comparison definitions must commit the endpoints, baseline comparators,
analysis units and cost-accounting scope. The code does not decide whether a
research report used independent samples or counted all costs: the trusted
independent reviewer must verify those claims before signing. Distinct signer
and producer IDs are enforced; genuine organizational and key independence is
part of the host trust decision.

Canonical Ed25519 signing bytes bind reviewer identity and authority epoch,
exact publication operation ID, policy digest, withdrawal-bound admission
identity, expected registry predecessor, report digest, each measured evidence
identity/count/interval, and issue/expiry times. The validated admission in turn
binds the complete normalized manifest, including payload digest, byte length,
code/runtime/schema identities, lineage, generation and rollback predecessor.
The full report digest must appear in manifest lineage. Publication recomputes
the payload hash and requires the eligible parameter predecessor's generation
plus one with matching objective and compatibility identities.

| Gate | Frozen V1 operator | Missing or invalid result |
| --- | --- | --- |
| Task improvement | Interval upper bound strictly below the negative host threshold | Reject before owner publication |
| Retention | Interval upper bound at or below the host non-regression threshold | Reject before owner publication |
| Total cost | Nonnegative interval, upper bound at or below the host cost threshold | Reject before owner publication |

All bounds and estimates must be finite and ordered; comparison identities,
evidence digests and observation counts are checked. NaN, infinity, an empty
evidence digest, underpowered counts and an unregistered comparison all reject,
even with a valid signature. The synthetic test thresholds are not a shipped
scientific policy. A deployment must pin its approved study's actual thresholds
and identifiers.

The publisher preserves exact acknowledged retry and reopen semantics. It
reconstructs the original bounded registry prefix and compares the existing
transaction's intent-derived registration ID before accepting a retry. A new
operation for an already published artifact rejects before owner writes, even
if the reviewer signs the changed operation. Registry history cannot be used as
a blanket exemption from the predecessor check.

The returned receipt commits both the signed review and host policy. The
existing owner persistently stores the report digest through manifest lineage;
it does **not** automatically retain the complete review object or report
bytes. The host must retain those evidence artifacts and the returned receipt
in its review archive. No new broad-purpose JSON parser or unauthenticated
review transport is introduced here.

## Tests and independent source review

The new tests exercise the real durable owner with a baseline parameter artifact:

- Passing synthetic measurements publish one candidate, preserve the baseline,
  grant no authority, return the same receipt on retry and reopen successfully.
- Missing review and each unavailable or failing numeric gate leave every owner
  file byte-for-byte unchanged.
- Every signed field and measurement component is mutated; signatures and
  semantic bindings reject the changes without owner writes.
- Altered payload, manifest digest, generation, policy and expiry reject.
- A current source withdrawal rejects a previously signed candidate, and an
  attempted rollback to the older withdrawal frontier is rejected.
- Correctly signed malformed intervals, evidence and comparison identities fail.
- Validly re-admitted stale generations and registry predecessors reject.
- Wrong reviewer key, self-review identity and revoked reviewer trust reject.
- Task equality rejects while retention and cost equality pass.
- After success, changing the operation ID rejects both with the original
  signature and with a fresh valid signature; the original exact retry works.

Independent source review identified and closed two issues before the final
suite: strict task-threshold equality and operation-ID/retry scope. Neither fix
changes the existing owner's publication implementation.

## Qualification evidence

Source baseline: `a47190bb84714cb1262fcd85ebb723081fdb0581`.
Actual copied source closure: 77 files across `hepta-learning-artifacts` and
`hepta-types`, including the original crate manifests. The two-crate workspace
pins the native direct dependency versions but has its own transitive lockfile;
this is not a claim that the full repository lockfile/build graph was tested.
`source-tested.json` and `source-final.json` distinguish tested source identities
from the final mechanical formatting/lint changes.

Tools: Rust/Cargo 1.95.0, cargo-nextest 0.9.149, just 1.59.0, Linux x86_64.
The original `justfile`, `scripts/run-nextest.py` and `scripts/just-shell.py` were
used. The initial original nextest configuration failed because overrides named
packages outside this isolated closure; zero tests ran in that attempt. The
supplied `nextest.toml` preserves its applicable default/local retry and timeout
policy without those absent-package overrides. That failure is retained.

Final order was scoped `just test`, scoped `just fix`, then repository `just fmt`.
The first `just fix` needed a sandbox retry because Cargo opens a local TCP
listener to coordinate fix locks. The retry succeeded. Clippy's mechanical
let-chain suggestion and boxing of the review enum were applied, then a final
scoped `just fix` compiled the test code without warnings. `just fmt` succeeded
and `git diff --check` was clean. Tests were not rerun after fix/format, as the
repository's `AGENTS.md` explicitly requires. No sandbox-control environment
variables were changed.

## Reproduction

From this native source checkout, with Rust 1.95.0, Clippy, rustfmt, cargo-nextest
and just installed, create a new destination outside the checkout:

```sh
PFT_NATIVE_QUAL=/tmp/hepta-scientific-candidate-qualification
mkdir -p "$PFT_NATIVE_QUAL/codex-rs/.config" "$PFT_NATIVE_QUAL/scripts"
cp -R codex-rs/hepta-types codex-rs/hepta-learning-artifacts "$PFT_NATIVE_QUAL/codex-rs/"
cp justfile "$PFT_NATIVE_QUAL/"
cp scripts/run-nextest.py scripts/just-shell.py "$PFT_NATIVE_QUAL/scripts/"
cp codex-rs/rustfmt.toml codex-rs/clippy.toml "$PFT_NATIVE_QUAL/codex-rs/"
cp qualification/scientific-candidate-review/workspace.toml "$PFT_NATIVE_QUAL/codex-rs/Cargo.toml"
cp qualification/scientific-candidate-review/Cargo.lock "$PFT_NATIVE_QUAL/codex-rs/Cargo.lock"
cp qualification/scientific-candidate-review/nextest.toml "$PFT_NATIVE_QUAL/codex-rs/.config/isolated-nextest.toml"
cp qualification/scientific-candidate-review/rust-toolchain.toml "$PFT_NATIVE_QUAL/"
cd "$PFT_NATIVE_QUAL/codex-rs"
just test -p codex-hepta-learning-artifacts --config-file .config/isolated-nextest.toml
just fix -p codex-hepta-learning-artifacts --allow-no-vcs
```

A normal fully provisioned repository should also run its standard scoped crate
qualification without isolation. This local receipt does not substitute for
full native build, runtime integration, schema compatibility or independent
scientific acceptance of a trained artifact.
