# Reviewed legacy research integration

This record covers ordinary three-way merges on the local reviewed legacy
branch. Original branch tips remain preserved as merge parents. It does not
grant production authority or establish that required CI has passed.

## Fleet and group-research ancestry

Starting checkpoint: `b6a5e15aa4`.
Incoming tip: `255c4fdfad374c08200847761040c4eadaa16f7d`
(`research/v11-fleet-clippy-test-20261016`). This tip covers 52 distinct frozen
unmerged tips and 52 branch names; coverage overlaps with other selected tips.

Despite its single conflicted path, the ordinary merge brings 243 changed paths,
including two new Rust binaries, five workflows, and 187 Python files under
`qualification/stem-cell-v1`. The historical qualification reports and logs are
retained observations of their original sources, not test results for this merge.

### Conflict resolution

`codex-rs/hepta-fleet/src/authority_port.rs` conflicts only in the test fixture's
successful `admit_host` assertion. Both sides construct the same host and require
successful admission. The integration keeps the existing whole-result comparison
`assert_eq!(..., Ok(()))`; no Fleet behavior or fixture fields are removed.

The stage blobs are base `55e117dafe84709451a638bb8f6bafa41c38bd5a`, current
`bec81e610a120727ac749c4e4d75e625f3a0df1f`, and incoming
`67d3d6768fe989c88177fe936ad96e3bd6b49752`. The resolved file is exactly current
blob `bec81e610a120727ac749c4e4d75e625f3a0df1f`. This is a resolution of the
specific assertion conflict, not a whole-branch merge strategy.

### Source and workflow review

The new `ndu-group-control` and `ndu-group-replay` sources retain their incoming
bytes. They bound ASCII input and event/scenario counts, bind the complete input
with a digest, require nonzero context identities, and call the existing scalar
recursive-utility implementation. Replay enforces the library's event sequence,
duplicate-event, discount and utility bounds. Control checks exact Q32 probability
mass, fixed observation ordering, checked costs and conservative downward
rounding; unsupported projection or insufficient resources stops continuation.
Both require a `DENY_ALL` receipt and neither dispatches effects or mutates an
owner. Their receipts explicitly deny production-owner/general-FBSDE claims.

Three incoming real-model paths previously ran from ordinary repository events:
group pretrained research, the public encoder canary, and V10 physical encoding
with dependent training. They now require `workflow_dispatch` and a separate
boolean input whose default is false. Source/unit jobs remain available on
their original triggers; fixed seeds, experiment budgets and scientific
assertions are unchanged. The group source job runs with offline model flags,
builds both native binaries, and provides their paths to native control, replay,
reader and token regression tests. Its path filter includes their source crates.
The next-round source job no longer labels a suite containing conditional native
tests as running "without skips".

The inherited isolated native build helper was incompatible with the current
source tree: `hepta-contracts` has a Windows path dependency on `codex-utils-path`,
which in turn depends on `codex-utils-absolute-path`. Cargo must resolve these
target-specific manifests even for a Linux build. The helper now follows all
production, build and target-specific local dependencies and inherits exactly
their workspace dependency declarations. It retains original production source
bytes and removes only dev-dependency tables. A TOML semantic comparison guards
against deleting a later `[lib]`, feature or target table. Paths outside
`codex-rs`, symlinked source dependencies and nonregular inputs are rejected.
The actual closure contains the three Hepta crates plus `utils/path-utils` and
`utils/absolute-path`; no repository Cargo manifest or lockfile is modified.

### Verification and remaining scope

`legacy/native-helper-oracle-tests.json` and its log record 12 passing local
tests: four targeted build-helper regressions and eight Python control/replay
oracle tests. These tests do not execute Rust. The helper regressions cover the
missing target-specific transitive dependency, preservation of trailing manifest
tables, an out-of-tree dependency and a symlinked dependency.

The coordinator's initial complete discovery of the 81 incoming Python test
modules reported 307 tests, 61 dependency-import errors due to unavailable Torch,
three conditional native skips, and no assertion failures. That run is incomplete
and is not a passing suite. All 187 incoming Python files parsed successfully.
The helper regression added during integration brings the directory delta to
188 Python files. The exact combined source still requires dependency-complete
Python execution, the owning Rust tests, native-binary comparisons, formatter
and linter checks on the prepared native host. Local Rust, Cargo, just and Bazel
commands are unavailable in this execution environment.
