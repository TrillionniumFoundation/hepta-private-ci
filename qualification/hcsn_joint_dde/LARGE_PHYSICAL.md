# Sparse instantaneous Jacobian and bounded original-law partials

The former conservative dense same-channel cross blocks limited the physical
variational solver to small meshes. The augmented linear DDE now supplies its
actual instantaneous sparse Jacobian to BDF. Each method-of-steps segment
treats delayed history and external phase release as known forcing. Six
diagonal blocks contain the current linear operator; each physical partial has
only its own primal forcing block. Discounted event, occupation and remaining
phase terms retain their parameter derivatives.

The callback was compared with the actual captured augmented RHS at three
times and two central state-FD steps: 2,381,400 matrix-coordinate comparisons,
zero failures. Eight affected uniform/graded flow tests pass. Their stderr
retains one SciPy BDF invalid-subtraction warning; all returned-finite guards
and physical FD assertions passed. This is a separate new-source execution.

The original seed37/c0_b1/update24/position1 law and four signed content
channels were recovered from artifact 13904346161. The complete journal SHA,
original selected line, model identity and 896-position prefix were checked;
the selection independently matches the frozen original maximum-first-cell
case. Recovery is retained in #6223, exact head
`676a1ec677b64e1970e8079aaa799e513d59e5d6`. New JSON exports disclose the
recovery and hold the migrated law fixed. Both NPZ files reproduce the exact
previously recorded, subsequently lost export hashes. Old JSON bytes were not
reconstructed. No original training step or optimizer was replayed.

| Original fixed posterior | n128 | n512 |
| --- | ---: | ---: |
| Physical Jacobian coordinates | 3,325 | 12,925 |
| Both FD steps / stability failures | 0 | 0 |
| Maximum fine-FD absolute error | 9.89e-10 | 6.67e-10 |
| Maximum mixed-tolerance gate ratio | 0.000337 | 0.000346 |
| Augmented state scalars | 3,990 | 15,510 |
| Instantaneous support nonzeros, upper bound | 23,665 | 94,705 |
| Complete diagnostic wall after imports | 6.515 s | 72.423 s |
| Variational flow wall | 2.067 s | 37.804 s |
| Process maximum RSS | 214,860 KiB | 819,056 KiB |

Each profile executes one variational flow, one unchanged-forward baseline
and twenty central-FD forward flows. Both steps, 2e-4 and 1e-4, stay within the
same actual reset stencil. The predeclared error gate is 3e-6 + 4e-4*abs(FD),
with stability gate 5e-6 + 6e-4*abs(fine FD). Original n128 passed before the
n512 invocation. Primal disagreements with the unchanged forward solver are
below 1.1e-11. All source and input guards match.

The original profile uses the recorded .02 interval, below the .2 delay. It
checks the first DDE segment and initial phase release, without a new-hit
second-cycle feedback qualification at either large mesh. B and absolute reset
affect only the local reset interpolation under this fixed relative prior;
the two columns are not independent identifiable boundary/prior effects.
The n512 array has 10,005 fine-FD values below the absolute tolerance and 213
undefined ordinary relative ratios. These are mixed absolute/relative checks,
not a rare-tail relative-precision certificate or continuum-accuracy result.

Two additional disclosed n128 controls precede the original profile: a first
uniform-cell law and a uniform/phase mixture, both with four declared signed
marks. The pure first-cell control correctly has zero B/reset derivatives
before any reset release. No corresponding n512 control flow was executed.
The four completed diagnostic profiles total four variational and 84 primal
flows, 92.625 seconds after imports, and zero optimizer updates. Regression and
RHS costs are recorded separately. This is not a serving, energy, neural
training, or complete project cost measurement.

The initial numeric-sparsity n128 attempt ended with observed Killed/exit 137
and no result. Its cause is unknown; no authoritative OOM evidence was
available. The executor then became unavailable, and the original scratch
directory was absent after replacement. The observed terminal/preflight
summary was already committed in d3722803; the lost local receipt cannot be
represented as recovered original bytes. The replacement exact-Jacobian
attempts above have new source identities and retained complete outputs.

The enlarged input admission checks cap augmented state at 32,768 scalars,
conservative dense coefficients at `20*(N+5)^2 <= 12,000,000`, instantaneous
support at 2,000,000 nonzeros, and snapshots at 2,000,000 scalars. These are
explicit component budgets, not a peak RSS guarantee. The returned historical
field `instantaneous_jacobian_nonzeros` counts the support upper bound, rather
than the actual callback nonzeros at a chosen time.

`ORIGINALS.tar.gz` is stored as five ordered binary parts; join the paths in
`ORIGINALS.parts.json` and verify the recorded complete size/SHA before extraction.
It retains raw arrays, plus/minus outputs, fixed-law exports,
the original selected journal line and recovery receipt, all cost/stderr logs,
and exact executing sources. `FORMAT.json` independently links fourteen
tested source byte identities to published bytes with identical normalized
ASTs; no tests or model runs followed final formatting. The earlier small
source-stage archive remains separately retained in the branch history.

This closes only the disclosed original-law n128/n512 discrete physical
partial checks. New grids, v3, other priors, multi-cycle large-mesh flows,
episode/migration/filter/network gradients, full training replay, continuum
rare-phase precision, equal-quality comparisons, future tasks and adoption
remain separate gates. Global status remains Draft / HOLD_NO_GO.

The `candidate_source_commit` copied from each input describes its original
migration baseline, not this new numerical kernel. Exact tested source SHA256s,
the source archive and the format witness bind the present execution.

Inherited uniform and graded Torch CI remain enabled. Any actual hosted
optimizer calls are separate new-source small-mesh regressions and must be
counted separately; they cannot qualify a large-mesh Torch/network execution.
