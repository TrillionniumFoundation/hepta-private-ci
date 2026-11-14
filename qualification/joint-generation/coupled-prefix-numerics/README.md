# Fixed FIT-prefix diagnostic: explicit probability normalization is supported

The previous coupled-gradient science campaign remains **aborted and unevaluated**.
This separate numerical diagnosis reconstructed only its seed11 independent-NDU
117-update prefix, reproduced the same old guard refusal at fixed batch117, and
compared all64 rows. No validation, TEST, new checkpoint or later update occurred.

## What the fixed batch establishes

- The original FP64 computation had one relative residual-balance failure among
  48 nonconstant rows (16 other rows were constant compositions). Maximum relative
  imbalance was2.0333e-8 against the unchanged sqrt(float64eps) threshold1.4901e-8.
- Exact rational arithmetic on the **existing binary64 probabilities without
  renormalization** still had one relative-balance failure:1.9068e-8. Exact transport
  sums alone therefore do not admit this whole batch. The exact identity
  rA-rB=sum(p)-sum(q) held on every row. Maximum input-total error was3.6492e-16.
  Failure-row intersection was not saved; no same-row or per-row causal claim is made.
- **Explicit normalization of each input policy** in rational arithmetic and in
  genuinely extended precision admitted all64 rows under the same floor, balance
  and marginal guards. Exact-normalized versus extended gradients differed by at
  most8.67e-19; joint tables by3.05e-19; objective values by1.11e-16.
- The explicitly normalized joint differed from the original actual CDF-normalized
  serving table by at most4.88e-16, and marginals by4.44e-16. This is below the fixed
  1e-12 diagnostic comparison bound, not bitwise equality or a universal guarantee.

Thus **input-mass-closure reference is supported on this fixed batch**. This is not
new generation performance, general numerical coverage, permission to relax old
thresholds, or a rescue of the failed eight-cell campaign.

## Explicit reference graphs

`reference.py` exposes separate represented, simplex and extended references.
Represented mode reports forward values only, not an invented derivative. Simplex
and extended explicitly normalize raw input policy masses. Their gradients are
with respect to normalized logweights, including transport, branch derivatives and
whole-table normalization. They are not claimed to differentiate the old binary
softmax program unchanged. NDU costs use the same rounded binary64 exponential
entries; rational arithmetic is exact relative to those entries, not exact exp.
Positive exact min ties still refuse; constant compositions have zero utility
logweight gradients. The existing64float64eps residual floor andsqrt(float64eps)
balance threshold remain fixed even for extended arithmetic. No epsilon repair or
fallback on hardware without extended precision is allowed.

Four literal tests passed, including exact/extended parity, directional finite
differences for both heads and A/N, a mass-drift counterexample, ties/constants and
input immutability. From this directory, using the existing qualified helpers:

```sh
PYTHONPATH=../coupled-law-gradient:../explicit-semantic-transport:../semantic-coupling:../semantic-coupling-batch:../transport-aligned-training:.. python -B -m unittest -v test_reference
```

The frozen plan preceded this sole run. The original failed run did not save its
prefix digest: deterministic source/input reconstruction plus identical refusal is
the evidence, not a comparison against an unavailable original state snapshot.

## Cost and next boundary

Whole waited child: **0.714013 CPU seconds**,0.727987wall,41972KiB RSS, under5CPU/
60wall/512MiB/4MiB limits, CPU0/single-thread and the existing synthetic shared lock.
This includes all four tests,117 updates,353 forwards/22592 rows, one restore/clone,
one decoder observation/12 images,64 original tables and64 rows of each reference.
Reference CPU was0.095854 represented,0.137330 exact-normalized,0.006351 extended;
these are measured within the whole child, not additional totals. Previously
measured base preparation was0.219982CPU; prior failed/qualification runs, source/
review and unknown supervisor tails remain additional, not zero.

Any training follow-on needs a **new opt-in numerical profile**, its own literal
qualification and predeclared comparison. No old implementation, failure, scientific
gate or serving default is changed here. Only portable source, tests and aggregates
are published; no weights, private paths, images, row IDs or raw policies.
