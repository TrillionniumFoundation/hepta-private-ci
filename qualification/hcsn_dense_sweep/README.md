# Fixed-profile reset sweep and original-law value cost — HOLD

This stage extends #6224 with the two fixed 1024-interval profiles and a source-bound comparison on all original retained posteriors. No mesh, floor, gap, reset or gate was tuned after these results. Original v3 loss remains recorded in #6220; these are new execution identities.

The positive backward Markov sweep covers 184 actual original reset values and four exposed literals, six gaps, and both profiles: 2,256 reset/time/profile rows. Original artifact SUMMARY and all 12 journal hashes are enforced. At .02, near800's maximum eligible relative M error is 1.543763%, at the actual original reset .3279167232298848. Near960's maximum is .984990%, at .32725. Eight forward-row comparisons agree within 3.12e-15 absolute. At .001/.003 all 188 values per profile are below the unchanged 1e-12 reference floor; there is no relative precision admission. Poisson bounds exclude roundoff and continuum error.

The continuation audit calls the actual candidate perpetual() on all 184 recorded physical/reset laws and three fixed profiles, with the real conservative initial-law lift. It retains every original 14,336 posterior per profile: 43,008 profile/posterior rows in six complete array parts, each below 830KB. The original published #6189 80-digit corpus is hash-pinned and joined by original arm/visit identity. The independent new 80-digit closed form differs by at most 3.55e-15; the real exp512 candidate reproduces its published baseline to 8.88e-16.

| Fixed profile | Maximum scaled value error | Maximum sum of absolute components |
| --- | ---: | ---: |
| exp512 | 4.00956e-6 | 4.00959e-6 |
| near800 to .5, far224 | 2.74368e-6 | 3.69706e-6 |
| near960 to .48, far64 | 3.59390e-5 | 4.87775e-5 |

All original unchanged .01 continuation checks pass, including the sum that forbids error cancellation. Near960's value error is larger than the other profiles. Whole far cells plus tail have maximum absolute contribution 1.74e-4 for near960 versus 1.47e-5 for exp512; the boundary-crossing cell is explicitly excluded. These differences combine initial-law lift, spatial operator and reset effects and do not isolate one mechanism.

The decomposition is D-A=(D-C)+(C-B)+(B-A). A is the original halfline law, B its finite-continuum nonreturning-upper approximation, C the same finite continuum with only the initial law lifted, and D the actual candidate with nodal reset. Therefore D-C combines CTMC and reset randomization; it is not a pure spatial CTMC error. Every signed component and the absolute sum are retained. Upper escape is permanently active and nonreturning.

All source was committed before execution. Source and inputs stayed unchanged. Four numerical-reference/cap tests passed. The first audit stopped before any lift/perpetual call because its guard incorrectly expected lexical arm ordering; original stderr and execution receipt remain. Source v2 follows the artifact's exact completion order. The actual published derived SUMMARY, hash 12fa561e..., independently confirms that order; this separate check is not falsely added to the auditor's executing-input guard. The successful complete attempt002 was not restarted.

The reset sweep took 7.4283s wall. The complete cost audit used 552 actual perpetual calls and about 15.68s outer wall, with original CPU/RSS and command receipts retained. It performed zero training, filter replays and DDE rollouts. These costs are shared-host development costs, not neural-model throughput or energy measurements.

Publication retains all 23 successful-stage artifacts, each Git blob matched against original local bytes, the source/geometry/lineage/physics records and all MP80 basis values. Every artifact is at most 1MiB. Read-only local verifiers checked all 2,256 sweep rows and 43,008 value rows with zero new model/kernel calls. Dedicated hosted arithmetic CI does not repeat the numerical experiments.

Draft / HOLD_NO_GO / all_closed=false. The reset sweep is exposed post-failure development, not a new prospective science gate or whole-risk-domain certificate. No relative precision below the reference floor, gaps below .001, finite horizons beyond .16, physical parameter box, new-profile gradients, whole filtering/training, C2 replay, strong baselines, real asynchronous task advantage, full cost/energy, or production adoption is qualified here.
