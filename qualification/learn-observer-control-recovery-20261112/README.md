# Original Observer control recovery candidate

This is a new recovery candidate on published base
`106f5e41f2ff8421c5aad10eeb746d453ed00563`. It does not reuse the unavailable
old cloud Observer commits or their earlier test results.

## Frozen source and actual checks

| Stage | Local commit | Published commit | Exact tree |
| --- | --- | --- | --- |
| Original producer / Config / State / UDS data wire | b67cb049ae5d579b09cf7d5c90283e59ac43ba5d | 55d3447f8af0fb1d4fb4687e8697185db4581221 | 503329b3245e6d4cae15152e4dbaa89dacbadcbc |
| Five real UDS cases and two protocol cases | 4945c98ac9008af1a5589ba0d353b29079c93fac | f59ba61abcca1f8428acb45e05b9e47d63d3a692 | ef7e8a45f8505913fc95bff30dfcc4689f2d5fae |
| Closed callers and source mutation checks | 41dd2778dd90d2d8f8c48ba28a70dbfa03957b90 | a8a1e66210a7ab3e2ab2b4a0f4a53f69c1af2760 | 241e8fb88ea0cc10f5d52a30092762e3faa72b14 |

Publication used the exact local blobs and verified each resulting Git tree.
Local and API commits differ in commit metadata; the mapped trees are equal.
The qualification files in this later documentation commit do not change Rust
or the caller manifest tested at the last row.

At 2026-11-12T06:07:24Z the clean guard tree actually passed:

- 16 source QA methods, including positive and mutation checks for eight
  relevant exact caller sets.
- All 379 protected-file rows in the unchanged verifier.
- The 511-entry privileged inventory's declaration equality check.

The complete repository caller scan was **not run**. The 511 inventory entries
are not 511 independently executed caller scans. The actual logs, commands,
exit codes, durations and source identity are retained alongside this file.
An MCP start acknowledgement timed out; the later actual frozen files and
completed logs established the result. No duplicate mutation was launched.

## Behavior this source connects

The same original producer Arc is installed with the actual Q24 Circuit,
transferred through Config into State, and selected by the existing private
control dispatch. Requests carry bounded canonical Outcome bytes and the
unchanged signed Observer evidence. They cannot supply an owner, root key,
replacement trust, activation capability or controller choice.

The adapter calls the existing original producer. That producer retains its
original signature journal, Ledger, witness, source checks, enrolled roles and
once-only append/reconciliation. Task success is not converted to a reward.
State checks current generation and readiness before and after submission.
An error after an append is uncertainty: it does not establish NoUpdate or
authorize re-signing, re-execution or a replacement observation.

The client entrypoint currently has an explicitly empty in-repository product
caller set. The UDS method is available to an actual enrolled Observer; these
source checks do not demonstrate a deployed independent Observer or evaluator.

## Pending execution and integration

The five UDS tests use a real committed engineering task, original file owners,
a real UDS server and explicit fixture keys. The protocol tests cover strict
wire shape and the existing frame bound. They have not been executed natively
on this recovery candidate. Required filters are
`test(original_q24_outcome_control_)` and
`test(q24_original_outcome_wire_)`, with zero retries and exact source identity.

The owned control JoinSet, typed drain receipt and Source-close companion are
separate Root work. Their merged postimage needs fresh formatting, compiler,
native and complete caller checks. The same invocation's source lifetime hook
must be retained when integrating the original-ledger installer.

The actual Root trust handoff and first-A Ledger FD loader are separate work.
Existing Dataset materialization still holds the original
`Arc<Mutex<LedgerWriter>>`; retained-source construction keeps those original
owners alive. That read side does not establish a cold O_RDONLY Ledger or an
independently retained Objective ACK.

This candidate proves no ordinary end-to-end Adopt, NoUpdate or whole
daemon-plus-Root cold restart. Their qualified counts remain **0 / 0 / 0**.
