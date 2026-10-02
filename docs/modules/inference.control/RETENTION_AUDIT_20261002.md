# inference.control retained-history audit, 2026-10-02

## Source, owner and scope

The repair is based on ordinary V2 source
`ef2d2d14e36fb694f9fc7bbdf58c177010f9832a` in
[PR #1304](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1304).
The retained-cut source commit is `4c43a577bd0ffce567312604093f3404eb00eeda`;
[scoped validation and retained logs](../../../qualification/inference-control-audit/retention-20261002/VALIDATION.json)
describe the executed scope and its limits.
`DurableInferenceControl` remains the only request/reservation/receipt writer;
`NativeJournalWriterActor` remains its product mailbox. Provider awaits remain
outside that actor. There is no second journal, owner or execution engine.

The paired [runtime audit](../runtime.codex/INTERFACE_AUDIT_20261002.md) records
the divergent runtime/integration compositions and pending final-send bridge.
Source readiness and the CLI's signed-plan composition do not establish full
product execution, selected-host qualification or release.

## Reproduced defect

Two actual-source baseline regressions failed before the fix:

* Truncating the live journal to zero did not prevent an identical reservation
  retry from receiving the cached successful acknowledgement.
* Replacing valid journal history with different, same-length request identities
  did not prevent a new reservation from being appended and acknowledged. Reopen
  recovered the substituted identity and forgot the original one.

An exclusive cooperative writer lock does not detect an administrator, another
process bypassing that lock, or storage corruption changing retained bytes.
Additional review reproduced checkpoint permission changes and active-journal
read/write permission loss that left live acknowledgements possible while reopen
failed. No automatic byte restoration is used as a repair.

## Implemented retention boundary

`retained_journal.rs` streams the complete active journal and its current
referenced checkpoint through the retained descriptors. It checks exact byte
count, EOF and SHA-256, regular-file/path identity, and required private Unix
read/write permissions. Windows uses metadata-only handle identity queries,
avoiding an independent data read through its mandatory file lock.

Every cached positive acknowledgement verifies the current retained cut. Every
new write verifies before append and again after flush/sync before publishing
the staged record. Invalid bounded inputs can reject before the scan. Verification
results are not cached across operations. Integrity or uncertain I/O failure
poisons the live owner, including retries; restoring old valid bytes does not
clear that poison. Explicit inspected reopen is required.

Compaction validates the predecessor, prepares and syncs archive/checkpoint and
replacement generation, rechecks the predecessor immediately before rename,
syncs the parent directory, and verifies the replacement/current checkpoint before
publishing the new state. A failure after rename retains poison. The stable
sidecar writer lock and existing schema/wire formats are unchanged.

The active journal and current checkpoint are each capped at 64 MiB. Live scans
use a 64 KiB buffer and cost O(active-journal bytes + current-checkpoint bytes)
under the single owner. Mutation uses pre-append and post-sync scans; cached ACK
uses one scan. Checkpoint decode retains its separately bounded allocation.
This is neither a constant-time acknowledgement nor a throughput improvement.

## Proof boundary and pending qualification

The current checkpoint contains the state needed for current replay. Historical
predecessor archives are not traversed by this live check; archive retention,
transfer and independent rollback witnesses remain separate obligations.
A valid replacement made before a plain reopen cannot be distinguished without
an independently retained anchor. These checks do not provide one.

Unix live-tampering tests cover truncated and same-length substituted journals,
byte-identical inode replacement, checkpoint deletion/truncation/substitution,
permission drift, poison surviving restoration, interrupted compaction and reopen.
Windows byte locks prevent the same live-tampering test technique. Windows source
cross-compilation is separate from Windows runtime evidence. The current metadata
comparison uses 64-bit volume/file IDs; ReFS's stronger identity requirement and
selected-host ACL/locking behavior remain unqualified.

The unchanged unoptimized original byte-budget test timed out at its 60-second
limit during full-history hashing. A same-source optimized diagnostic passed all
97 then-selected tests (one original soak ignored), including that case in 3.43 s.
At a 63 MiB prefix, local owning submit/release took 3.74/3.78 s unoptimized and
98.7/100.6 ms optimized; a 1 KiB prefix took 25.98/11.21 microseconds optimized.
These intermediate measurements isolate a substantial profile-sensitive cost;
they are not final-candidate receipts, a target-host SLO or evidence that the
existing 1024-identity/16-generation maintenance soak passes. Final verification
and source hashes are recorded separately with the qualification evidence.

The final normal `just test` invocation, after persisting a narrow
`profile.dev.package.sha2` optimization, passes 152 tests: 99 inference-core and
53 type/hash/canonical-vector cases, with the one original soak ignored and no
retries. No command-line optimization override is required. Core remains in its
normal debug profile; only the existing SHA-256 dependency is optimized. This
preserves digest/wire semantics and leaves release settings, limits and test
deadlines unchanged. The final 63 MiB local owning submit/release measurements
were 91.1/91.4 ms. Scoped strict Clippy and Windows cross-compilation pass; the
Windows check retains two pre-existing non-Unix unused-parameter warnings.

The original hosted V2 maintenance source-head artifact recorded 206 test passes,
but failed global implementation maps and strict lint in `hepta-operations`
(`connect_with` SQLite-shim violations and a collapsible-if). The native-host lane
recorded 65 worker tests, compaction/tamper cases and process/recovery cases, but
also failed its aggregate gates. Local scoped repair results do not replace those
exact-head/base-merge gates or the separately recorded 600.244-second soak timeout.

Production implementation, product execution, target-host qualification,
independent acceptance, activation and release remain false. The subsequent
[guarded-send stage](../runtime.codex/GUARDED_SEND_AUDIT_20261002.md) addresses
final-send deadline and transport queue cancellation separately. The ordinary
Agentd durable handoff and server generation fence remain pending; none of these
are implied by this retained-history patch.
