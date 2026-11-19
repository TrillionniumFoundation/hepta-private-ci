# P5 fast outward interval audit — research only

**Draft / Shadow / DENY_ALL.** Stacked on PR #2045 at c220ff1b846b8875893ba6584cfe973770d890bd. The queued P0 Granite/mmBERT pretrained comparison, P5 coupled solver, prior original mmBERT replay and prior 96-term verifier are unmodified.

## Registered discrete mathematical law

For the exact same bounded binary coupled FBSDE as #2003/#2034/#2045, the old independent verifier used a positive 96-term Taylor expansion to enclose exp(2*x). This new alternative computes u=2*abs(x)/64 <=1/2, outward-rounds u, encloses exp(u) with 16 nonnegative Taylor terms and an analytic geometric bound on the remaining positive tail:

    R_16 <= term_17/(1-u/18).

Six outward interval squarings enclose exp(2*abs(x)); monotonicity of (E-1)/(E+1) and odd symmetry enclose tanh(x). All remaining forward state, backward conditional utility, signed-square-root noise, exact-binary64 coefficient interpretation, Q112 arithmetic, and global *discrete* contraction criterion q=a*T*(1+beta*T)<0.95 are unchanged.

Only candidate root intervals that strictly separate every action (including zero-value abstain) qualify. Singular/unsupported domains, ties, missing source, shifted task versions and invalid work receipts reject. The reference is not machine-verified formal software.

## Actual source-bound, local experiment — October 14, 2026

The 192 cases are the **same previously sealed synthetic cohort**, not new independent natural or prospective tasks. Canonical plan SHA256 e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2; original file SHA256 92c568e9694c259b64ac1f8bb1f6db9d9214dd14ca13c81ff7d1f75bbea7a607.

| Measured comparison (one local source-bound run) | Taylor-96 | Reduced Taylor-16 |
|---|---:|---:|
| Action choices agreeing with independently computed full-Picard reference | 192/192 | 192/192 |
| Interval recalculation CPU over all 576 candidate actions | 2927.00 ms | 1040.93 ms |
| P95 cumulative interval CPU per task | 16.475 ms | 5.646 ms |
| Original frozen nominal FBSDE forward-backward map calls | 1511 | 1511 |
| Proved end-to-end ONLINE cost/utility gain | NO | NO |

Source-held map-work replay separately charged 935 calls and ~41.5 ms CPU. Historical full Picard CPU in a DIFFERENT execution phase was ~126.93 ms over 192 tasks. Consequently **the 1.04 second verification is still more expensive than simply solving this toy discrete problem to completion**; treat this as an offline-audit arithmetic improvement, NOT faster real System2 reasoning. The Lambert continued-fraction alternative was also executed and rejected as slower, about 5.21 seconds versus 3.12 seconds for the older Taylor-96 method in an earlier local run.

The 26 normal and 26 optimized-Python adversarial tests cover exact-decimal numerical enclosures, source/label/authority drift, fabricated work counters, rank/shape errors, out-of-domain values and 192-case full independent decision correspondence. The CI re-executes a fresh plan -> sealed predictions -> independent score -> costed interval replay and uploads original complete and failed records.

No real pretrained Encoder, new task quality improvement, continuous FBSDE existence theorem, future-world observation or production model selection is claimed. All acceptance flags remain false, current blocking-ci/security/FinalUse remain mandatory.

## Reproduction

Run "python -m unittest discover -s qualification/ndu-p5-fast-outward -p test_fast.py -v" and the same command with "python -O". The read-only GitHub Action hepta-p5-fast-outward.yml runs the pinned synthetic plan/predict/score/compare sequence; compare.py accepts --plan, --sealed, --prior and create-only --output.
