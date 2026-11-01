# Finite permutation-symmetric transition acceleration

The existing forty-state row generator has ten physical phases and four exchangeable content classes. Let S be its equal-content block and H any unequal-content block. The candidate requires all sixteen blocks to agree **bit for bit** with S or H; it never symmetrizes an approximately symmetric fitted matrix.

In real arithmetic,

\[
Q=S\otimes I_4+H\otimes(J_4-I_4),\qquad
A=S+3H,\quad B=S-H.
\]

The uniform content subspace has generator A and its orthogonal complement has generator B. Consequently,

\[
e^{tQ}=e^{tB}\otimes I_4+(e^{tA}-e^{tB})\otimes J_4/4.
\]

Direct subtraction can erase small positive off-content tails. Instead exponentiate

\[
L=\begin{pmatrix}B&4H\\0&A\end{pmatrix}.
\]

Its upper-right block is

\[
\Delta(t)=\int_0^t e^{B(t-s)}(A-B)e^{As}\,ds=e^{At}-e^{Bt}.
\]

The equality follows by integrating the derivative of `exp(B(t-s)) exp(As)`; it does not require A and B to commute. The implementation checks that L is Metzler and H nonnegative, so its exponential and reconstructed forty-state transition are nonnegative in exact arithmetic. Actual FP64 results are checked for finite nonnegative entries; there is no clipping, epsilon floor, renormalization, or altered generator. Zero, tiny, moderate and long durations are independently compared with dense exponentiation and the full matrix ODE.

Unsupported matrices use the original dense method and record ineligibility. Some free-rate fitted matrices differ between content diagonals by one floating-point rounding step, so approximate symmetry is deliberately rejected. Original law arrays, financial parameters, operator identity, model identity, emissions, rewards, policies and tie rules remain unchanged.

## Interpretation

This optimization is equally available to the HX law and its same-matrix ordinary HMM comparator. Faster finite exponentiation cannot establish an HX-exclusive representation, independent core quality gain, continuous free-boundary optimality, GPU/energy advantage, or production ownership qualification.

The execution comparison demands exact agreement of action/answer/token/fee/utility records. Checkpoint hashes remain in raw records but are compared separately because numeric roundoff changes hashes. Numeric checkpoint arrays are compared only at the executor's existing zero-based query2 checkpoint, after the third query; this does not audit every intermediate state, the final state, a cold process, or a pending action. Numeric differences cannot excuse an action or answer mismatch.

Model preparation and measured execution CPU are reported separately. A combined preparation ratio allocates each shared law's preparation equally to the two representations. Full child receipts include interpreter/import, all attempted work, output serialization/writing and process exit. These are finite reference costs, not complete training or deployment economics. CPU seconds are not joules.
