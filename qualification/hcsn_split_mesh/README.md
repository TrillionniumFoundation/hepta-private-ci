# Two fixed split meshes: exploratory successor

This stage follows common candidate `a12f564d5d15258f6ef5d64ceaa5966d2fd04f8f`
(#6185), in its own directory. It changes no common source and does not rewrite
the common 29-source manifest. `SplitResetAlignedSpatial` inherits the exact
common generator and point-reset convention, with an optional fixed right-hand
grading. Omitting that option preserves the common nodes, matrix and analytic
physical derivatives bit for bit, including the original default grading.

The two declared exploratory geometries both have 32 left and 32 right intervals,
reset distance .5, endpoint 2, and right grading 0. Left grading is 1 or 0.
No extra geometry search is part of this stage. The grids were chosen after
observing #6165's failures, so these results are not prospective qualification.

For drift -.12 and noise .08, both grids have minimum down rate 2.7363555556
and minimum up rate .1763555556. They admit this particular low-noise case
without clipping rates. The equal-segment grading-1 common geometry rejects
it through 64 intervals. This is a bounded domain improvement, not general
low-noise qualification. The 64 nodal rows exhaust the existing Torch law cap;
there is no room for phase rows at this resolution.

At drift -.12 and noise .5, the half-line first-hit reference at time .1 is
.0019850919213766746; its upper-reach correction is bounded by 1.16e-21.

| Left/right grading | CTMC F(.1) | Relative error at .1 | F(.01) / half-line F(.01) |
| --- | ---: | ---: | ---: |
| 1 / 0 | .0019871358933324875 | +0.102966% | 2,078,586.192 |
| 0 / 0 | .0019743033913152954 | -0.543478% | 804,116.085 |

The short rare-horizon failure remains severe and is explicitly retained by a
test. The two moderate-horizon observations cannot establish a uniform error
bound or replace the original 14,336-position qualification gate.

Four dedicated controls check inherited behavior; exact generator moments,
positive rates and five physical generator derivatives on both sides of the
former reset knot; full delayed-state physical derivatives against independent
forward finite differences; and the retained continuum failure. Generator FD
uses absolute tolerance 2e-6 plus relative tolerance 2e-7. DDE FD uses absolute
tolerance 4e-6 plus relative tolerance 5e-4; raw vectors and both step sizes
2e-4 and 1e-4 are retained. A relative tolerance must not be reported as a pure
absolute error bound.

Run `python -B -m qualification.hcsn_split_mesh.qualify --output NEW_DIRECTORY`.
The dedicated manifest and workflow bind this source and the unchanged common
dependencies. Passing these four discrete controls does not change #6185's
qualification scope. This stage supplies no Torch adapter, no learned grading,
no fixed-physical-prior migration Jacobian, and no next-hit phase readout.
It makes no claim of training benefit, independent-data generalization or Cell
adoption. Original common and #6165 negative evidence remains intact.
