# Kernel validation 003: independent duration chunks

## Outcome

All 18 source-bound numerical tests passed, followed by the independent seeded CTMC Monte Carlo reference, spatial-refinement comparison, and local forward/backward probes. This is a finite-generator propagation audit, not a content-accuracy or deployment-benefit result.

The neural configuration is `Grid(cells=8, lower=-2, refractory_stages=2, fixed_rate=8.1, fixed_terms=21, max_duration=.36, per_token_chunks=True)`. The duration field bounds each chunk. Each token independently selects n=max(1,ceil(dt/.36)); a local rounding guard can add one chunk. Small transition/event operators are composed by masked binary powers. Completed tokens retain their tensors; a longer neighboring token changes scheduling only. Physical boundary remapping occurs once per observation.

The old strict single-chunk and adaptive modes remain reference APIs. Gross-rate domain violations and the explicit resource cap of 1,048,576 chunks raise errors. There is no clipping, fallback to a batch-selected truncation, or silent duration truncation.

## Evidence

| Check | Result |
|---|---:|
| Dense reference, duration 0 through 7.31, maximum state L1 error | 1.26267746259e-12 |
| Same cases, maximum expected-event error | 1.10400577569e-11 |
| Same cases, maximum affine reward error | 4.41624514735e-12 |
| Float64 maximum mass error in those cases | 3.10862446895e-15 |
| Eight local parameter/duration FD checks, maximum scaled error | 5.78444705031e-10 |
| 64-step float32 mixed-duration maximum mass error | 4.52995300293e-06 |
| 64-step mixed-duration total expected events | 14.3314371109 |

Both float32 and float64 retained **bitwise identical** prefix transition/event/reward/J/G arrays when future or neighboring durations changed the maximum chunk count from 1 to 21 and scheduling rounds from 0 to 5. Prefix derivatives with respect to forbidden future/neighbor inputs were exactly zero. The old short-duration profile and the new profile also returned bitwise identical prepared operators on their common domain. The value solver is unchanged.

Independent physical-overlap integration followed by a single dense exponential verifies one-remap semantics at dt=0, .8 and 3.2. A separate repeated strict-chunk route agrees with the binary composition, and fixed-generator subdivision agrees within roundoff. These statements do not cover inserting artificial boundary changes or collapsing the state between numerical chunks.

At physical dt=3.2, the nine-chunk analytic state bound is 1.66842334881e-11, and the expected-count bound is 4.03668273808e-10. The measured state/count errors were 2.58491145155e-13 / 6.25988150205e-12. Whole-interval error is explicitly accumulated; it is not advertised as the single-chunk 1e-10 tolerance for arbitrary chunk count. Bounds exclude floating-point, spatial/remap and prior-input errors. Derivatives hold the discrete chunk count and interpolation branch fixed.

## Local cost, not whole training

The mixed-duration proxy uses float32 B=8,T=16,C=4,n=8,m=2 and durations .07, .495755147934,3.2. It measures forward plus backward with no optimizer. Sequential local-composite median CPU time was 0.274811893s; prepared composite median was 0.069138520s, a ratio of 3.974801. Every repeat and objective is in RESULTS.json; objectives agree. The direct independent-chunk route also builds a small composite operator, so this comparison must not be called a sparse-step kernel comparison.

The final validation process used 8.399870000 complete child CPU seconds and 13.870486127 wall seconds, including import/startup/exit. The earlier candidate audit used 8.920761000 CPU seconds; both new audits together used 17.320631000 CPU seconds. These costs are retained separately from previous audits and the stopped content001 study. No energy or GPU measurement is claimed.

## Provenance and failed prior time-domain assumption

The fixed one-chunk 002 source is preserved exactly under `results/kernel_validation002/source/`. The 003 candidate and its raw run are retained under `results/kernel_candidate003/` and `results/kernel_candidate003_run001/`. After content001 workers drained and their original source verification completed, the candidate's exact bytes were installed at the working root; this final validation ran the root module. Exact final source is retained in this directory's `source/`.

The content001 duration failures are not retrospectively reclassified as successful runs. The source-defined real-task time generation normalizes positive gaps to a total of 32; with physical scale .1, one interval can approach 3.2. This independent source contract invalidated the previous .36 observation-duration assumption. Revision 003 did not use heldout maxima to set numerical parameters. Content001 completed/failed-worker costs remain the study runner's responsibility and evidence.

| Source | SHA256 |
|---|---|
| MATH.md | `3899a158c856f72ba52c59de8d1f9d46f3967a9f2b8a1de2fa5e0bad97fb3a96` |
| distribution_kernel.py | `07195028877b4eb24f1bb1b53f1337019daf7bdabbdecbcd059f89079ba23de6` |
| kernel_tests.py | `e8c9cd018a7d707ebb8f118fd2f1e297057a5c59e2dcd06c53025cf19f045add` |
