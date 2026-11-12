# Utility evaluation — original caller PASS; overall qualification remains HOLD

Checkpoint: 2026-11-12 16:43:15 UTC. Draft [PR #6203](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6203) still publishes **c0f78493f815780f68b9bf5e390a21314d79311f**, tree **313ee34febc8ccc54c611ab56286e289518c63cb**. Its full evaluator library and full caller gate passed. Its original focused native and source-closure gates failed. **No merge, production activation, real Adopt, completed real NoUpdate, or cold-recovery qualification is claimed.**

The next source exists as an immutable **PREPARATION/HOLD** object, **86dd56a930277e0d1aef3e475e35c2b5d60b43b7**, tree **383ab85c39ef9d848252ef5c25922d13d9fae6c6**, with 15,188 leaves. It has not replaced the PR head and has not run maintenance, compilation or qualification. Its exact parents are c0f followed by fixed upstream a96d1b821d10ed3d9e99dd06c5141f9f242ae318.

All previous evidence remains addressed. The [unchanged 1425-file README](checkpoints/README_1425FILES_OBJECT_CLOSURE_PENDING.md) preserves the prior checkpoint's then-pending object-closure validation. It retains the [1120-file historical checkpoint](checkpoints/README_1120FILES_C0F_FULLCALLER_PENDING.md) and all earlier observations. The present checkpoint contains **1486** addressed files; that count is an archive inventory, not a quality score.

## Exact published source and actual original gates

| Item | Actual observation |
| --- | --- |
| Published source | c0f78493f815780f68b9bf5e390a21314d79311f / tree 313ee34febc8ccc54c611ab56286e289518c63cb |
| Canonical commit | Original 1,293-byte body, SHA256 8aefa9dd70ba73ec646dbca656270509dfa3c1afed23b08e10330540a587d4d3; exact Git commit ID verified |
| Original fix / fmt | Both exit 0, no source difference; complete 14,851-file checkout observed before the original gates |
| Complete evaluator library | **163/163 actual cases PASS**, including all four required missing-evidence regressions |
| Focused native | **FAILED: 81 PASS / 28 FAIL**, 109 unique cases; original command exit 100, 960.6167 seconds, no overall timeout or output cap |
| Full / ordinary / Root native gates | **Not started** after the original focused failure |
| Source closure | **FAILED** at the original 600-second limit; wrapper 602.9541 seconds, exit 124, child -9; functional failures appeared before timeout |
| Caller self-test | Actual original command exit 0 |
| Full caller | **PASS_HEPTA_CALLER_CLOSED_SET**, original command exit 0, no timeout or output cap; **534 boundaries / 534 required IDs / 409 protected rows / 338 distinct protected paths / 6,597 Rust files** |
| Entire source-gate job | **FAILED**, process exit 1 because source closure failed; the full caller pass does not override it |
| Real authorized A → T → B → C → daemon / Root recovery | **Not established** |

The native job is **1a1d0137095-2564-1b21** with key **hepta-utility-36fa-native-c0f78493-v1**. The source job is **1a1d01a6652-2564-1b2d** with key **hepta-utility-36fa-source-gates-c0f78493-v1**. Both used c0f; gate inputs, deadlines and definitions were not edited during those runs. Earlier e8 results and preparation checks do not transfer.

The c0f change preserves missing-applicable-evidence precedence and complete-negative semantics. It refuses an eligible primary paired with a negative retention member at the original panel and current-material boundaries. This refusal is not aggregate NoUpdate, objective fraud or a payment decision. Complete primary-negative NoUpdate and insufficient-evidence refusal remain distinct.

[Publication proof](published-c0f/ROOT_PUBLICATION_AND_ALIGNMENT_REVIEW.json) · [fresh evaluator XML](native-c0f-exact-validation-v1/eval-lib.xml) · [fresh evaluator review](native-c0f-exact-validation-v1/EVALUATOR_ROOT_REVIEW.json) · [complete original native terminal bundle](native-c0f-terminal-complete) · [earlier maintenance and marker synchronization](checkpoints/README_1120FILES_C0F_FULLCALLER_PENDING.md).

## Full caller terminal evidence and exact recovery

The actual caller entrypoint was **14:23:20.377483 UTC**. The command terminal was **15:37:45.633884 UTC**, and packaging completed at **15:37:51.957226 UTC**. The original wrapper took **4477.559094 seconds** within its unchanged **4800-second budget**. The receipt explicitly retains **authorityGranted=false**.

The complete original raw output is **251,757 bytes**, SHA256 **c35b1087bfd1d113fe745ebba74dfaceab650c694842d93372b88ba07687ba2d**, Git blob **d99d8f143638e563d10804dc4b5be0e663ba7012**. These bytes were recovered using the exact original serializer and actual c0f boundary metadata, then accepted only after matching the independently recorded original full-file byte count, SHA256 and Git identity. Actual pinned-version prefix and tail reads also match. The two middle direct reads timed out; a separate asynchronous read is not silently counted as complete. **This is exact-byte recovery, not a new complete on-site read or a new gate execution.**

The original before/after source inventories have the same **5,474,911-byte JSON** and SHA256 **cdb6cea4f3142702681a20476db2a078a08d7b3b981bbc1ceb568c886fe3aa57**. Both terminal manifests refer to the same five exact retained gzip parts. Root newly decoded their previously verified base64 companions and matched every part's byte count, SHA256 and Git identity. The earlier independent complete inventory decompression remains preserved.

[Original command record](source-gates/c0f78493-v1/verify/verify.json) · [full original output](source-gates/c0f78493-v1/verify/verify.log) · [original execution terminal](source-gates/c0f78493-v1/verify/execution-terminal.json) · [original package terminal](source-gates/c0f78493-v1/verify/gate-final.json) · [recovery method and limitations](source-gates/c0f78493-v1/verify/FULLCALLER_EXACT_BYTE_RECOVERY.json) · [root terminal review](source-gates/c0f78493-v1/ROOT_TERMINAL_ADDENDUM_REVIEW.json) · [setup/self-test placement](source-gates/c0f78493-v1/SETUP_SELFTEST_TERMINAL_PLACEMENT.json) · [root setup/self-test byte review](source-gates/c0f78493-v1/ROOT_SETUP_SELFTEST_REVIEW.json).

Original pre-package gate-summary records remain unmodified; later gate-final records determine their final states. Source-closure's **83,293-byte forwarded stdout remains unavailable**, although its separate **81,881-byte full raw log** was previously recovered and verified. The helper compiler's internal **1,036,137-byte JSONL remains incompletely recovered**; its file-info and first chunk are not relabeled a complete log.

## Native failures and one actual stack diagnosis

The fresh focused JUnit confirms **24 stack-overflow failures, two actual per-test 60-second timeouts, one InvalidBinding and one OwnerUnavailable**. They are not collapsed into a single cause. The original helper build succeeded; that success does not override the subsequent focused failures.

One original failed c0f ELF was preserved byte-for-byte: **282,318,328 bytes**, SHA256 **b63053496fb1a8f610445862a6ce980ccb7beead4e08796feaa97ab21813e119**. A single diagnostic GDB run stopped on its first actual SIGSEGV at the ready-for-publication future's stack probe. It used the original 8 MiB thread stack and did not run Cargo or change stack limits.

The actual caller stack already used **7,251,104 bytes**, leaving **1,137,504 writable bytes**. The next prologue requires **2,284,152 local bytes**, plus saved registers/return address; the observed fault lies in the adjacent guard page. A later read-only ELF inspection found four caller-local reserves totalling **7,242,272 bytes**. The remaining 8,832 bytes are not assigned to frames without evidence. CFI extraction stopped at its bounded byte limit and is explicitly unavailable.

This establishes a concrete oversized-frame failure in this one observed chain. It does not prove recursion, explain all 24 failures, or predict the stack layout of the next Rust build. The two additional boxes already present in fixed a96 may affect layout; their effect must be measured by actual compilation/tests. No speculative extra boxing or stack-budget increase was added after this diagnosis.

[Original GDB run and bytes](native-c0f-first-signal-diagnostic) · [four-frame original static evidence](c0f-four-caller-prologues-v1) · [source/ELF audit](native-c0f-first-signal-diagnostic/FOUR_CALLER_SOURCE_AUDIT.md) · [complete original focused evidence](native-c0f-terminal-complete).

## Source-availability finding and next isolated worktree

The original review directory's last proven complete physical source inventory is the **15:17 UTC GDB operation**. A later operation at **15:29:07–15:29:13 UTC** attempted its prerequisite full-byte source check and could not find the tracked file **qualification/cell-platform-fixtures-20261108/native-and-ci-evidence.tar.gz**. Its actual result states **fetch_started=false** and **cargo_or_tests_started=false**. The operation therefore never reached Git fetch.

The cause of that missing file remains Unknown. This is not evidence of an origin, credential or network failure. Later HEAD/tree/status and ELF reads do not prove physical completeness. The old directory is preserved; the next maintenance uses a fresh isolated directory constructed from verified canonical Git objects.

The separate original source-gates clone was fully inventoried before and after its completed caller run and again during the completed timing diagnostic. Its proof is not substituted for the old review directory.

The cloud execution environment subsequently became unavailable. GitHub object reads/writes and the independent native desktop remain separate capabilities. A local root canonical-validator request was terminated without a usable completion receipt; no execution or saved output is claimed for it. The approved **evidence-only canonical object validation has now actually completed successfully**. Its read-only Git object checks did not import objects, create a checkout, run Cargo or examine current worktree file bytes. The next operation is preparation of a new independent repository and exact physical checkout; its reviewed implementation and actual execution are still pending.

[Original failed prerequisite result](a96-origin-object-fetch-v1/RESULT.json) · [unaltered native payload](a96-origin-object-fetch-v1/RESULT.binary-read.payload.json) · [canonical transport](next-profile/a96-canonical-transport) · [root transport-only review](next-profile/a96-canonical-transport/ROOT_TRANSPORT_REVIEW.json) · [prepared independent validator](next-profile/a96-canonical-independent-validation-v1).

## Measured caller hotspot and exact proposed optimization

A single scoped diagnostic used the **original unmodified c0f verifier** and all **6,597 Rust files**. Its internal 220-second window stopped as designed; worker exit was **3**, not PASS. Actual elapsed time including final inventory was **224.8805 seconds**. The durable process terminal confirms exit 3, no process timeout, complete/durable logs and terminal publication. Before/after full source inventories match exactly.

It called 14 boundaries and completed 13 before stopping inside final_use_open_state. Inclusive measurements were:

| Wrapped operation | Calls | Inclusive wall seconds |
| --- | ---: | ---: |
| has_authority_call | 25,251 | 152.749 |
| _declared_aliases | 64,833 | 43.959 |
| _verify_boundary | 14 | 185.058 |

These measurements overlap and must not be added into a total or percentage. The actual stopped stack is the original helper's per-type-name word-boundary regular expression.

The prepared optimization changes only **scripts/hepta_typed_callers.py**, from **e23bb8aa42241b429ef5dbce5a4660853b66eb2f** to **2708a60c076c0b4ae8c0bdd4473ce30bc9c9bbf4**. It adds two necessary literal-containment checks before existing regular expressions. It does not add a verdict cache, filter source files, remove a boundary, change normalization, or extend a gate budget. Whole-file postimage and exact two replacements were independently verified. Actual optimized gate performance is not yet observed.

Timing v1 was never executed: root caught that one verifier import held a previously captured helper alias. The executed v2 wraps and restores both original references. An initial relative-executable admission was explicitly rejected before a job existed; the same stable key was admitted once after changing only the executable to /usr/bin/python3.

[Actual timing metrics](caller-performance-diagnostic/c0f-typed-timing-v2/timing-metrics.json) · [root review](caller-performance-diagnostic/c0f-typed-timing-v2/ROOT_REVIEW.json) · [actual diagnostic log](caller-performance-diagnostic/c0f-typed-timing-v2/diagnostic.log) · [actual durable terminal](caller-performance-diagnostic/c0f-typed-timing-v2/actual-process-terminal-sdk.json) · [exact optimization packet](caller-performance-preparation/necessary-literal-shortcircuits-v1) · [integration plan](caller-performance-diagnostic/helper-integration/INTEGRATION_PLAN.json).

## Next source preparation: exact object, incomplete qualification

The prepared **86dd56a9** commit has its original 1,388-byte canonical body, SHA256 **62f050d9cbe56cad3c46f4d9a02a57cc27f4f6fa3453d60db1580f3a7561936c**, and exact Git ID independently verified. Root separately fetched and re-encoded the before/after root and scripts trees. Relative to the previously verified f1db tree, only the stated helper blob changes; the full leaf count remains 15,188. No source or PR ref moved.

Its source composition includes the complete fixed a96 delta, the 59-file ordinary evaluated NoUpdate preparation, three separately reviewed Rust increments, the explicit 33rd Root case, 13 structural non-Rust changes, and the two helper short circuits. The Rust increments preserve route evidence while putting it into actual candidate order, and make two real original-owner calls explicit for the conservative collector. They do not forge owners, decisions or outcomes.

The ordinary evaluated preparation keeps legacy and evaluated profiles distinct, retains actual original Training/Evaluation custody, uses once-consumed channels without reconnect/retry, and checks current Root authority before and after recovery/readback. Complete-negative evidence is required for NoUpdate. Original Model ownership is still required; missing original Model/Selector/Version/FinalUse owners do not gain an Adopt path. These remain uncompiled mechanisms, not a real A/T/B/C completion.

The structural CALLERS preparation has **569 boundaries**, including 28 additions relative to fixed a96's 541. Existing authority flags remain false. The 12 QA structural edits change expected membership only; the original 140 function ASTs remain unchanged. **Ten new protected rows, 39 existing protected literal updates, new adversarial QA and final blob-size allowance synchronization remain incomplete**, pending actual native maintenance. The subsequent complete exact-source gates must run under their original definitions and budgets.

The canonical a96 transport contains **395 original Git objects: seven commits, 80 trees and 308 blobs**. Root verified the complete transport identities, all seven canonical commit bodies and the explicitly documented 72-byte binary recovery. The approved independent native validator then actually verified every inflated object body, seven complete snapshot diffs and the exact existing prerequisite set. Root separately read the complete original result and matched it against the pinned-version native binary read, full-file metadata and durable process terminal. The required-existing set is exactly the objects needed by the seven new snapshots minus transported objects, plus two commit anchors; it is **not a claim of complete recursive repository history**. The original manifest's broader ancestry phrase is preserved and this scope correction is explicit.

[Prepared canonical commit](next-profile/preparation86dd/CANONICAL_COMMIT.json) · [root independent commit/tree review](next-profile/preparation86dd/ROOT_REVIEW.json) · [ordinary evaluated preparation](ordinary-evaluated-no-update-preparation) · [structural non-Rust review and remaining protections](next-profile/nonrust-structural-v1).


### Actual canonical object validation and full prepared delta

The unique native validation job **1a1d09b7b3e-2564-1ba7** ran at **16:33:35.443467–16:33:48.419914 UTC**. Its actual status is **canonical_snapshot_closure_verified**; the process exited **0**, with no timeout, complete/durable output and terminal publication confirmed. This is an object-closure result, not a qualification gate.

The reviewed driver **49c9c2c13cf545b2a47cce110b8dce6b60a0e86a** checked all **395** provided raw objects; the seven original commit bodies and complete tree/leaf differences; the authentic b298 and c0f snapshots; and **16,082** required existing objects (**14,306 blobs, 1,774 trees, two commit anchors**). The existing prerequisite set exactly equals what the seven new snapshots need after excluding transported objects and adding the two anchors. The complete trusted b298/c0f snapshot union contains 16,136 objects. Final a96 is exactly tree f96bebefbc1e7d8187efadb62f88d524cdd18451 with **15,161 leaves**.

The original complete result is **38,525 bytes**, SHA256 **e3fa2ee9c142b6360fb7994db28746d54b2abf9fc27ea362f08e6a80d37f7bdb**, Git blob **d7c135961dfacc04fe8b69697a66450e65566acb**. Root decoded the full original binary-read payload and checked exact bytes, hash, length, fixed version and EOF. The original source repo's HEAD/tree, **2,013,903-byte index**, and empty ref listing were identical before/after; **current physical worktree files were not examined by this operation**. The next materialization must freshly reproduce the full original physical inventory before/after.

Three full audit packages were generated on the native host: object audit **1,916,374 gzip bytes**, nine snapshot leaf maps **10,388,682 gzip bytes**, and raw trees/anchors **920,740 gzip bytes**. Their exact raw/compressed identities and recoverable parts are in the original result. Their complete transfer off the native host is not yet claimed. Current source/test failures and historical whole-history fsck limitations remain unchanged.

Root also independently checked the next **86dd** transport: **87** raw objects (**77 blobs, nine new trees, one original commit**), 2,302,939 raw object bytes. Its five verbatim ASCII JSON fragments assemble to exactly **3,241,174 bytes**, SHA256 **05e3a7b01f5814e0816fe8d521c68f55fddc64536e62fcedca7934e0832cb055**. Every object body and Git ID, all provided-object reachability and all **1,451 immediate external references** were checked. Thirteen independent original Git tree reads proved the complete fixed-a96-to-86dd difference: **99 paths changed, 27 added, zero deleted**, resulting in **15,188 leaves**. Two unchanged c0f evaluator subtrees are deliberately reused rather than retransmitted. Direct reference checks are not a substitute for the final native transitive closure and physical source checks.

[Original native object result](next-profile/a96-canonical-independent-validation-v1/ROOT_REVIEW.native-original.json) · [root actual-result review](next-profile/a96-canonical-independent-validation-v1/ROOT_ACTUAL_RESULT_REVIEW.json) · [full 86dd objects/delta review](next-profile/preparation86dd/ROOT_FULL_OBJECTS_AND_DELTA_REVIEW.json) · [87-object transport manifest](next-profile/preparation86dd/OBJECT_MANIFEST.json) · [handoff and exact format](next-profile/preparation86dd/README.md).

### Separate QA strengthening proposal

A separately reviewed proposal strengthens one existing published-read membership test from its declared-file subset to the **original complete Rust collector and both original masks**. It locks the existing source root and ignored-path contract, keeps every original assertion/attack, and checks that its two injected attack paths cannot be ignored. Each variant receives a separate full source dictionary and follows the original uncached boundary scan; no verdict/path/field cache or new ignored path is introduced.

This method explicitly leaves the earlier structural-only phase in which 140 function ASTs were unchanged. Its 25 original boundary invocations, when the method reaches them, retain the same attacks. The proposal is **not applied or executed**: it may enter the final non-Rust packet only after the actual formatted worktree matches its exact QA preimage. Further Clone/readiness/current-authority protections and adversarial QA remain in preparation.

[Exact proposal](next-profile/protection-preparation/complete-collector/MANIFEST.json) · [root method review](next-profile/protection-preparation/COMPLETE_COLLECTOR_ROOT_REVIEW.json) · [independent semantic checklist](next-profile/protection-preparation/INDEPENDENT_SEMANTIC_CHECKLIST.md).

### Exact-head hosted CI observation

The read-only observation at **16:21:52–16:21:53 UTC** found **zero check runs, zero check suites and zero workflow runs** for the exact published c0f head. Combined status was pending with zero entries. This supplies no PASS and does not prove a job is running. No workflow was triggered by that observation. [Original timestamped API responses](published-c0f/CI_OBSERVATION_1621.json).


## External utility and authority limits

The external task goal, consequence prediction, policy, critic, later independent observation and public reward contract remain separate. A learned model does not gain permission to redefine the goal, observation standard, reward contract or owner authorization to demonstrate progress.

A successful method or caller receipt would still not establish the strongest deployable comparison. The fixed matched expert does not prove the strongest deployable baseline; the evaluated object must include base, Cell/adapter, router, runtime configuration/tools, actual task distribution and lifecycle costs. Old, rare and mandatory safety tasks need their own noncompensable constraints.

The frozen cost scope remains **TaskLedgersBeforeFinalHoldout**. Full post-cut evaluation, download, activation, serving and maintenance costs are not established. Different keys/controllers do not demonstrate independent task provenance, training lineage, evaluator models or operations. Recorded action/propensity and frozen/cross-fit critics do not by themselves identify all action-changing outcomes; unsupported comparisons remain Unknown.

Complete negative service, insufficient evidence and objective fraud retain different meanings. Retention refusal is not a fraud judgment or a payment contract. Chain content roots identify bytes; they do not independently establish continued availability, lawful authorization or actual consumer adoption.

**Real ordinary Adopt = 0. Real evaluated NoUpdate = 0. Real daemon + Root cold-recovery qualification = 0.** The required real authorized A → original T → independent B → Adopt or complete NoUpdate → new C → daemon and Root cold recovery still needs authentic owners, task outcomes, retrievable authorized model materials and consumer readback.

[Literature result boundaries](LITERATURE_RESULT_BOUNDARIES.md) cover unilateral deception versus collusion, evaluator-lineage preference leakage and the conditions of performative scoring. The historical repository-wide fsck exit 3 also remains preserved; verified snapshot closures do not turn global history green.
