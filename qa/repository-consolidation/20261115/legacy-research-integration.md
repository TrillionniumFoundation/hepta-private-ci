# Reviewed legacy research integration

This record covers ordinary three-way merges on the local reviewed legacy
branch. Original branch tips remain preserved as merge parents. It does not
grant production authority or establish that required CI has passed.

## Fleet and group-research ancestry

Starting checkpoint: `b6a5e15aa4`.
Incoming tip: `255c4fdfad374c08200847761040c4eadaa16f7d`
(`research/v11-fleet-clippy-test-20261016`). This tip covers 52 distinct frozen
unmerged tips and 52 branch names; coverage overlaps with other selected tips.

Despite its single conflicted path, the initial ordinary-merge preview contains 243 paths,
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

## PRED observed-history and retained research ancestry

Incoming tip: `ed9918ab1c2642e0c866425a700ca0eb5f806c70`
(`evidence/pred-history-study-20261112-5028`), merged normally after the Fleet
checkpoint. It covers 28 frozen tips and branch names. This merge adds 40 Python
files to `scripts/hepta_pred1` and retains their associated evidence; it does not
replace Rust source or introduce workflows.

### Conflict resolution and evidence integrity

The only conflict is `.github/blob-size-allowlist.txt`: the current side appends
ordinary-owner and other preserved evidence, while the incoming side appends 18
independent, exact-byte PRED archive-part exceptions. Both sets are retained.
Every new exception was checked against the file's SHA-256 before resolution;
there is no path overlap, wildcard or size-threshold change. Exact stage OIDs
and the 18 checked digests are recorded in `legacy/pred-allowlist-resolution.json`.

All 20 archive parts match their recorded sizes, SHA-256 values and Git blob
identities. In-memory reconstruction matches both original XZ archive digests;
all 599 training and 200 replay regular members match the frozen inventories.
All 22 adjacent history-evidence inventory records also match their files.
`legacy/pred-archive-validation.json` records this byte-integrity check. Archives
were read without filesystem extraction, and their historical drivers were not
executed. Their original `HOLD`, `HOLD_UNCHANGED`, `NoUpdate`, missing live-owner
data and incomplete physical-cost conclusions remain unchanged.

### Source review and correction

The active Python modules were reviewed across causal action-prefix encoding,
fixed/cached preparation, crossed train/dev design and replay, native ledger
readback, observed empirical/MLP/GRU fitting, calibration, owner-effect joins and
shadow inference. Source and regression coverage preserve unknown/censored
labels, separate training from confirmation, bound schemas and numeric input,
retain failed work, and prevent numerical eligibility from granting production
activation. The SQLite adapters use existing databases in read-only/query-only
transactions and bind parameterized identity keys; their selected columns match
the current TaskFlow dispatch/reconciliation migrations. Checkpoint loading uses
bounded, pinned JSON or NPZ bytes, with object arrays disallowed and explicit NPY
shape/expanded-byte checks at the native shadow boundary. The only subprocess
training wrapper launches a copied, source-pinned module in its own process group;
its timeout terminates that owned child session and retains failure receipts.
No remote publish, service restart or model-acquisition path was introduced.

Review found a concrete replay admission gap: the gate ignored fields already
produced by its outer wrapper. A temporary fixture with a zeroed result digest,
a nonzero child exit code or a false source-closure flag was still accepted.
The gate now requires a successful integer child exit, an unchanged source
closure, a matching terminal-result digest, and matching original/executed source
readbacks before opening fit outcomes/checkpoints or creating replay output.
The new regression covers these inconsistencies, boolean exit-code confusion,
changed source readbacks and post-receipt result changes. These checks validate
consistency of supplied artifacts; they do not authenticate the operator.

Because the replay source changed, historical registrations tied to the original
source hashes remain historical evidence. A new execution must use a registration
for the revised source; none of the retained scientific results was relabeled.

### Verification

The original 55-file PRED source closure passed 182 tests in isolation, with no
skips. Its bytes matched the actual ordinary merge before the gate correction.
`legacy/pred-python-tests.json` and its log record the complete suite on the
corrected merged source: 183 passed, without skips, including the added rejection
regression. These are
source/fixture checks, not a live-owner study or a new training campaign.

The staged merge passes the unchanged 512,000-byte blob policy, including all
18 verified exact-byte exceptions. The source/allowlist/audit diff whitespace
check passes. The full diff whitespace check reports CRLF or trailing spaces in
three unchanged historical hosted logs (546 reported lines); those bytes match
their historical inventory and were retained. No whitespace-check exclusion or
global size limit was changed. The scoped and full outcomes are distinguished
in `legacy/pred-static-checks.json`.

## PERC real-producer and native-control ancestry

Incoming tip: `9197fc1ec55d1ff25efa0ac87ad21659e5d55d7f`
(`research/perc-native-control-c47d3953-20261110`), merged normally after the
PRED checkpoint. The actual delta adds 90 paths, including 18 Python production
modules and 11 test modules. It changes no Rust source or workflow behavior.
All 90 new paths retain their exact incoming bytes, as recorded in
`legacy/perc-source-integrity.json`.

### Conflict resolution and preserved evidence

The sole conflict is an explanatory comment in `.gitattributes` above the
existing canonical Perception fixture rule. The resolution retains the incoming
explanation and every existing attribute. It also adds exact `-text` rules for
the three already-verified PRED historical logs, protecting their original
line endings on other platforms. This does not exclude whitespace checks. The
Perception fixture's complete SHA-256 and native payload SHA-256 both match the
retained EOL proof; this is a byte check, not a new Windows/native execution.

Historical public evidence summaries and their HOLD/failure records are retained
unchanged. Private image/receipt/model archives named by those summaries are not
present in this delta, so their historical execution results were not reverified.
Archived HeptaRuntime continuation/publication request JSON remains evidence;
none of those commands was launched, reconciled or published during this review.

### Source review

All 18 new production modules were read, covering raster export, local frozen
producer, train-only projection, acquisition ridge/MLP heads, document data and
OCR collection, actor prefixes, public controls, diagnostic evaluation, native
readback, recomputation, repeated development training, source-reuse rejection
and process metering. The producer requires a local SHA-pinned weight file,
loads it with `weights_only=True`, and constructs torchvision with no pretrained
weight download. It bounds image/region/native-wire sizes and retains original
RGB crop evidence. OCR and native probes use argument lists and timeouts.

Acquisition heads remain advisory/HOLD. They separate TRAIN/DEV from confirmation,
retain controlled prefix/evidence identities and leave production source/budget
ownership unimplemented. The actor uses bounded read quotes and preserves an
overrun failure instead of labeling an over-budget trace valid. Diagnostic
reports keep the unchanged complete PERC prerequisite gate; no scientific or
production acceptance was promoted. DEV repeats are labeled as calibration with
shared sources, and local time/byte proxies are not described as provider bills.

Native probe generation points to the actual production Rust Perception and
Hepta type sources and checks their before/after hashes. Its wrappers prove
observation decoding/binding only and deny Cell admission/execution attestation.
The process meter owns its launched process group, preserves timeout/failure
receipts and does not claim completeness for detached descendants. No network
acquisition, remote publication, daemon restart or automatic training job is
introduced by the merge. No PERC production logic required a merge correction.

### Verification

`legacy/perc-python-tests.json` and its log record an exit-zero run of the full
`test_perc1*.py` discovery: **90 reported tests, 84 passed and six explicit
skips**, with source hashes unchanged. Five skipped producer tests require an
explicit official MobileNet checkpoint; the executed document test additionally
requires its explicit dataset/runtime. All 29 incoming Python files parse.
These source/fixture and owned-child-process checks did not run a historical
campaign, acquire a model or execute a native Rust probe. Native checks and the
six dependency/data-bound tests remain pending on an appropriately provisioned
host; historical PASS fields do not fill that gap.

The complete staged PERC delta passes the unchanged 512,000-byte blob policy
and full `git diff --check`; the tree checked and raw outputs are recorded in
`legacy/perc-static-checks.json`. This is scoped to this third merge, so it does
not relabel the three preserved PRED raw-log whitespace findings.

## Model-runner documentation correction

A separate documentation-only follow-up describes the existing custom-model
exception accurately: local content-pinned snapshots are required, automatic
downloads are disabled, and custom code defaults off; the CLI permits only the
explicitly audited `jina_zh` snapshot with `--allow-audited-custom-code`. Runtime
logic is unchanged. The before/after Python ASTs match after normalizing the
module docstring; no model was loaded for this documentation correction.
