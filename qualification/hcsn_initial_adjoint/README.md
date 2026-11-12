# Bounded initial-amplitude adjoint

Local stage 1 passed its own prefrozen small-model gates. This supplies a
continuous finite-DDE VJP without constructing an initial-basis forward map.
It is a new candidate; global HCSN qualification remains HOLD.

The numerical source and complete acceptance matrix were committed as
`caba5a3f3a77d0a6eb7d54b5a906ae3bbb4fb772` before the only local001 run.
The result belongs to those exact bytes. The two published Python files were
subsequently formatted; `evidence/FORMAT.json` records complete normalized AST
equivalence. No numerical test was rerun after formatting. To reproduce this
original request, use that prefreeze commit or its exact source archive,
rather than relabeling a run of the published formatted bytes.

Actual scope is uniform N=7 and graded N=12, fixed physics/actual nodes/reset,
fixed atom and uniform phase supports, up to three marks, queries through
.53 with delay .21. Probability and signed-content amplitudes share the same
linear VJP. The lower boundary is excluded and upper escape retained.
The objective follows post-release query semantics, including atom/query
coincidences and a query at zero. `SPEC.md` defines the equations and sides.

The 69 old-forward-basis contractions agreed within 1.282e-10 (uniform) and
4.866e-9 (graded). Ten directions per geometry were checked against retained
coarse/fine FD scalar contractions; no old basis or FD experiment was rerun.
Time tightening, exact mass gradients, Bellman continuation gradients,
atom/uniform fronts, upper occupation, scalar delay direction and physical
discount clock all passed. All 345 compared scalar values passed their
prefrozen mixed gates. These are not rare-tail relative guarantees.

Cost was 18 new adjoint calls, including two zero-horizon calls; 196 independent
small matrix exponentials; and two static perpetual solves. There were zero
forward DDE/basis calls, Torch calls or optimizer updates. Actual wall time was
2.66415 seconds, CPU 2.64862 seconds, and peak process RSS 72760 KiB on the
recorded Python 3.12.14 CPU environment with numerical threads fixed at one.
Per-call maxima were 3056 accepted steps, 6142 RHS evaluations, 934247 stored
float64 polynomial/snapshot coefficients, and 147 current sparse-Jacobian
nonzeros. The tightened graded run approaches the declared coefficient cap;
larger meshes have not been admitted. A stored-coefficient cap is not an RSS
limit, and sparse current actions do not establish total O(N) solver cost.

Original arrays, source bytes, START, complete stdout/stderr and result are
in `evidence/LOCAL001-ORIGINALS.tar.gz`, whose SHA and per-member inventory
are in `evidence/LOCAL001-ARCHIVE.json`. `evidence/local001/RESULT.json` and
`ARRAYS.npz` are convenient identical copies. Source-before/after matched.
The numerical stage mutates live query/support/model containers after
freezing and still matches the original oracle. Snapshot identity/read-only
rejection logic is present; separate adversarial input guards and a real
Torch backward remain open. The first formatter invocation lacked a local
Git HEAD; its exact RED is retained, followed by a successful invocation
after creating a formatting-scope-only local HEAD. It is not numerical
candidate evidence or a replacement for the remote prefreeze identity.

Still OPEN: independent review of this new stage, a real first-order Torch
adapter and all version/metadata guards, larger-mesh resource/error gates,
support/delay/physics/migration derivatives, full-network training and
restoration, continuum finite-risk accuracy and independent task controls.
No existing physical-only or #6241 qualification has been broadened.
