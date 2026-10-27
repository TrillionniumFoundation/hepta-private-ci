# Coherent dependency port qualification

This packet prepares a reviewable candidate for the remaining dependency CI
failures. It does not activate the ports or authorize production deployment.
The scientific acceptance failures in `../../BLOCKER_LEDGER.json` remain open.

## One candidate, independent consumers

`RECIPE.json` binds the complete source patch, the exact file set of seven
vendor directories, expected package versions and effective features, the
original Matrix fixture producer, and the full upstream AWS test resources.
The producer must reconstruct the approved source, resolve Cargo and Bazel
locks together, and export the exact resulting bytes. Every consumer verifies
the producer's RESULT hash, source commit, workflow run and attempt, recipe,
vendor inventory, source snapshots, locks and binary patch before using them.

The original `deny.toml`, cargo-deny workflow and diagnostic source are bound
inputs. No ignore, feature reduction, platform reduction or policy edit is
permitted in the candidate. Original AWS dependency versions are checked
explicitly; login signing is ported without replacing the provider surface.

| Qualification | Required observed result |
| --- | --- |
| Source and locks | Exact approved source; both lock generators and lock check succeed |
| YAML consumers | Utility and actual skills, plugins and migration packages execute |
| AWS consumer | Actual workspace AWS authentication package executes |
| Keyring consumer | Actual workspace keyring package executes |
| Matrix | Four actual workspace packages and an independent old-state reopen execute |
| AWS upstream | All 244 nonignored upstream test names execute; the original DNS ignore is the only exception |
| Cargo deny | Original pinned action succeeds with its unchanged complete scope |
| Linux Bazel | Four first-party consumers and six vendor library targets build with sealed locks |

The workflow contains seven jobs, with the ordinary workspace test job expanded
into three groups. The Linux library build is a targeted qualification; it is
not a claim that all-platform or full-workspace CI has passed.

## Matrix migration provenance

The old fixture is compiled from the independent fixed source
`6215cb6a87f29623d4beaad24cdf7bcb6bb4fb2c`, its original Matrix 0.18 lock and
Rust 1.95. Only the reviewed fixture integration test is added. The producer
retains the compiled source, actual executable, original lock, JUnit report,
database files and every surviving SQLite sidecar after the process exits.

The Rust 1.96 candidate must verify that artifact and reopen a separate writable
copy. A newly generated 0.19 database cannot stand in for old state. Both phases
require exactly the specified test to pass, with no skipped or retried result.
The original artifact is checked again after the migration phase.

## AWS execution completeness

The candidate's complete upstream vendor source is copied outside the workspace
and bound to the separately retained test lock and nextest configuration.
Inventory must contain 245 tests, with exactly the original ignored DNS case.
JUnit must cover the other 244 names, including the two timeout tests that
failed under the earlier local proxy environment. The 19 passing login tests
are useful evidence but do not replace this complete qualification. Executable
copies are hashed immediately and after execution. Only the child's NO_COLOR
setting is normalized; assertions and timeout behavior are preserved.

## Local evidence and its limits

`TESTS_002.json` records 18 actual Python tests of artifact binding, tamper
refusal, compiler identity, complete test inventories and failure preservation.
`FORMAT_ONLY.json` binds the subsequent seven-file Python formatting change and
identical ASTs; it does not claim a repeat behavior run. `BUILD_FORMAT_ONLY.json`
retains the original and formatted BUILD text, formatter hash, and expression
equality with keyword argument order normalized. `PREFLIGHT_002.json` independently
checks all 1,282 vendor files and reconstructs all 29 source paths from an
isolated Git index using the final recipe. Earlier receipts remain available.

The older ZIP/protocol staging workflow is tied to the already running reviewed
head `88bcc7f92b9a52bf77e0095614fd496288b6ca86`. Later candidate pushes do not cancel
or duplicate that qualification. Ordinary repository gates remain in place.

Remote compilation, migration, upstream execution, original dependency policy,
and normal platform results determine whether the ports can be integrated.
Successful preparation alone never sets `promotion_allowed` to true. Production
native authority remains `DENY_ALL`.
