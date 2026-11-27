# Historical Cargo dependency admission

The common candidate `ecac3513c280a5d2ca66fd12f33aa487aea01041` actually
failed its complete file-update, filesystem-effect and unified-formatter
comparisons before they could execute. The first two rejected the changed
workspace `codex-rs/Cargo.toml`; the formatter also required current workspace
dependency declarations to equal its frozen original. Run `45991034792`,
artifact `15196501850`, is retained unmodified in
`common-ecac-original-owner-failures.zip`.

The original workspace must keep its own dependency declarations and lockfile.
The new admission builds its complete ordinary owner and fourteen direct
dependencies with the pinned Rust 1.96.1 toolchain, then binds every selected
unit, artifact, metadata input and command output. Verification re-derives those
identities from the actual retained Cargo streams. Environment flag overrides,
nonempty fingerprint Rust flags, wrong profiles, mixed source/target paths and
native features are rejected. The historical checkout is never rewritten to
adopt the current dependency graph.

The existing current-default versus current-native dependency comparisons remain
required. The complete original libraries and public drivers instead use the
separately admitted historical graph. Downstream standalone, application and
summary comparisons require the new effects receipt and the same bound original
graph. All original cases, five file-update tests, thirteen root tests and
existing output comparisons remain required.

## Actual limited qualification

On ROG, exact original `a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095` completed
an ordinary Cargo build using its unchanged lockfile and the fixed compiler
SHA-256 `4a84e05991ad6f2a84c1361c29b52b38c390365bd1fc269b1936c88d482a8928`.
The captured graph contains 666 library units and 1,284 library files. Thirteen
mutations of its real receipts were rejected, including a boolean return code,
unlocked or failed builds, wrong source/target/native features, altered profiles,
unbound artifact streams, invented units and changed metadata. Positive
verification passed before and after the controls. The seven existing exact
dependency source-projection tests also passed without skips.

`a201-admission.json` records the scope and actual terminal. The archive retains
the actual command streams, graph, metadata, thirteen negative-control inputs,
control report and exact helper source archive. `a201-invocation.py` is the exact
Python source supplied to the owned terminal's `python3 -u -c` invocation.
Its executed source archive contains the shared dependency-admission helpers
and controls; it does not claim that the formatter integration or CI registration
executed in this component run.

This evidence qualifies historical dependency admission only. The complete
original/native owner comparisons, both formatter overflow policies and the
remaining full product/platform matrix still require their actual executions.
The first CI failures are retained as failures, and no skipped gate is admitted
as passing.

## Complete formatter dependency graphs

Both unchanged `aeb88f596b83186456caac577080bcb2f253ad32` original
Cargo graphs completed naturally on ROG using the fixed Rust 1.96.1
compiler. Checked mode took 358.386 seconds and wrapping mode took
346.127 seconds. Each admitted 666 actual library units and 1,284 library
files. Separate target directories and the exact reviewed wrapping
configuration bind each policy. `aeb-both-policies-actual-cargo.tar.gz`
retains both original receipts, Cargo metadata, command streams, graph
manifests and the wrapping configuration.

The formatter runner now builds the complete unchanged original against
its own admitted dependency graph, and builds each public observation
driver against the same graph as its owner. Native owners retain their
current actual Cargo libraries and existing policy admission. The 109
original source files, 3,974 cases per mode, literal transcript comparison,
native call counts, source-entry negative controls and eight native
policy negative controls are unchanged. These dependency build receipts
do not qualify the full formatter comparison.

The existing fourteen complete-owner/formatter CI steps move unchanged
into an independent 60-minute job, with the original six compiler and
policy setup steps copied unchanged. The remaining main steps, the
exec-stdin job, the legacy ABI job and workflow triggers are unchanged.
This retains the original per-job time bound while allowing the three
new historical dependency builds without consuming the main job budget.
Original diagnostics and all owner/formatter result paths are retained.

## Exact types and current Linux dependency projection

Independent review found that Python equality could treat an integer as a
boolean in a rebound Cargo profile. Admission now compares recursive JSON types
as well as values. Five additional mutations of the actual receipt exercise
integer debug assertions, test flags and overflow flags, boolean debug-info, and
an integer profile in the recorded unit stream. All eighteen actual mutations
were rejected and the unchanged positive receipt still passed. The bound helper
source, all mutation records and the actual terminal are retained in
`typed-controls-and-darwin-source-admission.tar.gz` and its adjacent index.

The first full owner attempt on `ba4b4778d0b900c2259538b14b181e11dd39a3a7`
then rejected an existing reviewed Darwin authorization change in exec-server.
A separate exact inverse now binds all 144 current dependency leaves, restores
the three precise Darwin leaves to the previously admitted 143-leaf tree, then
applies the unchanged Wine-test inverse to recover the pinned original tree.
The complete authorization source bytes also recover their original Git blob:
on Linux the candidate list is exactly `[final_path]` and the rejection predicate
remains `D || !A`; the new Darwin helper is excluded by its original cfg.
Unrelated leaves, modes, duplicates, missing or additional files, different
source predicates and refreshed original pins are rejected by eight additional
controls. The original historical Cargo graph remains separate and unchanged.

This exact source admission passed against the actual clean ROG producer and
unchanged a201 snapshot. It does not by itself qualify the complete owner or
filesystem-effect observations. The earlier full attempt remains a failure,
including every skipped dependent comparison, until its successor runs all
required original comparisons successfully.

## Subsequent actual component execution

The complete `ba4b` sequence finished with failure and four skipped dependent
gates; that original sequence record remains unchanged. Its UUID comparison
passed 9,609 public pairs and 78,778 complete regex matches. The formatter policy
gate and complete public comparison both passed: 3,974 cases in each mode,
7,948 paired public results, 15,864 actual HIA calls, 1,417 observed differences
between checked and wrapping policies, and all 109 original source files bound.
This public formatter gate retains its original scope and does not claim to have
run the full original unit suite.

The template gate initially failed inside the unchanged 2 GiB resource bound
because Git mapped a large borrowed pack. Restricting only the three isolated
repositories' local Git mapping windows to 16 MiB/64 MiB exposed a second failure:
lld could not create its worker threads under the same bound. Restricting the
owned process to two of its original 32 allowed CPUs resolved that infrastructure
failure without changing compiler flags, tested source, 2 GiB address-space or
192 MiB evidence limits. The exact original command then naturally passed in
23.817 seconds: all fourteen original tests, 13,206 public pairs and 66,549 real
native calls. Both prior failures remain retained.

`ba4b-component-execution.json` indexes those actual outcomes and the original
failed sequence. `ba4b-comparison-terminal-receipts.tar.gz` preserves the actual
reports and selected command streams; the complete bound observation payloads
and physical binary artifacts remain in the recorded ROG evidence directory.
The adjacent invocation sources retain the exact commands used. These component
passes do not turn skipped file-update/effects successors or the full platform
matrix into a passing result.
