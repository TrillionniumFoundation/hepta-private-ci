# Fixture identity and PSEC observation records

This layer reads two bounded records added to the existing legacy test. It does
not add a Rust test, native command, retry, workflow, permission or timeout. The
original two test identities, eight controller commands, 20-minute job,
30-second by two nextest timeout, one test thread and zero retries remain intact.
The original factory and legacy assertions still determine the native result.

The source stages remain separate. The fixture stage adds an ordinary TokenUser
grant only to a new, empty, task-owned temporary root before its children exist.
That ordinary identity premise also applies to the outside and `.git` children;
the existing restricted execution must still deny those original negative
controls. The PSEC stage only queries two optional exports in the parent test
process. It creates no environment, attaches no policy and launches no child.

## What the parser verifies

`HEPTA_LEGACY_FIXTURE_ACL` has exactly two records sharing a 16 KiB limit,
including prefixes and newlines. Their order must be before and after the owned
fixture grant. Both descriptors must describe an ordinary, non-reparse directory
with a non-null DACL containing only the allowed ACE representation. Bounds on
descriptor, DACL and ACE sizes are checked. Each descriptor must carry the DACL
present bit, and its DACL must fit after the 20-byte self-relative header. The
after record must retain the
exact same owner, group and attributes and attest the complete DACL readback. It
must contain the fixed inheritable TokenUser full-access ACE. A claim that the
raw descriptor is unchanged must agree with every visible snapshot field.
Role labels do not reconstruct hidden SID bytes; equal redacted summaries alone
do not prove raw identity or raw descriptor equality.

`HEPTA_PSEC_SUPPORT` has exactly one record within 4 KiB, including prefix and
newline. The actor, zero create/close/child counters, exact field types, symbol
presence and query presence must agree. HRESULT, the full unsigned 64-bit support
output, BOOLEAN output and version fields are retained. Output validity must
match the exact raw return convention used by the reviewed Rust source. Missing
DLLs or exports and failed query results remain observed unavailable or unknown.
Unsupported versions remain explicit results. Unknown support bits are retained
without inferring their meaning. Module-release failure is retained separately.

`LOAD_LIBRARY_SEARCH_SYSTEM32` restricts the search, but an already loaded module
with the same basename may be reused. This observer does not measure the module's
actual path, signature or file bytes. It therefore records
`module_file_identity_measured: false`. No support result qualifies a sandbox
policy or proves a usable PSEC backend.

Each parser rejects malformed, missing, duplicate, oversized, wrongly typed or
internally contradictory records. JSON duplicate keys are rejected. Only records
before the first nextest summary in each stream are considered, so failure
recaps are not counted as new observations. ANSI and nextest indentation are
handled without changing the retained raw log. An unknown observation adds a
report error; it never replaces the original native or Clippy exit code.

## Existing evidence remains distinct

The runner adds one import and one observation call. Removing those two additions
must recover the entire original runner byte for byte, including its original
factory and child-token verifiers, source-before/after checks, exact selected
binary hashes before and after the native command, and first-nonzero selection.
The source inventory already includes the complete Windows crate and this
qualification directory, so no source scope or original observer pin is changed.

The original 2c6 run had strict Clippy exit zero and two native failures. Replaying
its archived logs through the unchanged verifier must still retain those two
failures. The old run has neither new record type; the new parser must mark those
observations unknown rather than supplying synthetic measurements. Synthetic
parser controls are separate from the unchanged child-token controls and from
every Windows execution. They do not establish the new fixture or query result.

This candidate has not run on Windows. The original factory outside-delete
failure and the observed legacy results remain open. A successful ordinary-user
setup, a complete record or a support flag cannot turn either original native
assertion into a pass.
