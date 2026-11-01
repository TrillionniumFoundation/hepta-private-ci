# Eight masses with explicit phase-shape loss

The frozen R15 state is `(phase, content)`, with eight active phases, two recovery
phases and four content classes. Let `C` collect each active/recovery by content
block. Let `R` spread its mass uniformly over its eight or two phases. Both are
nonnegative stochastic kernels and `RC = I_8`. The reconstruction is `pCR`.
It retains eight block masses exactly in real arithmetic and satisfies

\[
p_z>0 \quad\Longrightarrow\quad (pCR)_z>0.
\]

Uniform shape is an explicit model approximation, not a floor on observations.
It may add phase support within an occupied block, but never removes positive
support in exact arithmetic. Empty blocks stay empty. The implementation rejects
unrepresentable subnormal reconstruction instead of silently deleting support.
Floating-point validation is separately finite; no whole-domain numerical
certificate is claimed.

## Observations, writes, propagation and support

R15 READ, REFRESH and the content reward are constant over phase within each
block. Therefore `pCRE = pE` immediately after compression. Bayes updating on a
legal observation remains legal, and compression preserves the resulting block
masses. A read erasure retains recovery mass, unlike the frozen index-mean
projection. The original mean projection and its invalid result are unchanged.

If `supp(p)` is contained in `supp(q)`, then the inclusion is preserved by a
common nonnegative transition, by multiplication with a common nonnegative
observation likelihood, and by the common deterministic public WRITE mapping.
Normalization of a legal observation does not change support. Induction proves
that repeatedly applying the declared compression cannot convert a possible
observation into an impossible one, in exact arithmetic under the same finite
model and emission law. This is a support statement, not equality of posterior
probabilities, decision values, or likelihood calibration. It is not a claim
about arbitrary observation channels that vary within a phase group.

## Two intentionally distinct time semantics

`PackedBeliefMemory` stores four arrays of eight masses and advances with

\[
K(t)=R\exp(tQ)C.
\]

Its expanded state equals the forty-state filter that projects at every advance.
In general `K(s)K(t) != K(s+t)`: splitting an interval silently adds another
information-destroying projection. The audit measures and reports this defect.
This candidate does **not** pass the continuous time segmentation contract.

`AnchoredPackedMemory` instead stores eight masses and the last observation/write
time per address. At elapsed time `t`, it materializes `zR exp(tQ)` without
compressing again. Missing observations only advance the public clock. Only a
real observed symbol or public WRITE creates a new compressed anchor. Thus
splitting a no-observation interval does not change the mathematical state;
floating-point clock accumulation is measured separately. The initial phase
shape is also compressed explicitly for every address.

This anchored model is an age-dependent filter, not an eight-state Markov chain.
The current-query planner must mirror its projection times: WAIT propagates the
full temporary distribution, and only a future observed token is projected.
A forty-state planner that projects after every WAIT describes another model.

## Storage and cost scope

For four addresses the packed masses use 256 numeric bytes. The anchored variant
also uses 32 bytes for per-address event times and 8 bytes for the global clock:
296 numeric bytes. Python objects, counters, the forty-state model, cached
transitions, temporary expanded probabilities, planning branches and checkpoint
serialization are additional costs. The full R15 belief arrays use 1280 numeric
bytes, plus their own clock and other state. These counts are not a process-RSS,
latency, throughput, or energy measurement. Full execution costs must be measured
before making a cost-admission claim.

## Independent finite reference

`operator_audit.py` integrates forward conservative and killed equations and
backward event-reward equations with SciPy DOP853. Its right-hand side uses the
frozen generator directly and does not call project transition/event routines.
It compares probabilities, first hits, survival, repeated-event counts, the time
derivative and semigroup composition. It additionally checks basis-state support
and actual observations, overwrites and checkpoint restoration after irregular
missing-observation intervals. This reference does not establish finite-grid to
continuum convergence, financial parameter gradients or full financial FP32
qualification.
