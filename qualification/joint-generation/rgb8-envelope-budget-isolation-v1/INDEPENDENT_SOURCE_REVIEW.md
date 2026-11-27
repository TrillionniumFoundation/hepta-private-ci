# Independent source-only review — SOURCE ADMITTED

Exact freeze SHA256 `079690081a39bb9b4404a9b2b425d0d742994ea55ec1d4564e36c8aab81813ae`.
Reviewer /root/review_risk_decomposition. Read source, checked all25 bound hashes and AST, compared copied dependencies and exact old/new diff. No candidate imports, tests, adapter execution, model/data execution or worker invocation. RUN_ONCE absent. Candidate untouched.

## Fix and provenance
The sole adapter code change is returned request budget becoming a new dictionary instead of exposing the Budget instance's dictionary. Its two values are validated immutable integers, so a shallow dictionary copy is sufficient for this bounded contract. Input validation's temporary vars use remains safe for this scope because RunSpec.parse constructs a fresh Budget and does not return/retain the supplied dictionary. No validation order, thresholds, grammar, callback ordering or capability admission is changed.

Legacy adapter is byte-identical to original RGB8 publication and latest copied media module. Latest already-hardened contracts unchanged; original serve/control/model/data/utility dependencies byte-identical to historical sources. Original RunSpec.payload copy repair is a different return site; this fix is not duplicate qualification of that repaired site. Original tests cover pixel-copy and real backend serving, but do not assert this returned-budget value isolation.

Latest Fashion runtime is not shown to call RGB8: latest candidate lacks serve.py, and this isolated package explicitly binds the old real encode_request dependency. No claim of integrated latest-runtime repair, deployment, production authority or preserved historical release mutation is justified.

## Tests and exact cost
Five fixed methods statically cover old behavior separately, new two-way value isolation for each field and sibling conversions, unchanged old/new request and real202-feature encoder parity for eight command/mode/order cases, six validation refusals on both implementations, and actual dispatch with two trusted literal callbacks. No replacement model encoder or mock feature calculation is used. Ten instruction one-hot coordinates are checked against expected command semantics; image parser float32 conversion is unchanged.

Call ledger reconciles: adapter2 old +10 bidirectional/sibling conversions +16 parity conversions +12 refusals +2 dispatch=42 attempts,30 successes/12 refusals. Encoder30 successful adapters +16 direct parity calls +2 unknown-word failures=48 attempts,46 success/2 refusal. Observations2+4+8+12+2=28; callbacks2. Expected refusals are fixed qualifications, not experiment retries. Returned requests intentionally remain mutable; isolation, not hostile-code protection, is the property.

Imported native model/data/control modules have no top-level learned-model allocation or dataset generation. Worker forbids constructors/loading/inference/training/dataset entrypoints before tests; tests do not call them. Actual native encoder performs only literal input validation and feature construction. Imports cost time/memory and are charged; not claimed absent. No model state, archives, raw dataset, serving output, training or inference work is authorized.

## Evidence and failure limits
Legacy observations record before/after primitive budgets and alias assertion; new fixed-isolation observations currently retain passed flags rather than all primitive before/after values. Therefore independent saved review can verify inventory/hashes and rely on frozen assertions for those four new cases, but cannot reconstruct their unsaved budget snapshots from JSON alone. Likewise exact feature parity is checked in runtime assertions; saved feature hashes bind outputs but cannot reconstruct unsaved tensors. No blocker: claims/publication must retain these limits.

Adapter rejections use no callback in those tests, so callback nonexecution there is supported by source ordering, not a separately observed backend call count. The separate dispatch test uses actual dispatch with local functions, not model inference or external owner callbacks. Partial completed observations/counts survive unexpected failure; all tests and exact counts plus final source hash equality required before terminal success. Guard/output restrictions and monkeypatches are qualification controls, not an untrusted-code security boundary.

## Envelope and disposition
Single parent-authorized invocation only, shared synthetic nonblocking lock, CPU0/one numerical thread,5CPU/30wall/512MiB/4MiB-per-file, fullwait4 resource receipt, no retry. Preparation/review, all upstream work and supervisor tails additional nonzero costs. AUTHORING_NOTES preserves a pre-freeze textual-edit rejection with no source write, not a scientific retry. Reviewer also used only non-mutating text/hash checks; no experiments occurred during this review.

SOURCE ADMITTED for isolated local adapter value-copy qualification only. No deployment, latest Fashion integration, owner authorization, security hardening guarantee, natural data, scientific gate reopening or production inference capability follows. Parent authorization and successful sole run are still required for result claims.

## Final evidence-retention revision — SOURCE ADMITTED
Final freeze `0cc4f7e0c096c3c60dfee08a04c4f6977d975f58a6ff0897d119c52c01b5d187` supersedes079690... . Rechecked all25 source hashes/AST and exact one-line old/new adapter diff; RUN_ONCE absent. Reviewed added `fresh=None`, fresh budget snapshot on the already-existing conversion, and before/after envelope/request/sibling snapshot fields in each of four fixed-isolation observations. These changes retain primitive dictionaries rather than aliases; no extra adapter/encoder invocation, test method, threshold or fix behavior is introduced. PLAN evidence description now corresponds to saved fields. Future independent review CAN check those saved numeric budget relations; prior paragraph's bool-only limitation applies only to superseded revision. Feature-array and production-integration limits remain unchanged. No tests/model/worker executed by reviewer. SOURCE ADMITTED for this exact revised freeze.
