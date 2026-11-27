# Real native loop: controlled commit ACK-loss diagnostics

Parent #3653 d282d937aab7cf1ba3a1751db72f337442d54078. The production runner and all existing owners remain unchanged. This is new test/diagnostic evidence, not a product recovery implementation or claimed blocker closure.

PLAN.md fixed six cases and counts before execution. Directly drives the existing run() function through four post-commit error boundaries and two prewrite controls, using test-only file-backed adapters. The initial targeted six tests passed; the complete context-v2 package then passed30/30 (prior24+new6), zero skipped. all-loop-tests.log retains each case’s independent counter output. just fmt, diff-check and scoped --no-deps strict Clippy passed; broad dependency-wide strict Clippy retains the two unrelated context-compiler lint failures already recorded in #3653 and was not relabeled green.

Observed fixture behavior:
- ModelCompleted or ToolCompleted snapshot saved before reply loss: reconstruction follows committed cursor;2 model dispatches and1 effect execution total.
- CancelRequested snapshot saved before reply loss: no owners notified before that failed commit response; reconstruction obtains both owner ACKs once, no dispatch.
- Cancelled snapshot saved before reply loss: reconstruction returns stored terminal state without notifying owners again; both cancellation counters remain1.
- ToolCompleted fails before cursor persistence, effect receipt retained separately: identical operation key observed twice, effect executed once. Receipt-based deduplication is supplied by the EffectOwner fixture, not the loop.
- Explicit negative control discards the effect receipt while retaining its independent execution counter: the same key is observed twice and the effect executes TWICE. This expected negative result demonstrates that loop orchestration alone does not guarantee durable effect exactly-once semantics.

Context checkpoint, effect receipt, key log, execution counts, inference receipt IDs and cancellation counts are distinct files. All three adapters are dropped and rebuilt from those files. The context fixture serializes only deterministic revision/round/token/phase state and reconstructs fixed fixture binding/payload values; it is not an arbitrary conversation serializer or a provider-native continuation store. File-backed owner assumptions are deliberately visible, not smuggled into a product claim.

This is process-local adapter reconstruction, not process termination, SIGKILL, power loss, storage atomicity qualification, a real durable TurnOwner, production effect owner, live provider or physical effect. Counters/receipts are independent files, not a transactional distributed system. No socket calls, credentials, schema/dependency/API/security changes, merges or deployments. No new implementation defect was established by these six cases. Existing SHADOW/DENY_ALL posture is unchanged.

Tests preceded final formatting; per repository instructions they were not rerun after fmt. The author reports formatting/import-only post-green changes. The final test source was independently reviewed, but pre-format test bytes were not separately retained, so an independent before/after byte comparison is not claimed. Original runner SHA256 remains c8e89152bb7ae520314be240e8ddb1940c614443be90c7d5189ac8ce7bca2a96.

A local, unapplied one-line context-doc whitespace patch is intentionally not part of this publication. The8-parameter public observe_delivery API and its design lint remain unchanged. Future compatible migration may add a named request-object v3 API, preserve all independent receipt/verifier/time checks, migrate callers, and deprecate the old API under an explicit version policy. Keeping the old8-argument compatibility entry does not by itself remove that lint. No expect/allow suppression or public API rewrite was added.
