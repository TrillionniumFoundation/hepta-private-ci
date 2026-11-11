# MEM continuation: native withdrawal repair and context-delivery control

## Decision

**Scientific acceptance: HOLD. Production adoption: false. Action: NoUpdate.**
All ten original adoption blockers remain open. This continuation adds zero scored
memory-benefit actor episodes and zero real-model calls. The native withdrawal
defect is reproduced and repaired in [draft PR #5972][owner-pr]; its green native
validation passed 19 executions covering 18 unique cases, with no failures or
retries. The independent delivery control passed seven unique native cases, including
the old default API, with unchanged source after scoped fix.
These results do not establish retained-experience benefit on unseen tasks.

## Established evidence

| Evidence | Retained result | Interpretation |
| --- | --- | --- |
| MEM6 fixed-public working-state retention | bounded 30/84; current_only 28/84; 2 wins / 82 ties / 0 losses; 16 initial no-ops per arm | 20 source groups; initially incorrect cases 14/68 versus 12/68; source-weighted difference +0.10; prespecified one-sided 95% source-bootstrap lower bound 0.0. The positive lower-bound gate was not met. |
| MEM6 selector replication | public_rule 21/54; frozen_neural 13/54; 9 wins / 44 ties / 1 loss; 10 initial no-ops per arm | 14 different source groups. Retain public_rule as the fixed research control; this is selector evidence, including one public image-only bypass. |
| MEM6 fresh-process mechanism suite | 18/18 scenarios; 18 new consumer processes following three exited writers; zero model calls | Same-authority persistence and read-to-file mechanisms; no measured unseen successor-task benefit. |
| MEM6 archive recovery and publication | Original 61,412,948-byte archive; 10,365 restored files; second-host verification and later complete 128-part publication [R7] | File-byte recovery is closed in its recorded scope. Original owner, authority, runtime dependencies and real effects remain unrecovered. |

The two MEM6 actor cohorts contain 276 episodes over 138 paired cases and 34
allocated source groups. Their disjoint interventions are not pooled into a
memory-effect estimate. MEM5 remains historical evidence. Original failures,
no-ops, bypasses and unknown observations retain their original labels. [R1–R3]

MEM8 has separately recorded native bridge/isolation/regression and consumer
package passes. Each belongs to its tested source and selected scope. The
original ordinary-provider attempt remains 0 passed / 1 failed, with one logical
turn admitted and no settled terminal; physical provider request count remains
UNKNOWN. Healthy later GETs and an empty bounded journal query do not settle
that turn. [R3]

The CI v13 checkpoint records source
`189711e3563ea13a5328d52e99a286f082045b98`, tree
`e253b99e0a5c3b3a680569da0d224fabff0781ba`. Blocking run 43002359918
attempt 1 ended with 23 successful, 10 failed and four skipped jobs; aggregate
jobs are not extra tests. The MEM run passed its 11 memory and six Agentd cases,
then stopped at an incorrect JUnit path before the remaining stages. This is
partial engineering evidence, not a passed required-CI gate. [R4]

The later Blob-size retry, run 43002359918 attempt 2 / job 130483156553,
failed at Fence 0.10.0 readiness with `local_control_inventory_unavailable`.
Checkout and blob-policy steps were skipped. Its retained original log is
3,859 bytes, SHA-256
`6cb0c5b96b73f48dfb3f86098951207e42ffdea9015b348f5d289ec3ce88448b`.
This does not measure blob size or test either proposal below. The exact [`CI_BLOB_RETRY.log`](./CI_BLOB_RETRY.log) and
[`CI_BLOB_RETRY.json`](./CI_BLOB_RETRY.json) must accompany this later observation. [R6]

## State layers

| Layer | Boundary | Evidence needed |
| --- | --- | --- |
| Within-task working state | Current observations and transient candidate state; reset at each task/session or source boundary | Paired actual deliveries with retention alone changed. current_only still receives the current observation. |
| Cross-session episodic/source memory | Retained authorized evidence with source/namespace, version, provenance, dependencies and current withdrawal frontier | A writer exits; a fresh reader/session retrieves through the real owner path and demonstrably uses eligible retained content on a later task. |
| Slow semantic/skill consolidation | A separately versioned candidate derived from authorized experience | Frozen exposure/training lineage, held-out comparison, downstream use and adoption/rollback evidence. No such component is currently qualified. |

## Native predecessor withdrawal: reproduced and repaired

A source snapshot can remain accepted by its external verifier after the
original native owner withdraws a prerequisite. The old import path checked
native correspondence, but a fresh explicit read could still return the
dependent record. The original red fixture demonstrated this through a real
Agentd Unix socket: after source-a was withdrawn, the fresh read still returned
`The route evidence says blue.` with `read_allowed=true`. Compilation completed
and the intended fresh-read rejection assertion failed. Existing broader
retained-context freshness checks are not presented as a newly reproduced defect.

The repair shares the existing native correspondence check between import and
reads. It validates the complete retained acknowledged receipt before and after
fresh reads and retained-context revalidation, including bounded active and
retired slots absent from retrieved items. It checks native source/memory
revisions, lifecycle, scope and citation through the original writer in a
read-only transaction. External verification and current-observation checks
remain intact.

A stale mapping rejects this explicit source view until valid original-owner
reconciliation. It rejects the complete stale view rather than silently returning
an unrelated subset. The API requires a complete receipt retained from an
acknowledged import; it does not authenticate an arbitrary supplied roster,
perform physical erasure, reconcile the original deployment, or grant external
effect authority.

### Native results

| Original phase | Executed tests | Outcome |
| --- | --- | --- |
| Red: original source plus regression fixture | 1 | 0 passed / 1 failed; 788 unselected; intended fresh-read assertion; zero retries |
| Green: exact regression | 1 | 1 passed / 0 failed; 788 unselected; zero retries |
| Green: Agentd episodic/source-read selection | 7 | 7 passed / 0 failed; includes the exact regression again; zero retries |
| Green: memory episodic selection | 11 | 11 passed / 0 failed; zero retries |
| Same-source CLI build | 0 | Exit 0; binary retained for applicable fixtures |
| Scoped `just fix` | 0 | Exit 0; source unchanged |

**Green aggregate: 19 executions, 18 unique case IDs, zero failures.** Each phase
retains its command, source before/after, raw log and applicable JUnit. Builds,
formatting and fixes are not counted as tests. A built CLI does not establish
that every fixture consumed that binary; actual executable routes stay distinct.

| Identity | Value |
| --- | --- |
| Frozen base commit / tree | `189711e3563ea13a5328d52e99a286f082045b98` / `e253b99e0a5c3b3a680569da0d224fabff0781ba` |
| Red local commit / tree | `98ada254cb89b1d3604ddcdadc74f08482e7fb5c` / `5d1bb704e79421455cf30ddfe49527edbc6007f7` |
| Green tested local commit / tree | `801a79f7b11f0c7fe1d6e2354225d686bae4325b` / `3e87a1e1e6d17191f9342e276d70cc0187dfb6b7` |
| Published source commit | `2e0f6ff4525a02143f700dee70309ef9b6169398`; same complete green tree, distinct commit identity |
| Red runtime job | `1a1ca89c499-2564-6a3`; native command receipt exit 100 |
| Green runtime job | `1a1ca9ada6a-2564-735`; runtime terminal succeeded, exit 0, complete durable output |

The red native command terminal, raw failure and JUnit are known. A later root
runtime-status probe failed at SSH transport; no additional runtime terminal
envelope is invented. The green runtime terminal is retained independently.

Root reconstructed both complete Git trees from the frozen base and published
postimages. It read the archives back from GitHub, verified every member and
hash, and reconciled raw summaries, JUnit case IDs and source cleanliness.
The final green source equals the pre-fix frozen source.

| Archive | Bytes / SHA-256 | Independent readback |
| --- | --- | --- |
| [owner-red.tar.xz](./owner-red.tar.xz) | 24,756 / `6bf2240b48d8e1e151ba6448871059452de35186f78e1f80617d528480926a8e` | 20 regular members; 19 member-manifest entries verified |
| [owner-green.tar.xz](./owner-green.tar.xz) | 50,740 / `b6a8b820e987c9c87bd64c9c394d554ed534ab88fe639058238c400afde3a235` | 75 regular members; 74 member-manifest entries verified |

See [red audit](./ROOT_RED_READBACK.json), [complete green audit](./ROOT_OWNER_READBACK.json),
[terminal metadata](./OWNER_GREEN.json) and [formatted manifest](./OWNER_FORMATTED_MANIFEST.json).
Setup failures and read-only transport errors remain in [SETUP](./SETUP.json),
the original archives and metadata. One timed-out observation was reconciled by
its original operation identity; it did not trigger another native execution.

## Explicit context-delivery intervention

[Draft PR #5977][delivery-pr] adds `NativeContextDelivery::{Attach, Withhold}`.
Both modes perform owner retrieval, bounded serialization, retained
owner-context digest, final revalidation and final-use authorization. Withhold
suppresses only the explicit `additional_context` attachment and retains the
owner evidence needed for current-source checks.

Delivery is bound into durable admission before connection. Withhold uses its
own intervention domain, while Attach and existing run APIs retain their legacy
identities. Exact replay must not repeat a provider request; changing delivery
mode while reusing a logical request ID must conflict.

The native fixture uses a restrictive explicit-context-only profile, two fresh
threads and a bounded observer inside the actual child. It compares stable
retrieval support, checks the physical mock Responses body and each complete
owner digest against its own journal, and exercises exact replay, a changed-mode
conflict and withdrawal before final use. Clock-dependent full digests are not
falsely required to be identical across reads.

**Withhold is a delivery intervention, not complete memory-off.** Whole-memory
off/on still needs isolated history, tools, implicit memories, original-owner
binding and a prospectively frozen successor-task protocol. A mock provider
fixture is not a real-model benefit measurement.

### Original zero-execution attempt

The first driver used source-file names instead of the actual Rust modules in
its Nextest expression. Compilation succeeded, but it selected no tests:
**0 executed, 52 skipped, exit 4**, UUID
`4c08fe7a-116b-41a9-b71b-fc92852f38cc`. This is a selection failure, not a compile
failure, assertion failure or pass.

Source remained clean at local commit
`542443191af06facb891f58fecb8bfe7a925c893`, tree
`adcc19bcdd31c10781e57296730d9c81869c3d98`, parent 189711e.
Runtime job `1a1cabcb509-2564-83f` ended failed/exit 1. Its full original archive
is 32,140 bytes, SHA-256
`a8ac659ee5768b17dc86b16cebd91506d995a27fada3ca33679dc271256de380`,
Git blob `6a460db9a7394b84a13d5e71d5cf447fc5e8c2e8`.
The formatted six-file manifest is blob
`2bb9922d4231e81589552b0d88e9a3bd7cb854d3`.

The corrected filter is
`test(native_app_server::context::tests::) or test(native_app_server::control::tests::)`.
It selects two new cases and four existing controls on the same frozen source.
The first actual selected-case execution passed 6 / 0, with the exact expected
case set and zero retries. Scoped fix exited 0 and left source unchanged.
Root independently read the complete successful archive back from GitHub and
verified 42 regular members, 41 member hashes, all six JUnit cases, both phase
raw logs/receipts, final source postimages and the durable succeeded terminal.
See [delivery-native.tar.xz](./delivery-native.tar.xz),
[terminal metadata](./DELIVERY_NATIVE.json) and
[root audit](./ROOT_DELIVERY_READBACK.json).

The existing old-API case
`native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`
then passed its first execution: 1 passed / 0 failed, 51 unselected, zero retries.
It uses the normal host profile and old Attach API. The complete source, original
fixture blob and native test-artifact hash stayed unchanged; the six earlier
cases were not repeated. Root independently verified all 18 regular archive
members and 17 member hashes, its fresh one-case JUnit, raw receipt, source
identity and durable succeeded terminal. See [legacy archive](./delivery-legacy.tar.xz),
[terminal metadata](./DELIVERY_LEGACY.json) and [root audit](./ROOT_DELIVERY_LEGACY_READBACK.json).

**Delivery aggregate: 7 executions / 7 unique cases, zero failures and retries.**
The initial selection failure remains 0 executed cases. These native fixtures
use loopback mock Responses servers and the test executable via `current_exe`;
no separate CLI consumption or real-model benefit is claimed.

| Delivery evidence | Identity |
| --- | --- |
| Corrected six-case runtime job / Nextest UUID | `1a1cac77be5-2564-862` / `4b827bc0-efee-4e66-b629-d3e1399bea8d` |
| Legacy one-case runtime job / Nextest UUID | `1a1cacd57f0-2564-878` / `6dc5d5c9-4f10-472a-9d28-520654d27e89` |
| Six-case archive bytes / SHA-256 | 32,796 / `536eaef2efa46aa808ba05254e47ff3ffca3309037fbb14ba8227a44fec71c8e` |
| Legacy archive bytes / SHA-256 | 12,236 / `3857e409a3d2f6b55036448af93be50f36822b08cd6bc2207d57a98af9cb6ed8` |

Published commit `b03214c5c2e2bf4499c211227e43cc22f8663d95` has the same complete
adcc19b tree as the tested local commit; the commit identities remain distinct.
Both source proposals are documented in [SOURCE_PUBLICATION](./SOURCE_PUBLICATION.json).

## Source composition and hosted CI

Both proposals are independent changes based on frozen 189711e. While native
qualification ran, target [PR #5935][base-pr] advanced through 6ce7878 and c842e99
to `9bd2f589debdba4a93baa363817c3669cb103721`, tree
`c77785ecb368c44ea699769001a47402c9f50591`.

Root checked ancestry and all 13 affected paths: all nine existing files retain
the same blobs as the frozen base, and all four new paths remain absent. See
[BASE_ADVANCE](./BASE_ADVANCE.json). This supports the narrow proposed diffs and
conflict assessment; it does not transfer native component results to the newer
full composition.

For owner PR #5972, [MEM workflow 43024095069][owner-mem-ci] completed with all
three jobs successful, including native owner, isolation-feature, protocol and
scoped-fix steps. Broader blocking CI has observed failures, while other checks
remain in progress. See the [CI observation](./HOSTED_CI.json) and
[exact failure attribution](./ci-owner/CI_FAILURES_OWNER.md). The complete
HOSTED-CI gate is not closed.

The current Blob-policy job again failed at Fence before checkout. Windows
shard 4 failed a specific hard-link refusal-diagnostic assertion; earlier
attempt output also retains remote-environment and subagent-hook failures.
Shard 2 failed two ordinary-host delete controls before their restricted
operations, followed by three poisoned-mutex failures. Its older outside-delete
case is explicitly successful in this run. The six relevant test files are
unchanged between current base 9bd2f58 and the tested merge ddc505e, but three
differ from the independent native base 189711e. This is source attribution,
not proof of baseline reproduction or a globally green owner patch. Original
logs, source comparisons and step metadata are retained in
[owner-ci-failures.tar.xz](./owner-ci-failures.tar.xz).
Historical CI failures above retain their original source and scope. The
[bounded Fence diagnosis](./CI_DIAGNOSIS.md) uses official source and records no
security-policy, allowlist or workflow weakening and no original CI rerun.

## Next experiment order

1. Carry the now-verified bounded mechanisms into the intended composition and
   qualify that exact source; complete original owner/provider/source binding
   needed by the intended ordinary entry point. Retain the uncertain
   original provider turn and reconcile it by its original identity.
2. Freeze the complete new-source protocol, exposure roster, model, public
   selector, history, budgets, evaluator and analysis before outcomes. The first
   task contrast is memory-off/on with the public selector fixed: both arms
   receive the same predecessor experience and successor task; only eligible
   retained content differs. Use a fresh reader/session after the writer exits,
   with no prior chat or working-state passthrough.
3. Run separate retrieval, association and delivery interventions. Retrieval-off
   keeps persisted state/frontier fixed; association-off holds retrieved support
   and delivery fixed around a real pinned head; delivery-off holds retrieval
   work/support and final checks fixed while withholding the actor attachment.
   An absent association head is unavailable, not a successful ablation.
4. Retain exact KV, BM25/RAG, ordinary ICL and uniform experience replay under
   the same authorized history and frozen context budgets. Provide meaningful
   competing records and actor-visible keys. Uniform record sampling is a read
   baseline; it is not optimizer replay. Keep the existing optimizer-replay
   baseline until a separately matched training study supports replacement.
5. Cover authoritative fact updates, withdrawal and dependent invalidation,
   old snapshots under current authority, cross-document association, similar
   queries requiring different source-specific workflows, distractors and
   unanswerable abstention. Record retrieval, selection, actual delivery, actor
   behavior and final effects separately; removal/replacement counterfactuals
   must connect retained content to the successor outcome.

This is execution order within a prospectively frozen plan, not permission for
outcome-dependent cohort changes. The existing W thresholds stay unchanged.
E requires its own pre-execution protocol and has no approved numeric source
minimum or allocation inherited from W. The current catalog offers at most
16 residual candidate groups, all with current exposure UNKNOWN; verified
unseen capacity is null and no new source is admitted. [R3, R5]

## Evidence references

- [R1: MEM6 results](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/39d895547fa7a50c45d580d3e30236c87f99d322/qualification/memory-cell-mem6/run-001/RESULTS.md)
- [R2: Read-freshness repair and second-host file recovery](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/adef61556284cc5b58c4f23a33d7c8455e821c3f/qualification/memory-cell-mem7/read-freshness-20261110/RESULTS.md)
- [R3: MEM8 original-owner blocker ledger](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/cb54f618f0408c314b1c367a5256ea185165c354/qualification/memory-cell-mem8-owner/run-001/BLOCKERS.json)
- [R4: CI checkpoint v13](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/c6bdeeac20a8ff1c79a70209df9e9b85f51cc6a2/qualification/memory-cell-mem8-ci-followup/CHECKPOINT_REPAIR_V13.md)
- [R5: Frozen MEM6 acceptance requirements](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/39d895547fa7a50c45d580d3e30236c87f99d322/qualification/memory-cell-mem6/ACCEPTANCE.json)
- [R6: Original Blob-size retry job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43002359918/job/130483156553) — retained log and step readback are identified above.

- [R7: Independent complete 128-part archive copy receipt](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b66d74d4a61b15f3d9e1eb3b5ddfa251777ee4c1/qualification/memory-cell-mem6/run-001/CLOUD_COPY_RECEIPT_20261111_ED353.json)

[owner-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5972
[base-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5935
[owner-mem-ci]: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43024095069

[delivery-pr]: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5977

Formatted source manifests preserve their creation-time phase labels. Current
completion status is given by the final terminal metadata and root audits above.
The two source proposals are independently qualified; this evidence does not
claim a joint combined-source qualification.
