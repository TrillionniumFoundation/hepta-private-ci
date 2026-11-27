# Reviewed small legacy source integrations

Each incoming tip is merged normally after a fresh preview against the current
local head. Small/clean deltas are reviewed as code; historical PASS records do
not establish results for the combined source. Remote and protected HIA refs
are not changed by this local work.

## Independent v1 scorer

Incoming `0f8091d6f27b1f81eac08f1a1f3383a952a4ab80` adds the standalone model-free
audit, tests, explanation and a historical receipt. Review covered the complete
scorer, bounded reference-subset matching, exact frozen episode/method roster,
PNG bytes, score and cost reconciliation. No model/network job is introduced.

A concrete cache bug was reproduced: after accepting a 20x20 PNG, the auditor
accepted the same digest against a later 21x20 reference. The cache had stored a
reference-specific validity flag. It now stores only the pinned PNG's intrinsic
digest, format and dimensions, and rechecks each reference. Decoding uses the
same bytes that were hashed. Positive-to-negative and negative-to-positive cache
regressions both pass. The complete focused suite passes 13 tests without skips.

The original source-pinned historical receipt remains unchanged; its private
evidence archive was not supplied or rerun. The new checks do not revise the
frozen scientific result or authorize promotion. Exact hashes/test logs are in
`legacy-small/independent-v1-audit.json` and its companion log.

## NDU v2 confirmatory statistics

Incoming `f5a605255bca5a300a6c524e8206e8f0cc13d6c3`. Reviewed complete production module and tests. Requires fixed 12-method roster, at least three seeds, full source/seed/method denominator, score/cost completeness, pinned registration and cohort firewall. Uses fractional CVaR and 15 paired source-cluster bootstrap contrasts with Bonferroni intervals. Missing/over-budget observations retain zero quality and severe loss; all paths keep model_promotion_authorized false. CLI defaults retain 128 sources and 2000 bootstrap draws; synthetic unit overrides are not production results.

The fresh preview against `a6b77d82aba0d0f85c99e72910e4184ecec09262` has the exact reviewed source delta;
all incoming files retain their bytes. The focused suite passes 10 tests.
Hashes, command and log are retained under `legacy-small/confirmatory-v2`.

## NDU v2 historical source exclusions

Incoming `ec23a433bfa9b47f8c9a6c5fa892dda313569cd5`. Reviewed complete immutable exclusion assembler and both test modules. Fixed external SHA pins and exact 384+256 roster, original IDs, file/RGB digests and dHash distance reject reused sources. Existing nonidentical output is never replaced. Image fixture invokes existing cohort builder with download_images=False and local temporary JPEGs. No weights, outcomes, historical image payloads, model training or real new cohort were executed.

The fresh preview against `94909bc9f0a0bbd906c3d375b9f4decda7e50ffb` has the exact reviewed source delta;
all incoming files retain their bytes. The focused suite passes 15 tests.
Hashes, command and log are retained under `legacy-small/v2-exclusions`.

## Retention-reader evidence shapes

Incoming `4157c319f6031f8a431c13d5254a1f332c6cd6c8` strengthens nested
object/list checks and per-episode error handling. Missing evidence stays UNKNOWN;
malformed evidence, symlinks and unreadable nonmissing artifacts are REJECTED.
The authoritative roster and failed-row denominators remain intact, while later
valid episodes continue to be scored. Original source-plan pins are still checked
before and after reading; an incompatible original plan is refused. All incoming
source and evidence bytes are retained. Four historical test-stream size/SHA pins
were independently checked, mapping the older metadata's original stream names
to the retained `tests-before-oserror` files. That old run remains historical.

The complete focused reader suite passes 13 tests, including recursive shape
substitutions and later-episode real fixture pixel scoring. No real actor campaign
or production adoption occurred. Details and the actual combined-source test log
are retained under `legacy-small/retention-reader-shapes`.

## Bounded NDU worker deadline boundary

Incoming `d1a4caa4cbc50f5a7e2fd3d6063bf296f4b3c75d` adds a future warm-worker
supervisor and model-free tests. Review found no current production Python caller
in `qa`, `scripts` or `qualification`. Its original pickle transport could run
result reconstruction in the parent: a permitted result with a 600 ms restoration
caused a 50 ms deadline to return only after 603 ms. The result was correctly
marked timeout, but the waiting-time claim was not supported.

The merge retains worker reuse, measured startup, failure accounting, timeout
termination/replacement and unreaped-worker refusal. IPC now accepts bounded
builtin data (including bytes/tuples/null), with no reconstruction callbacks:
1 MiB wire, 4096 values, depth 32, finite floats and integers up to 256 bits.
The same-interpreter marshal framing is internal IPC, not an artifact format.
Custom objects require callers to export bounded data explicitly; the factory
remains importable/pickleable for spawn. Transfer, validation and cleanup are
charged, while OS scheduling latency and grandchildren remain outside the claim.

All 12 focused tests pass. New regressions cover the slow custom result, exact
builtin/null round trips, oversized progress/results and invalid payload bounds,
including cycles. No model work or external campaign was run. The preserved
reproducer, compatibility note, exact source hashes and test log are under
`legacy-small/hard-deadline`.

## Family/cohort factorial preflight

Incoming `9e11892e80b3cbb990d3d2dc8a897bc670dad8fc` adds the dataclass-based
`factorial_evidence` interface. Complete source/test review confirmed paired
A/B/C/D core/controller identities, equal opportunity contracts, per-seed frozen
cohort identities and balanced family rosters. Missing outcomes suppress all
net-value inference and family diagnostics; missing retention/resources remain
null. Sign flips use training-seed clusters rather than repeated task counts,
and four-contrast Holm correction remains exploratory. HOLD_NO_GO/DENY_ALL is
unconditional. All incoming bytes are retained. The focused suite passes 17
synthetic contract tests; these do not run a model or an owner.

## Six-family HPCA factorial coexistence

Incoming `c940b15f5359eccda233ff70d78a89db4ae5321c` has independent add/add
conflicts in `factorial.py` and `test_factorial.py`: its manifest API and schema
differ from the just-integrated dataclass preflight. Both complete implementations
and tests were reviewed. The resolution keeps family/cohort `factorial.py` and
its tests byte-for-byte, and retains the HPCA implementation byte-for-byte as
`hpca_factorial.py`. `test_hpca_factorial.py` changes only its import; AST comparison
confirms every original assertion and fixture is preserved. README entry points
now distinguish the two schemas and their different identity requirements.

The two suites execute together: 32 synthetic contract tests pass, without skips.
Four primary contrasts, missing-retention behavior, all resource/roster checks
and unconditional HOLD_NO_GO/DENY_ALL outputs are preserved in their respective
modules. Neither parser is substituted for the other or promoted to an owner
gate. The incoming HPCA parser records trained-model identities without proving
common weights across arms/families; that limit is explicit in its README.
The stage OIDs and exact path/byte mapping are recorded in
`legacy-small/factorial-hpca-coexistence.json`.

## Historical MEM7 capacity probe

Incoming `d7a037620e78b8ec323bba904e6abbb752a9102f` retains a single historical
4096-record synthetic probe and its exact source. The full harness and its
measurement limits were reviewed: local SHA-pinned source, fresh output root,
SQLite copies under that root and two isolated cold readers. Its cooperative
population wall check is explicitly not a whole-process hard deadline. No
network, model, service or deployment action is introduced.

All eight manifest entries match byte count, SHA-256 and Git blob ID; the sibling
inventory is complete, and the final event/result and cold-reader output pins
match. All nine incoming files retain exact bytes. The Python harness parses.
The historical 176-second capacity study was not rerun, so no new capacity
sample, Rust product qualification or real-task benefit is claimed. The original
HOLD/NoUpdate, missing main exit code and physical-cost limits remain intact.

## Cargo lock failure diagnostics

Incoming `b3226d21f09ec11d74925d8f667c58d98226b2c9` changes only two existing
workflow diagnostics. An online/offline resolver failure is now reported as
unresolved; lock drift is asserted only when a diff was actually observed. The
original nonzero `--locked` exit code is still returned and the checkout's lockfile
is restored. Triggers, job conditions, permissions and failure handling are
unchanged. Both affected shell blocks pass `bash -n`, and both workflows parse.
No Cargo resolution was launched for this message-classification change.

## Historical MEM8 source-only gates V5 through V11

The seven independent harnesses retain their original immutable source/capsule
pins and exact old-branch trigger guards. Their common implementation and each
version delta were reviewed. They format an isolated checkout, verify the entire
base-plus-overlay tree, retain source/lock/tool identities and produce an
uncommitted tree plus records. They do not push, update refs or run models/native
tests. V6 and later additionally verify full golden caller JSON (only a derived
Rust source count may differ) and exact named Python regression outcomes. V5
remains explicitly the earlier, narrower historical operation.

Each ordinary merge checks the fresh preview against its reviewed delta, retains
all incoming bytes, validates each frozen capsule row and golden receipt pins,
and parses Python, embedded Python and shell blocks. These are static integrity
checks, not new source-gate or native qualification runs. No trigger is widened
to main, pull requests or manual dispatch; retired branch names remain inert.
Individual pins and counts are in `legacy-small/mem8-source-gates-v*.json`.

## Historical Fence v0.13 isolated qualification

The entire incoming one-workflow harness was reviewed. It stays restricted to
its original branch, exact source parent/tree and preceding SHA, verifies the
original blob-policy sources and seven pinned Fence files, and retains before
and after identities with read-only repository permission. The artifact correctly
states that Fence post hooks and the final job log are not yet observed.

Thirty whitespace-only blank lines were cleaned; parsed YAML is identical,
including every embedded Python byte represented by the YAML value. All shell
blocks and embedded Python parse. The historical workflow was not executed,
and this retention is not current Fence/native qualification.

## Historical MEM formatter diagnostic

The 34-line Prettier diagnostic is retained unchanged. It runs only on its old
branch or an explicit dispatch, uses read-only contents permission and a frozen
pnpm installation with lifecycle scripts disabled, and prints a formatter diff
from the disposable checkout. It cannot commit or push that rewrite. YAML and
shell parsing pass. No dependency installation or formatter was launched here.

## Historical Windows scoped lint

The complete Windows harness and workflow were reviewed. They retain an exact
old source/tree, pinned lock and recipe bytes, three explicit `just fix --locked`
commands, a single Actions job timeout and before/after tool/source checks.
Any rewrite, nonzero exit or interruption remains a failure; a collection
snapshot cannot replace a missing command exit. Mutation is confined to the
isolated checkout, with no source commit or remote push. Its original old-branch
guard remains intact. Python and YAML parse. The PowerShell blocks were read but
not parsed or executed because PowerShell/Windows is unavailable here. No
Windows native/lint success is claimed.

## Historical Bazel lock V5

The full driver and workflow were reviewed. The original old-branch guard,
immutable source/tree, driver SHA and strict receipt-wrapper identity remain.
It uses an owned Bazelisk/output/repository cache, one bounded original lock
command and exact before/after source, lock and executable identities. A lock
rewrite remains a failed gate requiring another reviewed candidate; there is no
automatic commit, reset or retry. The driver SHA matches the workflow, Python
and embedded Python parse, and all shell blocks pass `bash -n`. No Bazel download,
lock regeneration or native project qualification was run.

## Terminal-loss covariance research contracts

The estimator, all fixtures, README and workflow were read in full. Complete
source/seed/arm pairing, failed or over-budget full losses, train-only fitting,
source/image-disjoint frozen holdout and immutable per-arm proposal identities
are preserved. Portfolio weights remain an additive surrogate; they do not
represent measured mixture performance or authorize any production action.

All nine synthetic numerical/custody tests pass against the integrated source,
without skips. The path-filtered exact-head workflow installs pinned NumPy and
runs only those synthetic tests with read-only contents permission. No real Cell
generation, blind experiment, model promotion or native qualification was run.

## ACT-2 historical fixture contrast and continuation evidence

The complete Python driver, workflow and protocol were reviewed. The old-branch
trigger and read-only permission remain. It requires an actual macOS host and
two fixed source identities across canonical, symlinked-baseline and repaired
paths. The red stage requires exactly the twelve named Invalid failures; later
formatting/source drift cannot become a clean pass. No desktop, native test or
historical driver was run.

All 23 ZIPs retain incoming bytes. Their 409 members pass CRC checks; nine
original macOS manifest entries plus source/command-log bindings match. Two raw
architecture logs keep every original byte through deterministic gzip with
original and stored pins in an adjacent manifest. README documents reconstruction.
Source whitespace checks remain unchanged, no evidence whitespace is erased,
and no historical claim is transferred to this integrated tree.

## Cell lifecycle historical refusal evidence

The archive and full three-document delta were reviewed. Current runtime source
already contains both mandatory public refusal calls; the documentation now
separates that DENY_ALL boundary from private process-local mechanics. The normal
merge preserves other composed documentation. Its generated plasticity status
and referenced test symbols validate, while old documentation-output pins remain
explicitly historical because current document bytes differ.

All 39 original manifest members, eight phase streams and the decompressed
materialization inventory match their pins. The original top-level native runner
is retained byte-for-byte as gzip with a reconstruction manifest, so its trailing
blank line is preserved without weakening whitespace checks. It was parsed only;
no historical negative control, native test or source mutation was executed.

## Retire the automatic runtime.codex bootstrap

The old workflow would run on main pull requests, execute a decoded historical
source transformation and commit/push to its old branch using write permission
and persisted credentials. Its small gzip payload is corrupt, while its shell
pipeline could leave an empty Python file that compiled successfully. Both
original payloads and the original workflow are preserved exactly for review.

The active workflow now requires a manual dispatch with a false-default opt-in,
uses read-only contents permission and inspects the selected source. The new
inspector pins encoded bytes, bounds encoded/decoded size and parses Python AST
without writing or executing the decoded program. There is no transformation,
commit or push. Its actual check fails with the original corrupt payload and
successfully parses the larger source proposal; this is the expected honest
archive result, not qualification. Five regressions pass, including a source
that would create a file if it were executed, corrupt original bytes, changed
hash, excessive decoded size and invalid syntax.

The larger preserved proposal contains exact dispatch binding and a cross-owner
pre-effect abort/ack outbox design. Those Rust changes were not blindly applied;
they remain an explicit semantic-review item against the latest runtime source.

## Source-only recovery with an explicit raw archive gap

The two historical archive scripts and complete notebook code cell were reviewed.
The three supplied source-only tarballs match their sidecars, internal manifests
and all 339 selected member hashes; 243 Python files and 31 JSON files parse.
Bundle members were not executed. The fixed-host historical checker is preserved
with an explicit warning that its missing-manifest path and process exit cannot
serve as a current integrity gate; independent strict checks were used here.

Seven blobs above the repository limit now use exact ordered pieces of at most
400000 bytes, with original byte/SHA/Git identities and tested reconstruction.
The source-only HCSN V9 bundle is complete, but its separate raw evidence ZIP was
already missing original part 004 (2000000 bytes). That gap remains explicit;
no full raw ZIP/replay claim or replacement bytes were invented. The existing
notebook code passes its declared 24/48/24 finite-grid numerical cases offline.
Its original bytes/output stay intact, and no training, network or Library
mutation was performed.
