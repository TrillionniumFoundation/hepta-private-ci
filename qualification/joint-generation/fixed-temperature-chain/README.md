# Fixed-support, fixed-temperature coupling gradient

**Literal qualification passes: 26 tests, 128 finite-difference checks. No generation-quality improvement is claimed.**

This opt-in loss fills a distinct interface gap: command transport creates legitimate structural zeros, so its calibrated marginals cannot be fed into an old raw-policy API that correctly requires strictly positive softmax probabilities. The new kernel supports fixed reachable sets without weakening that raw-policy guard or filling zeros with epsilon. Old normalized/calibrated helpers and default serving remain byte-identical.

The smooth reference graph normalizes raw policies in genuine longdouble, applies fixed semantic transport, raises reachable marginal probabilities to fixed positive inverse temperatures, and constructs maximal semantic coupling with the original A/N utility. A new `FixedTemperatureLossProfile` wraps and actually uses the existing bound temperature profile; identity covers both exact hexadecimal temperatures, model and semantic identities, runtime precision, domain constants, and new loss mode/schema. Old envelopes, wrong models/modes and altered metadata reject.

For per-row upstream derivative dL/dA before batch averaging, let `h = A * (dL/dA - sum(A*dL/dA))`. The raw logit pullback uses `chain_i = tau * (p_i/a_f(i)) * h_f(i)`, then `(chain_i - p_i*sum(chain))/n`. The conditional ratio is bounded by one and only formed for positive preimages: there is no standalone overflowing 1/a or structural 0/0. Coupling normalization, power normalization and raw-softmax projection are retained, and batch averaging is applied once. The ordinary aligned anchor remains separate and unweighted by risk.

**Fixed tau is a constant here.** This is not differentiation of binary64 rounding or of the FIT refitting algorithm tau(theta). Existing calibration first rounds an intermediate coupled CDF; qualification compares its actual output CE within a predeclared tolerance, not bitwise identity or a theorem covering every floating-point input.

## Boundaries and evidence

Positive exact min ties are checked after temperature. Both constant maps yield a fixed outcome and zero utility gradient, even for different destinations; one constant head does not shortcut the other. The original residual floor (64 float64 eps), relative-balance restriction, finite/CDF/support/argmax checks and genuine-longdouble requirement remain. No row masking, fallback, threshold relaxation, denominator floor or generalized derivative is introduced.

The seven new parameterized tests cover tau pairs (1,1),(.5,2),(.125,8),(8,.125), both A/N risks, legal partial commands and permuted semantics, two heads, utility plus ordinary .2 anchor, branch-stable central differences, batch averaging, constants, modality swap, reward/logit translation, immutable inputs and explicit identity/invalid-input rejection. Twelve old normalized and seven old temperature tests rerun unchanged. Old relative-balance fixtures are inherited; this does not claim a new-temperature witness for every possible rejection domain.

- 128 scalar finite-difference checks: maximum absolute error **3.56667057e−11**, below the fixed 1e−7 bound.
- Actual calibrated-CDF CE difference: **2.08166817e−16**, below the fixed 1e−12 bound.
- Tau=1 value/gradient parity with the qualified old smooth helper passes.
- A sharp .99/.98 raw-policy example at tau=8 correctly rejects transformed tie/residual admission; this qualification does not promise real FIT-calibrated policies will be admitted.
- The original two-support negative-leading-text incentive remains demonstrable after positive temperature. A correct chain rule does not repair that objective incentive or rescue previous negative coupled-training experiments.

## Actual cost and scope

The fully waited child used **1.007076 CPU seconds**, 1.033102 wall seconds and 34508 KiB RSS, under 5 CPU / 30 wall / 512 MiB / 4 MiB, CPU 0, one numerical thread and the existing synthetic lock. All tests, imports, reference calls and finite-difference perturbations are included. Zero model restores, zero training updates and zero dataset rows. Earlier research, source/review work and unknown supervisor tail are additional, not zero. No automatic retry.

Only the helper, literal tests, executed prospective plan and complete qualification aggregates are published. The all-`a` model digest in the profile is a hand-made fixture identity, not a scientific model. No weights, private inputs or runtime paths, no default-law change or deployment, and no unrestricted scientific runner.

## Portable tests

From this directory alongside the previously published sibling helpers:

```sh
PYTHONPATH=../semantic-temperature:../coupled-simplex-longdouble:../coupled-prefix-numerics:../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../semantic-coupling-batch:../transport-aligned-training:.. python -B -m unittest -v test_fixed_chain
```

This command runs the seven new tests; the recorded qualification ran those plus all nineteen inherited tests. Any subsequent FIT direction diagnostic or scientific comparison requires its own frozen plan, actual cost record and original scientific acceptance gates.
