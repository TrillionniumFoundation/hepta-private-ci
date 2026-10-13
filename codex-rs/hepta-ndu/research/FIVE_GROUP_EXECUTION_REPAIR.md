# Group execution repair: scalar hashing, full menu and partial compute

Date: 2026-10-13. Parent: `e2f2b78d387b7dd1404e502aaea35a6b1c836d12`.
Continuation of PR #1697. Existing reader learning, model inventories, all
experimental arms, trained-architecture identity and independent admission
remain unchanged. No production activation, main merge or forced ref update.

## Actual evidence obtained during this increment

The response-learning job **38385257430**, source `6c66ce7cb43f116b44c96fc8121df2b99aedf72d`,
is no longer pending. Job **115255335064** finished with FAILURE. Its actual
log records 14 matrix, 54 contract and 29 native tests passing. Of 45 Group
tests, seven errored and one failed; the other 37 passed. Five explicit
state-candidate-interaction tests passed. This is source/fixture evidence,
not learned reasoning or a pretrained Group run. No response test, model
acquisition or response training step executed after the failed Group gate.
Retained failure artifact: **11806563041**, GitHub-reported 58,529 bytes and
SHA256 `6bd33ea1cad275324e78f365e631465de3865c70be72a875add630c612aa48a6`.
This increment did not locally rehash that artifact.

The observed stack is `parameters(FixedCell) -> tensor_digest -> view(uint8)`:
`RuntimeError: self.dim() cannot be 0 to view Float as Byte (different element sizes)`.
The failed failure-injection test received that earlier RuntimeError instead
of reaching its planned Reader dispatch, so its observed call count was zero.
The fix does not reshape the fixture parameter or delete/weaken these tests.

The container and Python probes in this increment both returned infrastructure
ClientError. Consequently, newly submitted source/tests are NOT claimed locally
passing. A new exact-source hosted run is necessary; the old 97 passing tests
and 37 passing Group cases do not validate the patch.

## Repairs in the existing implementation

1. `experiments/shared_stem_cell/execution.tensor_digest` keeps the original
   shape and dtype header and flattens only the contiguous byte view. Scalars
   are now representable; old non-scalar digest bytes remain unchanged. This
   applies to the shared utility, not a Group-only replacement hash.
2. Eight evidence sources create 37 registered views, but `LocalEncoder.encode`
   admits at most 32 physical rows and 32768 padded tokens. The Group owner now
   chunks the ordered views with `min(32, 32768 // maximum_tokens)`. At a
   512-token ceiling the 37-view preparation requires batches 32 and 5; at
   8192 it uses nine batches of four and one of one. These are execution-plan
   counts, not measured model FLOPs or performance results. The original
   tokenizer enforces actual per-input length; no truncation, dropped view or
   batch-limit relaxation is introduced.
3. Every chunk checks the operation deadline and complete output geometry,
   dtype and finiteness. Features are returned only after all chunks succeed.
   A failed late chunk retains earlier actual forward hooks and wall/CPU
   observations; it does not produce a reduced candidate menu or retry.
4. `NativeGroupOwner.run` retains per-run cost even when execution raises.
   A Reader exception whose forward count is not reported leaves total Reader
   forwards null, with a separately identified known lower bound. Registered
   trial records preserve partial action-file hashes and observed cost before
   cleanup; a failed outcome is still a failed outcome.

`ENCODING_EXECUTION=ordered-chunks-32-items-32768-padded-tokens-v1` is included
in execution records. The menu, controller parameters and forward semantics
are unchanged; source SHA must still be re-registered before formal execution.
Batching can produce small floating-point differences; no universal bitwise
parity or device-speed claim is inferred. The tests use deterministic fixture
values to verify order and census, not generic HF numerical equivalence.

## Added regression definitions and execution behavior

`test_five_group_batching.py` adds 16 tests: scalar identity/shape and old
non-scalar digest bytes; all 37 inputs and order; padded-token cap; one-input
path; late failure/nonfinite output; deadline boundaries; rejected/closed
calls; all four System2 controls at the full menu; per-run partial cost;
unknown Reader cost; and nonaliasing output. All model/Reader inputs in these
tests are fixtures. The existing 45 Group test definitions are retained.

The native workflow now collects every focused test suite's exit status before
failing the step. A Group failure therefore no longer hides the Reader response
test results. ALL suites must still pass before archive acquisition and
training. This is not continue-on-error or a waived gate. Trigger paths and
retained source inventories include the shared utility and Group dependency.
The separate Group workflow preserves its pinned numerical environment.

## Scope remaining

This increment repairs execution prerequisites; it does not solve Reader
sufficiency or prove shared-learning, recurrent, NDU or multimodal gains.
The maximum menu remains empty/singletons/pairs, so tasks requiring three or
more jointly presented sources need a separately registered richer action
menu, not an inflated claim for this one. The one-step NDU profile remains a
baseline rather than a general FBSDE solver. Independent future tasks, review,
whole-lifecycle costs, media backends and native production integration remain.

No new pretrained model result or completed response-learning result is claimed.
All previous historical reference results and failed runs remain distinct.

Primary API reference for dtype view dimensionality:
https://docs.pytorch.org/docs/stable/generated/torch.Tensor.view.html
