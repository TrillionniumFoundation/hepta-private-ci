# Root Source durable refusal qualification

## Candidate and status

This stage follows `e69beef571bd7ca7b3d70f450dc8998bf171d248` on the isolated
`codex/learn-fence-ai395-20261112-ff41` branch. It protects the Source pin and
Source handoff components originally published on `106f5e41f2ff8421c5aad10eeb746d453ed00563`.
It does not contain the lost, unpublished Root RunStart retention implementation.

The seven new UID0 parent tests are written and enrolled, but have not executed.
The last observed development executor had UID 1000. The current follow-up
postimages have not run rustfmt, Python source QA, the full caller checker,
Clippy, or native tests while that execution service is unavailable. A lexical
preview and exact old-row comparison were performed in the orchestration
runtime; neither is the authoritative Python verifier. The generic locator
dependency uses the exact two blobs from `9e5fe517a94ca7acb285537648f97b378fbb3752`;
that separate tree's test result is not inherited by this composed candidate.

No A execution, authenticated Decision/Outcome, learning admission, independent
evaluation, CURRENT adoption, later C task, or whole-system cold restart is
qualified by this stage.

## Failure and repair

Previously, opening or reading a damaged primary could poison only the current
handle. Fencing then needed to decode that same primary. A process could exit,
the primary bytes could be restored, and a new handle could lose the refusal.
That was identified by source review; no native failure from the new UID0
counterexamples is claimed here.

The independent Root refusal record has a closed SourcePin/SourceHandoff kind,
the full original target, a checked monotonic attempt, and Ready/Armed/Refused
phase. Its owner key uses the primary slot's scope, so changing a target cannot
select a second marker for the same slot. Fresh registration writes Armed
before any primary IO. Existing operations compare-and-set the complete Ready
record to the next Armed attempt before opening or reading primary bytes.
Success clears only that exact attempt after its entire action and postchecks.
A failed action, unwind, or process exit leaves Armed. Recovery does not create
a missing marker or finish an interrupted attempt.

The Source capture arm encloses the original Root publication context, including
its returned postchecks and both actual physical Source observations. The
extracted record helpers retain the original Root, target, publisher, mode,
descriptor-custody, CURRENT and FinalUse checks. The first-capture failure can
therefore remain refused even when no primary pin was ever created.

Handoff replacement includes the exact prior read, primary CAS, exact replacement
read, and its actual transport callback in one arm. After the original ACK
context has returned successfully, Finalized is read back and the actual pin
digest and original receipt/session deadline are checked before Ready. The
transport does not recursively call same-kind cold recovery during that arm.
Cold Finalized remains data, not a historical learning grant or final-reply
delivery receipt.

All exposed operations on one helper share a nonblocking gate. Busy refusal
returns an error before reading the marker or changing that handle's poison.
Across handles, the protected store's original per-owner lock and exact attempt
CAS prevent one handle from clearing another attempt. Refusal is persisted
independently before decoding a legacy primary fence. Existing exact refusal
is idempotent; it cannot be overwritten by later capture.

The guarantee requires the independent refusal history to remain intact. It
does not establish freshness after rollback of that marker or the whole Root
directory/host. A failure to persist or read the refusal record remains an
error; no storage failure is described as magically durable or mapped to
NoUpdate.

## Counterexamples and non-vacuous children

The pin and handoff tests first require a fresh child to open the same valid
primary and target. They then write and sync damaged bytes, require a new child
to refuse them, restore and sync the old primary, and require another fresh
child to continue refusing. The separate interrupted-capture test leaves no
primary to reconstruct.

The helper crash test exits inside the Armed action after the actual primary
open fails, before returning through any failure or fence handler. Its later
child confirms restored primary data is valid while the independent marker
still blocks recovery. Another case leaves a physically Finalized handoff
behind an unsuccessful final postcheck and requires cold rejection.

The original test draft used `module_path!()` directly as the libtest exact
filter and checked only the exit code. The current candidate removes the crate
segment and requires each child's phase-specific execution receipt as well as
exit success. That receipt is emitted and flushed only after its real
assertions; the intentional-exit child emits it inside the failing-read action.
A zero-test success or unknown phase cannot supply the receipt. This is a
source-identified harness repair, not an executed native result.

New exact UID0 parent names (private children are not independent roster entries):

- `authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_sequences_block_stale_cross_handle_completion`
- `authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_does_not_retrofit_old_primary_or_split_one_scope`
- `authority_host_service::generation_initial::data_refusal::tests::root_data_refusal_crash_during_failed_primary_read_remains_armed_after_restore`
- `authority_host_service::generation_initial::historical_source_pin::tests::cold::root_source_pin_physical_corruption_then_restore_stays_refused_across_processes`
- `authority_host_service::generation_initial::historical_source_pin::tests::cold::root_source_pin_unfinished_capture_cannot_initialize_after_restart`
- `authority_host_service::generation_initial::historical_source_handoff::tests::cold::root_source_handoff_physical_corruption_then_restore_stays_refused_across_processes`
- `authority_host_service::generation_initial::historical_source_handoff::tests::root_source_handoff_finalized_primary_before_failed_postcheck_is_not_recoverable`

## Closed callers and source guards

All 504 existing boundary entries remain present. Three change semantically:
the pin registration method's definition moves to its extracted record module;
ACK delegates its guarded CAS to the private replacement method; and
`open_finalized` has an empty product caller set because the actual handler
now does its exact readback inside the ongoing arm. A definition is not counted
as a product caller.

Six boundaries close fresh/existing/inspect/refuse and the two private pin
capture/record calls, producing 510 entries. Three protected rows follow the
real extraction and strengthened call order; two new rows protect the helper
and record module, producing 371 rows. All 867 unrelated boundary/protected
table blocks are preserved byte-for-byte (apart from insignificant table-end
blank lines in the comparison). Every old required boundary ID keeps its
position. The old forbidden marker sets are preserved. The exact CALLERS
SHA-256 allowlist entry changes; every other allowlist line, including retained
archive hashes, is unchanged.

The existing 21 Source capture/handoff source-test methods remain, with
assertions following the actual delegated guarded operations. Eight additional
methods reject missing arms, attempt/gate/binding weakening, unguarded primary
IO, cold initialization, replay of a started capture, premature context or
receipt completion, and zero-test child success. New closed-caller negative
cases also reject unauthorized helper and cold-recovery calls.

The native workflow retains all 23 original Root parents and appends these
seven, for 30 on this isolated branch. Exact JUnit roster matching, retries,
deadlines, failure propagation, and the original test commands are unchanged.
Integration must union independent branches' added parents, including the
Artifact readview parent, rather than replace this roster.

## Required validation

Run the original repository formatting and scoped lint commands, then the
authoritative Python source checks and full caller checker on a fixed tree.
Relevant focused source checks are:

```text
python3 -m unittest discover -s qa/b4-no-bypass -p test_exact_generic_function_order.py
python3 -m unittest discover -s qa/b4-no-bypass -p test_root_historical_capture_source_closure.py
python3 -m unittest discover -s qa/b4-no-bypass -p test_root_historical_handoff_source_closure.py
python3 -m unittest discover -s qa/b4-no-bypass -p test_root_data_refusal_source_closure.py
python3 scripts/verify_hepta_callers.py
```

Use the unchanged native workflow's actual UID0 parent command and collector.
Retain source/tree identity, raw command and exit status, fresh JUnit, and exact
parent names. Neither ignored tests on UID 1000 nor fixture metadata can replace
that evidence. AuthBus/RunStart signatures, physical Cell decisions, Ledger and
Observer outcomes, outbox acknowledgement, original publisher retirement and
a new recipient's authorization remain separate required joins.
