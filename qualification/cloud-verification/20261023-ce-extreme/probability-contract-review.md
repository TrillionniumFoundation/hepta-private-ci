# conditional_ce probability contract review

Read-only baseline review at #3601 exact `4e49a5aa5025807d289b8219d049125327d3fbdd`, `/workspace/ce-numeric`. No #3603 content or code edits. Inspected repository AGENTS.md, v4 portfolio.py, test_near_neutral_risk.py, test_numeric_admission.py, test_portfolio.py and README.

Recommendation for this isolated numerical repair: preserve ordinary-path and gamma==0 behavior; preserve normalization in the small risk-weighted span regime. Record the existing difference as a compatibility limitation, rather than silently claiming one globally normalized probability law. A global normalization change needs its own semantic decision and revalidation of frozen outputs.

Evidence:
- portfolio.py:181–187 accepts probability mass within absolute 1e-12 of one.
- gamma==0 (189–190) uses raw weighted sum; ordinary positive risk (218–223) uses raw probability exponential sum.
- the current near-neutral branches (206–217) divide by supported total. This prevents accepted mass error from becoming -log(total)/gamma as gamma approaches zero.
- test_near_neutral_risk explicitly requires (0.4,0.6000000000001), gamma=1e-16 to stay approximately -5.8. Raw mass treatment would not satisfy that intended behavior.
- the ordinary-risk test explicitly requires original-evaluation equality; README near-neutral section says ordinary registered coefficients take the original calculation. README top-level entropic formula uses raw sum and assumes an actual normalized probability law. These coexist with the tolerated-input implementation compromise.

Global raw treatment would regress near-neutral continuity; global normalization would change ordinary evaluation and gamma==0 results for tolerated-mass inputs, and may change bitwise results even for float sums rounding to one. Neither is a purely numerical repair. Exact rejection of any float mass !=1 also tightens existing admission and is out of scope.

For a Decimal fallback triggered by float span overflow, classify the real risk-weighted span using Decimal input values. Apply normalized treatment when that span is <=1e-4 and raw treatment for the ordinary regime, so fallback selection alone does not silently change the accepted probability interpretation. If implementation instead deliberately normalizes all fallback cases, explicitly document and test that additional semantic exception; do not describe it as universal parity.

Remaining inherent limitation: tolerated nonunit mass can produce a normalization discontinuity around the small-span threshold, and gamma==0 is not exactly the normalized gamma->0 limit. This patch should not claim to solve those broader contracts. Finite-span normal path can also retain cancellation/error cases outside the requested fallback threshold.

Numerical review checklist for the subsequent diff: exact binary float conversion via Decimal.from_float; sufficient precision for exponent/log cancellation and subtracting a huge anchor; smallest subnormal gamma and probabilities; finite values with overflowing float difference but small/medium/huge true scaled span; zero-support exclusion; threshold boundaries; constant support; Decimal exponent bounds for gamma*span up to roughly 1e616. An independent oracle should use a distinct formula with greater precision, rather than copy implementation branches. Existing fixed 90-digit Decimal(str(...)) oracle is not sufficient evidence for all extreme exact-binary cases. No dynamic success claim yet; full diff still pending.
