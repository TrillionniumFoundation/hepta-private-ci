# Explicit SQLx temporal codec migration

Status: isolated source proposal. It has not been formatted, compiled, resolved,
tested, or published. Accepted source, generated locks, graph receipts, and a new
engineering budget are required before the proposed owner can run.

## Capability change

The root workspace stops selecting the optional SQLx 0.9.1 Chrono codec feature.
The public SqlitePool and Transaction types and the public Chrono-valued business
models remain. Therefore this is an explicit change to the implicit downstream
trait capability, not an assurance that arbitrary external DateTime<Utc> bindings
continue to compile.

Existing integer storage owners retain their own declared units. The state legacy
converter, connection factories, recovery refusals, transaction identity, atomic
commit guards, schemas, and history validation are unchanged. The proposal does
not add SQLx Any routing or infer that sqlx-core's internal Any feature exposes the
facade Any API.

## Callers that need the prior codec

A downstream application may explicitly select the upstream SQLx chrono feature
at the same accepted version. It must preserve its own patch and lock policy and
validate its schema and encodings. This keeps Chrono in that application's graph.
It is a compatibility path, not an advisory-remediation or dependency-removal
claim. Published consumers must use an explicitly announced API/capability
transition or remain on their previous release while migrating. This proposal
does not silently increment all workspace package versions.

Replacing arbitrary Chrono SQL values with time values is not a byte-compatible
substitution. The original SQLite Chrono and time codecs differ in accepted REAL
Julian input, text parsing, timezone rendering, leap-second representation and
date ranges. No production codec substitution is made here.

## Concrete engineering controls

The new state sibling module contains two real database controls using the
original SqliteConfig factory:

- Signed scalar seconds, milliseconds and nanoseconds, NULL and signed limits
  retain SQLite INTEGER/NULL storage through close and read-only reopen.
- Values read from real SQLite rows reach the unchanged legacy milliseconds
  converter. Fixed original outcomes include its threshold heuristic, negative
  input, NULL, and exact rejection of out-of-range signed integers.

The original ten storage, transaction, recovery and migration controls remain in
the explicit twelve-name native roster. No old qualification is inherited.

The compile owner selects the original twelve SQLx consumers with Cargo check
--locked --all-targets under their existing default/production features. It records
the complete target declarations separately from executed tests. Targets that
declare qualification-only required features are not counted as compiled merely
because they appear in metadata, and no qualification feature is enabled.

Two independent fixture workspace roots provide three compile comparisons:

1. The default workspace compiles scalar codecs and the original public pool,
   transaction and read-barrier signatures.
2. The same default workspace must receive the exact E0277 obligation
   DateTime<Utc>: Type<Sqlite> at its pinned negative expression. A dependency
   failure, syntax error, absent compiler, extra error, timeout or unrelated
   obligation cannot qualify. The original command record stays failed.
3. The explicit-opt-in workspace compiles Chrono Type/Encode/Decode. Its separate
   manifest, generated lock, metadata graph and Cargo target directory prevent
   opt-in feature unification with the default negative workspace.

The original root patch tables are forwarded into both independent fixture roots
with only their local relative paths re-anchored. Dependency workspace patches
are not assumed to propagate automatically. Actual generated fixture graphs must
be separately accepted; no handwritten or copied root lock is presented as a
fixture lock.

## Execution boundary

The proposed Python owner reuses the exact existing hepta_ci_exec and fresh JUnit
collector. It has fixed commands, a first-open owned Draft guard, exclusive
artifact creation, one shared admitted deadline, distinct fixture target
directories, source/pin checks before and after, and exact twelve-name XML/raw-log
agreement. It never retries a failed compiler or native command. The collector is
not a second native execution.

Inputs remain inactive, with null source/generation/acceptance/graph/lock/budget
fields. The source-only draft does not create a workflow or run a command.
Root must review the new source, arrange formatting and generation, accept the
actual four lockfiles and both fixture graphs, bind the complete consumer target
roster, and install the source-bound CI invocation before activation.

A future successful run would establish this explicit SQLx capability migration
on its recorded platform and source. It would not establish global Chrono removal,
arbitrary external codec compatibility, original A/B consent, useful training,
FinalUse, settlement, or any E1-E6 qualification.
