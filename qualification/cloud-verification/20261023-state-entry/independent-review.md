# Independent execute boundary review — final three-file set

No blocking finding. Base `cb97779e6f4ff361b5c1988523cb4dea87974ad4`. Full three-file diff SHA256 `e76d6f3fe744c8193087ea93bc009f014e0fc21040dfc7531752f170b4f3539a`; tree `04f4ce70b6b79c0158efd4874386534efdf26034`. Per-file SHA256 in independent-review-manifest.json. Temporary index includes new test without modifying actual index. All three files inspected; no source modifications by reviewer.

## Contract and behavior

Repository callers found only in test_portfolio/test_reallocation. execute has no fresh-only predicate and computes suffix cost from supplied initial.remaining; explicit fresh-only guards instead exist in full_outcome_audit/evaluate/evaluate_dependence. A legal advance-produced continuation carries the earlier paid activation, so the cost difference is not itself a demonstrated security defect. Full assessment is preserved in contract-review.md. Runtime behavior should remain unchanged.

Independent AST comparison of entire portfolio.py against HEAD, after removing only execute's docstring expression from both trees, is exactly equal. Therefore no behavioral statements, return schema, State validation, conditional_ce numerical repair or policy-replay guards changed. This preserves #3605/#3607. The docstring accurately states caller responsibility for paid transition history, suffix-only spent, and fresh RNG rather than checkpoint replay.

README describes the same actual boundary, explicitly distinguishing modeled integer charges from hardware metering, trace hashes from provenance and valid continuations from untrusted fresh-entry admission. Example parameters are explicit: activation5, max units1, risk0, shadow price0, seed0. The provided baseline and newly executed tests support fresh cost10, continuation cost5, prefix6 and complete modeled cost11. No claim of real independent witness, authentication, checkpoint verification or production execution acceptance is introduced.

## Tests

Independently executed final test_execute_boundary.py: 3 tests passed (independent-tests.log). The first locks in differing suffix control costs and reconciles spent with local records and terminal emission; the second constructs the continuation using actual advance/charge and reconciles prefix+suffix to original root budget; the third verifies each separate full-episode API rejects that valid continuation as a fresh root.

Final version uses a valid dependence regime `(((0,0,0,0),1.0),)` and precise error-message matches, eliminating the earlier possibility that an invalid regime could mask removal of the root guard. The positive continuation remains valid, so these tests do not enforce an incorrect step0 requirement on execute. No production checks were removed or added.

Command: `PYTHONPATH=experiments/multimodal_output_portfolio/v4 python3 -m unittest experiments/multimodal_output_portfolio/v4/test_execute_boundary.py -v`. No full-suite pass or remote CI result is inferred here. Parent owns exact-published-SHA full validation and remote file verification.

## Limitations

Documentation establishes the intended local helper boundary; it does not add authenticated provenance or stop a caller from manufacturing continuation state. Such an untrusted external adapter was not found in this experiment. Future adapters would need explicit fresh admission or verified resume provenance. Scope is documentation plus regression tests, not a vulnerability fix, real budget custody proof or new scientific acceptance.
