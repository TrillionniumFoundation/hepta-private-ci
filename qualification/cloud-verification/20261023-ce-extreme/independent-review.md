**Final disposition: no remaining blocking finding in the final two-file source set. Initial failures below are retained; final resolution and source binding follow at the end.**

# Independent conditional_ce review — changes required

Base 4e49a5aa5025807d289b8219d049125327d3fbdd. Reviewed actual portfolio.py diff and new test_extreme_risk.py. Source unmodified by reviewer.

## Blocking numerical defect

Precision max(80,80-2*width.adjusted()) does not account for tiny supported probability combined with large payoff and anchor subtraction. Two independently executed cases using the new direct unanchored 1500-digit exact-binary oracle:

- values=(-1e308,0), p=(5e-324,1), gamma=1e-320: actual +4.37260110905033e213, oracle -4.940656458414936e-16. Actual is above maximum supported payoff 0 and opposite sign.
- values=(0,1e308), p=(1,5e-324), gamma=1e-320: actual 0, oracle +4.940656458409995e-16.

Both pass existing admission: nonnegative finite probabilities within mass tolerance and smallest positive subnormal probability is not zero. Decimal precision discards the probability contribution; in the negative-anchor case log/division/subtraction leaves an enormous rounding residue. This disproves current claim that 80 extra digits cover final cancellation. Include probability dynamic range in precision and add these cases to regression, or use an adequately justified whole-binary64-range precision. Do not clip results to bounds or drop tiny supported mass.

Command: PYTHONPATH=experiments/multimodal_output_portfolio/v4 python3 with imports portfolio.conditional_ce and test_extreme_risk.oracle; exact inputs/results in independent-counterexamples.json. No external dependency/network/vendor execution.

## Otherwise reviewed behavior

Zero-mass outcomes are excluded consistently. Decimal.from_float preserves binary inputs. Width computed before lowering precision and ordinary finite-span float path remains syntactically unchanged. Overflow fallback uses true Decimal width to preserve near-neutral-normalized vs ordinary-raw probability convention. gamma==0 unchanged. Full probability contract review is in /workspace/verification-ce-numeric/probability-contract-review.md.

The new oracle uses a different unanchored formula, fixed 1500 digits, exact binary inputs, and bounded test exponents. That is a useful independent reference for listed cases. New tests cover symmetric extremes, smallest gamma, threshold sides, translation, mass conventions and huge negative Decimal exponents. However, they omitted positive subnormal support probabilities, which reveal the blocker above. No full-v4 pass is claimed by this review; parent tests run independently. Default-context exponent extremes tested in the supplied suite are not alone a general accuracy argument.

Pending revised precision/source diff and full publish-set evidence review. No approval to characterize this candidate as correct until the reproduced defect is resolved.

## Final revised-source review — reproduced blockers resolved

The initial counterexamples above and independent-counterexamples.json remain unchanged as failure evidence. Revised precision adds -min(p.adjusted()) for supported probabilities; both errors are resolved without clipping or dropping mass. Caller Decimal context dependence is resolved using localcontext(Context(prec=800)); the test sets precision=6, ROUND_UP, Inexact trap and narrow exponent limits, verifies identical output and unchanged caller context.

Additional independent audit initially found three unchanged ordinary-float defects: values=(-1e308,0), gamma=1e-308, low-outcome probability 5e-324 / 1e-300 / 1e-80, other probability=1. Baseline and first candidate both returned approximately -1.99584e292, unlike the independent direct-oracle values. Original 90-case results remain in independent-boundary-matrix.json. Parent explicitly expanded the numerical repair to these observed defects: positive supported mass <1e-16 now also selects Decimal, retaining raw mass when true scaled width>1e-4. This is a justified numerical scope extension within the same function, not universal ordinary-path bit parity. Registered ordinary risk with non-rare mass retains the original expression. Added direct-oracle regression covers all three cases.

Final independent validation: 90/90 boundary cases match the previously computed direct unanchored **2000-digit exact-binary** Decimal references (independent-boundary-matrix-final.json); original failure file retained. Cases span masses down to 5e-324, payoff scales from 5e-324 to 1e308, subnormal risk, symmetric/one-sided support. Reviewer also ran all ten new tests: 10 passed in 2.308s, full log independent-final-tests.log. Command: `PYTHONPATH=experiments/multimodal_output_portfolio/v4 python3 -m unittest experiments/multimodal_output_portfolio/v4/test_extreme_risk.py -v`. The new suite separately covers probability conventions, caller context, overflow spans, rare outcomes, degenerate support, translation, threshold sides, permutation and impossible outcomes. No source edits by reviewer.

No remaining blocking finding for this finite numerical repair. Input admission and gamma==0 remain unchanged; small-width normalization vs ordinary raw mass is deliberately preserved, not globally unified. Existing tolerance/branch-boundary semantics and finite precision do not constitute a formal proof for all admitted laws. The independent matrix is finite evidence. No claim of universal finite-input accuracy, NDU scientific closure, multimodal generation quality, Runtime acceptance or external evidence independence is authorized by these results.

Only two files form the approved source publish set; evidence documents are to be published separately. No #3603 content. Final base `4e49a5aa5025807d289b8219d049125327d3fbdd`; tree `049be22f80c3cbe081d2257d0d351b88362063fd`; complete two-file diff SHA256 `e096b4c162c3445e441883e4ecb4f32f1b587eccd9071e05c7b0ec70dd41f9d7` (temporary index includes new test; actual index untouched). Independently verified source-manifest matches:

- portfolio.py SHA256 `e47f02e8cde4e500cc75e0708adce503ac0d88599232504c2887e64a7f55dfb4`
- test_extreme_risk.py SHA256 `1a27be71acd2d20b938c358153f0c6aedd7b2f9f1e926f3e663e5139a819ef46`

Exact remote commit checks, full-v4 rerun on published SHA and final evidence-document review remain parent-owned subsequent steps. This conclusion approves source correctness within reviewed scope, not unobserved CI results.
