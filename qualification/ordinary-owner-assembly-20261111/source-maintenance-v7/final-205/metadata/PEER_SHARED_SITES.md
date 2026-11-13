# Independent static review: 19 Shared join sites / 13 CALLERS conjuncts

## Verdict and exact scope

**No confirmed local blocker was found in the requested 13 protection rows.** Their final contents correspond to the actual Shared implementation in the 204-source candidate. The removed optional-state and asynchronous `join_locked` obligations have concrete construction, original-handle await, result-storage, waiter, and Drop successors. No deleted function remains as a positive function selector, and no target row was made vacuous.

This is a **source-semantic obligation migration**, not a formatting-only adjustment. The review does not claim compilation, lint, original-checker, mutation-test, native-test, or business-completion success.

Inputs:

- Candidate supplied by Root: `f9615a668f0d3a8c584a304389c4ce4c69701123`; actual-source manifest `848a82a966e4cab54b5410c5e4d2fe0dd7fde616`.
- Final CALLERS: `0f0b4c835de967f90263ae9041865f5ac431615e`, 2,151,753 bytes.
- Semantic recipe: `84702e0f1f9f1354a7ab24447acc6027c7921adc`.
- Sampler: `7a73be0590d32e92ed34dc53e71f1155e100073a`.
- Original 19-site inventory: `f3c5006b49ad5f388fe2c0abd2e09772ee5cbdda`.
- Full independent details, source pins/hashes, row fingerprints, function/item extents, and all 19 site bindings: `432e1264ad9ff88960ce9ca418b9ec93442f38b6` (49,861 bytes; SHA256 `0381772e309f3feeaba9f98c3946dab78a48e855d507d5c0631e307f12ad4012`).

Only the requested conjuncts and their 11 product source postimages were inspected for this verdict. Same-path rows were retained independently, never collapsed into a path-keyed row.

## Source and row verification

All 11 manifest postimages were GET/hash verified. The supplied sampler was evaluated against those actual source bytes using the existing pure V8 transcription of the original masking/function-extent/order rules. No lexical fallback was needed. Each complete sampled successor row equals the independently parsed final TOML row, including all fields.

The result is exactly **12 changed rows and one unchanged row**. Work #391 remains identical. Origin/ordinal and final fingerprints were checked against the final row ledgers, rather than inferred from a shared path.

Independently of sampler equality, the review verified:

- All 30 resampled function sequences contain the complete actual nonempty masked function lines.
- All 19 original await sites are covered: 16 by complete unique function sequences, and three by complete actual generic impl spans. The two Learning impl sites remain protected in both applicable same-path conjuncts.
- The 13 rows contain 156 function guards / 2,846 ordered function markers, 76 file-order sequences and 76 raw requirements. All positive sequences are nonempty. Of the file-order sequences, 44 are exact complete actual item spans; the other existing ordered protections remain as specified.
- Five obsolete representation selectors are absent from both the actual source and these final positive guards. Their mandatory completion constructors and actual wait paths are protected instead.
- Path and forbidden-array values in these 13 rows remain equal to the recipe predecessors. The already-completed whole-table forbidden audit was not repeated.

These counts identify the inspected material; the obligation mapping below is the basis for the verdict.

## Obligation mapping

Base ordinals below refer to `0f0cc13187dd3f9a09f78ef9ce33f52009c96678#protected_file:N`. Additive origins retain their original packet identity.

| Origin / final ordinal | Actual successor and retained obligation |
|---|---|
| Base #375 | The complete generic `retain_original_handle` span owns the same input JoinHandle in one retained Shared future, awaits it once and writes the exact non-Clone result / JoinError to the original cell. The complete new short lock helper and `receive` body protect completion-before-lock, single result take, original failure handling and Gate checks. Complete job/state and Drop spans protect output release before pending decrement, and fail-closed Drop if no actual join was recorded. |
| Base #391 | The entire distinct `from_original_scope` conjunct is unchanged, including its original context / prepared-source / evaluation bindings. |
| Base #445 | Complete `receive_with_join_cause` preserves the original JoinError object and error priority. The complete `OriginalJobCustody` impl protects both normal retirement and discard. Normal retirement still rejects an undelivered original output; neither zero count nor Shared readiness replaces that check. The original normal admission / exact-origin protections remain. |
| Base #494 | Circuit admission protects the original input handle, exact original Result mapping, retained Shared and the registry write before disarming admission. All three waiters await that Shared before the short state check. `join_locked` still exists here as a synchronous recorded-join check; it is not a stale deleted selector. Original delivery states, abandoned-result single recovery and whole receiver Drop remain guarded. |
| Base #504 | Consumer registration retains the same actual handle and original Owner / Cancelled / Panicked mapping. The complete state span still has an optional Shared plus optional observation. The complete waiter protects clone-under-lock, await outside the lock, and subsequent observation recording. The original MissingHandle rejection and once-recorded consumer accounting remain. |
| Base #506 | Session construction retains the actual worker and its original AbortHandle. The complete worker-state span and fault join body preserve Returned / Cancelled / Panicked mapping, missing-handle refusal, actual Session-retired precondition, actual worker join before parked-resource discard, and subsequent actual consumer joins. The writer custody field and failure-only Drop remain guarded. |
| Base #507 | The normal pause waiter uses the same registered worker Shared as fault cleanup. Its complete body requires Returned plus no recorded worker failure, joins consumers, checks the original pause origin and parked writer/live state, and transfers the original guarded resources. Shared completion alone does not mint the paused capability. |
| e6da #0 / final #512 | Removed `OriginalDriverState` is replaced by the mandatory Shared field in the private actual job. Complete construction protects the same service-cleanup handle, existing error mapping and synchronous registry retention. Complete waiter and unchanged client Drop cover observation and cancellation. |
| e6da #1 / final #513 | Removed startup/cleanup optional-state structs are replaced by mandatory Shared jobs. Complete constructors preserve the real JoinSet-draining task, actual cleanup task and original result/error mappings. Complete startup and cleanup waiters plus existing construction/shutdown guards retain the original resource join order. |
| e6da #5 / final #517 | Removed `OriginalThreadStartupState` is replaced by the mandatory Shared in the private startup job. Complete admission construction retains the same actual handle before disarming. The actual original Arc-backed failure is cached, and complete waiter / unchanged sealed-startup-to-session-loop joins remain protected. |
| e6da #25 / final #537 | Complete generic `OwnedJob<T>` impl owns the real handle, records the original non-Clone transport/result exactly once in its separate cell, and returns the result lock only after Shared completion. The complete stdio cleanup body ends the launch-result guard scope and drops the abandoned transport before later child/stderr/termination awaits. Existing original child and failure obligations remain. |
| App40133 #0 / final #538 | Both complete private constructors still require concrete actual Unit or Result JoinHandles. They retain the original Arc-backed JoinError / I/O error mappings in a mandatory Shared. The complete waiter records the same result in the original OnceLock; unchanged `require_original_success` still refuses absent or failed terminal state. Existing real task-category, processor and failure aggregation protections remain. |
| c981 #1 / final #554 | Bootstrap admission retains the actual handle in one Shared future and the exact non-Clone authority/error in a distinct cell. Complete state / constructor / short lock helper / receive and cleanup bodies protect the once-only receiving claim, actual completion, single output take, original error-before-Gate ordering and fail-closed poison/Drop behavior. |

The five removed representations are `OriginalDriverState`, `OriginalStartupJobState`, `OriginalCleanupJobState`, `OriginalThreadStartupState`, and `ActualAppServerHandle`. Their former “optional missing handle” branches are not relabeled as success: their successor private constructors require the actual handle and provide a mandatory completion field. Optional-state paths that still legitimately exist in Session and Consumer custody retain their explicit missing/observed checks.

## Exact 19-site coverage

| Product group | Actual original wait sites | Final protection |
|---|---|---|
| rmcp client | `join_original` | #512 complete function |
| stdio | `join`; `join_original_stdio` | #537 complete generic impl; complete function |
| codex-mcp | `join_original_startup`; `receive_original_cleanup` | #513 complete functions |
| Core | `join_original_startup` | #517 complete function |
| AppServer | `join_original` | #538 complete function |
| Learning | `receive_with_join_cause`; `receive`; `join_for_normal_retirement`; `join_and_discard` | #445 / #375 complete functions; complete impl in #375 and #445 |
| Consumer | `join_original_handle` | #504 complete function |
| Session | `join_original_paused`; `join_original_retired_session_custody` | #507 / #506 complete functions |
| Circuit | `stop_and_join_original_owner`; `join_original_returned_ok`; `receive_original_result` | #494 complete functions |
| Bootstrap | `join_and_release`; `receive_original` | #554 complete functions |

For additional source-level continuity, nine surrounding stop/admission/record/sealed-join/final-success functions were compared with their pre-refactor source bodies byte-for-byte; all were unchanged. This includes AppServer's actual `require_original_success`, Consumer once-recording, Session stop/abort and Circuit stop/admission.

## Actual 204 test-only successors

Two source pins differ from the semantic recipe solely because the 204 candidate adds cfg(test) support:

- Consumer jobs: `0b332b21c124905a3930785cdfc7e47563ac8085` → `af646ff44ca68d4caefbfd3a18693546267f3e6c`.
- Session lifecycle: `43fa3e2dadbbdde0fa4cb2979f9ed5f47df5bf44` → `471a2f261fba698b52bfa20cf1e282e28beb121a`.

Both actual postimages were GET/hash verified. Their masked product code, with whitespace removed, is identical to the recipe postimage. All target guards were projected against these actual 204 postimages. The new components were not executed or counted as passing tests.

## Limits

This review preserves the distinction between retaining a same-handle Shared future, observing its real completion, and completing the whole normal protocol. It does not infer a physical join from Drop, an empty registry, an ACK, a count, or an ordinary returned Ok. It does not expand any existing shutdown, error, deadline, or business-proof claim.

No source or metadata was changed. No h/native/Cargo/Python/original-checker execution and no reference mutation occurred. The full repository caller union and unrelated protection rows remain outside this narrow verdict.
