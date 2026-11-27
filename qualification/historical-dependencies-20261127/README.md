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
