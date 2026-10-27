# Preserving raw history in the native readout: development result

The raw-preserving representation is implemented and its information contract
passes. This development study still does **not** establish a native-state
utility advantage over the equally tuned lightweight history family. Its
selected native-minus-history mean is **-0.000403519**, with two negative model
seeds and one positive seed. The comparative-benefit blocker remains open.

## Frozen scope

The new `HYBRID_CONTROL_PROTOCOL.json` was committed before fitting at
`8b0475892ab3724e8247263b115a3bd26e1acae9`; its SHA-256 is
`4cb88c3f23197b403e3a5acbd5e40979364ca04e4a0d554302e484c6225052c7`.
The executable analysis and its imported helpers were hashed into
`SOURCE_FREEZE.json` before opening numeric banks or fitting any head.

Only the three archived V1 frozen-generator training/development banks were
read: 768 fitting rows and 384 development rows per seed. The latter are 96
source pairs under four conditions. No V1/V2 test or retention results, new
generator outputs, or audit-observer outcomes entered this study.

Each representation has 24 candidates: two feature families, four common
input transforms, and three ridge penalties. Every head has 40 features and
205 fitted coefficients. All **144 heads**, their normalizers, actions,
feature matrices, and adverse results are preserved.

| Representation | First family | Second family |
|---|---|---|
| Native | Existing 40 activation/eligibility coordinates | Original 16 public history coordinates plus 24 native coordinates selected by training variance |
| History | Existing 40 raw/square/difference features | Original 16 public history coordinates plus 24 fixed Fourier features |

Both hybrid families preserve the original raw coordinates exactly in value,
without clipping. Array dtype may promote to float64; this is not a claim of
identical raw byte serialization. Native coordinate selection and Fourier
normalization use training features only. The Fourier projection is fixed
across seeds/transforms and has no label-based tuning.

Equal head size does not mean equal total transform constants or execution
cost. The native selector and Fourier constants/normalizers are recorded
separately. Native features came from the pinned actual FFI kernel, with
**27,648 executed native ticks**; no kernel dynamics were trained or replaced.

## Recorded development results

The table reports the best head in each feature family, selected using the
same development criterion. Values already include the original logical
action charge. They are selection-set statistics, not prospective estimates.

| Seed | Pure native | Raw + native | Original history | Raw + Fourier | Best fixed |
|---|---:|---:|---:|---:|---:|
| 17 | 0.752132 | 0.754595 | 0.753200 | 0.754663 | 0.752388 |
| 29 | 0.787351 | 0.787096 | 0.786761 | 0.786084 | 0.789213 |
| 43 | 0.778071 | 0.777046 | 0.779803 | 0.775765 | 0.775903 |
| Equal-seed mean | 0.772518 | 0.772912 | 0.773254 | 0.772171 | 0.772501 |

Allowing each representation its full 24-candidate search yields:

| Seed | Selected native family | Selected history family | Native minus history |
|---|---|---|---:|
| 17 | Raw + native, k2, alpha 0.0001 | Raw + Fourier, raw, alpha 1 | -0.0000684125 |
| 29 | Pure native, k4, alpha 1 | Original history, k1, alpha 0.0001 | +0.0005902046 |
| 43 | Pure native, raw, alpha 1 | Original history, raw, alpha 0.0001 | -0.0017323489 |

The selected means are 0.773338825 for native and 0.773742344 for history.
The diagnostic row-oracle mean is 0.788912184. Although pooled selected values
exceed the pooled best-fixed statistic, both selected families lose to the
best fixed action for seed 29. Pooled improvement is not a consistent
per-seed superiority result.

The hybrid improves the pure-native family on seed 17, but loses on seeds 29
and 43. Thus preserving public history fixes the specific omission of raw
inputs without guaranteeing better finite-sample regression or decisions.
The stronger history comparator also benefits from its extra Fourier family
on seed 17. Reporting only hybrid versus the old single history family would
overstate the evidence.

## Contract and arithmetic checks

Synthetic behavioral tests verified exact raw-coordinate preservation,
training-only native variance selection, stable index tie breaks, unchanged
Fourier normalization under development sentinels, identical frozen Fourier
weights, and exact head/normalizer/action parity with V1's existing ridge
implementation. Changing development features and labels does not change
fitted coefficients.

The independent arithmetic audit reconstructed every saved feature family,
all 144 action vectors, means, regrets, and selections. Its separate augmented
least-squares solver refit all 144 heads: the largest coefficient difference
was `1.20e-8`, the largest prediction difference `1.10e-7`, and there were
**zero action disagreements**. All 24 native feature matrices match the
hashes from the prior normalization diagnosis.

Result SHA-256:
`cd7465fabc1c0071aaf243cc6864fdac7a001947ff6c9ed68bb1c859ec6ac76d`.

This is a targeted, retained development attempt. It does not change the
frozen field-bank fitting/audit experiment, V1's negative primary comparisons,
or the requirement for prospective matched-information and retention evidence.
