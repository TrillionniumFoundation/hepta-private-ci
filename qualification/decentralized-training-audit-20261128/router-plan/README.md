# Preserve the original router fitting plan

The router-only source path accepted a valid parent with custom feature width,
ridge regularization and cost penalties, but `fit_bundle` silently selected its
defaults. After paying for graph search, the unchanged `review_search` refused
that result because its plan differed from the parent. The fixed path passes the
exact original `RouterPlan` into fitting and checks its execution binding before
loading any model. Callers without an explicit plan retain the existing defaults.
The original source, consent, graph, scoring and plan-equality gates remain intact.

## Reproduced behavior

The production baseline is `c076d74a013a9be0b969fd42c3932fdcee74e3f0`.
Its three router source files match the corresponding files in tree
`269d9e77805bd72353aaa812772d62d73c81d741`. The baseline control reaches the
original `review_search` gate and fails with
`original router study or retained Cells differ`.

All three final controls pass, with no skips: custom-plan source fitting and
independent readback; rejection of a stale execution binding before model loading;
and default-plan compatibility while retaining the refusal to relabel a custom
parent. The custom plan uses width 8, ridge 0.375, token penalty 0.125 and call
penalty 0.25. Each archived graph has two output tokens and two calls, with a
declared two-token and two-call cap. Its normalized penalties are therefore
`0.125 * 2 / 2 + 0.25 * 2 / 2 = 0.375`. The observed failure/success labels give
utilities `[-0.375, 0.625]`. All 18 fitted coordinates agree with the independent
single-sample ridge identity `W_g = y_g * x / (lambda + x.T @ x)` at
`rtol=1e-12, atol=1e-12`. The original `review_search` and `verify_originals` also
pass, and all input material hashes remain unchanged.

## Scope and reproduction

Run `PYTHONPATH=scripts python3 -m unittest cell_experiments.test_paired_router_plan -v`.
The test replays exact outputs and tokenizations from the two SHA-pinned existing
engineering archives. The business verifier and NumPy ridge calculations run
again. The final three-test suite makes 20 historical output readbacks and **zero
new model or teacher executions**. It does not run the original Transformer
loader, retrain Cell weights, establish independent learning benefit, or exercise
the native Control/Memory authorization pipeline. Historical provider timings
are retained for the fitting inputs and are not new runtime measurements.

`RESULTS.json` binds the tested source hashes and raw observation archive. The
archive retains the failing baseline, passing controls, original inputs and
outputs, exact baseline/final production sources, required `just fmt` result,
and separate harness-error notes. `MEMBERS.json` lists every other member's size
and SHA-256; all archive members were read back and compared byte for byte.
Formatting and lint on the changed bundle and new test pass. A whole-file lint
check of `paired_router_source.py` still reports its two existing unused imports;
those unrelated imports were neither removed nor suppressed.
