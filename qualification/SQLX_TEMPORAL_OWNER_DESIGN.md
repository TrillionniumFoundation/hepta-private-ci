# SQLx source-bound engineering owner, inactive source design

This is an implemented but unexecuted source proposal. The two real database
controls and a command owner are written; no repository module has been imported,
no syntax/formatter/compiler/test/resolver has been run, and no workflow has been
installed. The original local design is preserved by name and digest. This new
version was reconstructed from exact actual-2fd GitHub sources after the local
execution environment became unavailable.

## Source and command ownership

The fixed source baseline is 2fd85fd8276a14b3166a4175009c84fb4f36cd73. The proposed
root SQLx feature change matches the previously reviewed one-line draft. Existing
production pool and transaction bodies and the legacy timestamp converter remain
byte-identical. Only crate documentation and one explicit cfg(test) module hook
are added to existing Rust library files.

The new runner imports the exact original hepta_ci_exec and hepta_ci_junit after
source pins have been checked. Each command uses original source identity,
create-exclusive command records, bounded raw stdout/stderr, WNOWAIT leader
reservation, final group signal, and one bounded final reap. It does not introduce
another process launcher, alternate reaper, shell callback or automatic retry.
SIGTERM is converted into an interruption while the original owner holds a child.

The runner records a single elapsed scope from its entry, including source
checks, command preparation, compiler and metadata commands, the expected
compiler failure, native execution, collection and postchecks. Every child gets
the minimum of its admitted category cap and the remaining common deadline with
one second reserved for the original reap. Spawn, filesystem and signal syscalls
are not a hard real-time guarantee. The final record write is outside its own
elapsed timestamp; CI's whole-step observation must be retained separately.
No existing research or native budget is reused.

The input JSON is inactive. Parent/tree, generation source/run/artifact, accepted
four locks, two fixture graph digests, full twelve-consumer target digest,
acceptance receipt and a numeric budget are null. Inactive admission fails before
loading the original owner or dispatching a command. A new fixed first-open
owned Draft and attempt 1 are required even after source-bound activation.
The 3600-second source ceiling is a proposed maximum, not an execution grant.

## Twelve consumer compilation

Cargo check --locked --all-targets selects these exact existing packages with
their unchanged default/production features:

codex-cli; codex-hepta-agentd; codex-hepta-authbus; codex-hepta-automation;
codex-hepta-evidence; codex-hepta-matrix-store; codex-hepta-memory;
codex-hepta-operations; codex-hepta-runtime; codex-hepta-shadow-qualification;
codex-state; codex-thread-store.

The original source metadata declared 88 targets among these packages. This is
not a test count, nor a claim that build scripts, test=false targets or
required-feature declarations all executed. The runner records the complete
actual target objects and compares their normalized digest to a future accepted
roster. No --all-features flag is supplied. Qualification-only required features,
including Agentd's h4_persistent_writer feature, are not enabled by this owner and
are explicitly listed as declarations without claiming compilation.

The selected platform is aarch64-unknown-linux-gnu with the actual 1.96.0 Rust
toolchain. Other platforms require their own source-bound engineering scope.

## Three compile capability comparisons

The default and explicit-compatibility fixtures each have their own Cargo.toml
workspace root, accepted Cargo.lock and metadata graph. Their Cargo target
directories are distinct, and the runner never combines their -p selections.

All original root patch tables are retained in both fixture manifests. Only
local patch paths are re-anchored to the original codex-rs tree. The runner
compares normalized patch tables and exact SQLx/Chrono declarations before
dispatch. Dependency-workspace patches are never assumed to propagate.

The default scalar fixture compiles the original pool, destination transaction
and read-barrier signatures and i64/Option<i64>/String/Vec<u8> codec traits.
It does not execute any of these functions or create a production database.

The default negative fixture requests only DateTime<Utc>: Type<Sqlite> at line 7.
The original command must terminate with compiler exit 101, one exact E0277
diagnostic, the accepted package ID and target, the pinned source span and no unrelated
plain error. Cargo may omit its redundant terminal wrapper in JSON mode; if that
wrapper is present it must exactly name this package, bin and single error. Two full diagnostic spellings differing
only by the compiler's Type-path qualification are accepted. Dependency errors,
other obligations, timeouts, skipped builds or a mixed failure cannot substitute.
Its original command record stays failed. A separate interpretation records an
expected exact trait refusal.

The explicit-compatibility fixture requests upstream SQLx chrono and compiles
Type, Encode and Decode for Chrono. It retains Chrono and proves only the explicit
downstream capability path. The runtime also compares both fixture graph digests
with separately accepted originals and checks the intended SQLx feature closure.
No fixture lock or graph has yet been generated, copied, or fabricated.

## Twelve database and recovery controls

The native invocation uses original just test, the local profile, zero retries,
one test thread, exact binary_id/name filters, and the fixed ten original names
plus the two new state names. Original run-nextest already supplies --no-fail-fast;
the owner does not duplicate that flag.

The original fresh-JUnit collector retains and source-binds the real report.
The new owner independently requires exactly the same twelve pairs in JUnit and
raw ordinary PASS lines, with no duplicate, extra, failed, skipped, flaky or rerun
case. Collection is not counted as another native execution. A failed native
command is not converted to success, and its collection can retain failure
evidence before the overall scope refuses.

## Remaining Root-owned prerequisites

1. Independent source review, syntax/format handling, and final pin updates.
2. A source-bound generation design for the changed root capability and both
   independent fixture locks/graphs. Four actual locks and generation evidence
   must be accepted; none are handwritten.
3. Bind the exact accepted parent/tree, all original generation identities,
   normalized graph and consumer-target digests, and acceptance receipt.
4. Choose a new engineering budget and install a fixed CI workflow with only
   contents:read, the named owned Draft first-open guard, source-head checkout,
   original tool setup and artifact retention. This capsule deliberately does
   not contain an unreviewed CI workflow.
5. Activate only a reviewed new source version. Failed or cancelled attempts keep
   their original records and are not restarted by this owner.

The accepted original native25 and failed #7108 nine-control attempt confer no
qualification on this source. There is no global Chrono, A/B training, production
authorization, FinalUse, performance, or settlement claim.
