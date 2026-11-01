# R16 grouped compression: scope and proof

The implementation wraps the frozen R15 40-state law. It does not change its
generator, emissions, rewards, financial parameterization, or hidden-world
owner. Projection mode is recorded separately from model identity.

## Construction

Write the joint belief as `p[i,c]`, with ten phase indices and four content
classes. Partition phases into groups `g`. Every implemented group lies wholly
inside active phases `0..7` or recovery phases `8..9`. Define

\[
a_i=\sum_c p_{ic},\qquad b_{gc}=\sum_{i\in g}p_{ic},\qquad
m_g=\sum_{i\in g,c}p_{ic}.
\]

For positive group mass the lifted compressed belief is

\[
(Cp)_{ic}=a_i b_{g(i)c}/m_{g(i)}.
\]

An empty group remains exactly zero. No epsilon, pseudocount, or minimum
probability is added. Code divides by group mass before multiplying, to avoid
unnecessary intermediate underflow.

## Exact-arithmetic statements

1. **Mass and retained marginals.** Summing over content gives `a_i`.
   Summing over phases in a group gives `b_gc`. Total probability, the full
   phase marginal, the full content marginal, and group-by-content probabilities
   are therefore preserved.
2. **Support inclusion.** If `p_ic > 0`, then `a_i > 0`, `b_gc > 0` and
   `m_g > 0`, so `(Cp)_ic > 0`. Compression may introduce additional possible
   phase-content combinations; it never removes a positive original entry.
3. **Idempotence.** The formula depends only on the two retained marginals,
   which the first projection preserves. Applying it twice gives the same
   result as applying it once.
4. **Current emission likelihood.** R15 READ emission probabilities depend
   only on active/recovery status and content; REFRESH depends only on content.
   Both are constant in phase within each group. The expectation of each
   emission column is consequently unchanged by a single projection.

For two beliefs with `supp(p)` contained in `supp(q)`, multiplication by any
nonnegative transition matrix preserves that inclusion. A deterministic public
WRITE is another nonnegative linear map, so it does too. Multiplication by the
same nonnegative observation likelihood vector preserves inclusion before
normalization. If that observation has positive likelihood under `p`, it also
has positive likelihood under `q`; normalization preserves the remaining
support. Starting from the same prior, repeated propagation, public WRITE,
Bayesian observation, and grouped projection therefore cannot make a
model-legitimate observation impossible in exact arithmetic.

These statements require the same transition/emission support and a legal
common initial prior. They do not establish exact posterior values, future
emission likelihoods, optimal actions, or task utility after compressed
propagation. In particular, within-group phase-content correlation is discarded
and may matter to later absorption and recovery. The construction is an
ordinary probability-model baseline; it is not specific to HX dynamics.

## Floating-point boundary

The exact-arithmetic theorem is not a global floating-point theorem. A positive
input coordinate can lead to a mathematically positive compressed coordinate
below the smallest float64 value. The implementation explicitly raises
`ProjectionPrecisionError` when the lift would erase positive support. It does
not conceal such failure with smoothing. The validation includes accepted
rare-coordinate cases through `1e-150` and a rejected `1e-200` correlated case
whose projected coordinate is about `1e-400`.

These checks do not certify every floating-point operation in matrix
propagation or Bayes normalization. Wider precision or a logarithmic
representation remains necessary if that broader numerical contract is
required. The ordinary R15 `mean` mode is unchanged and remains a separate,
historically invalid comparator for its erased-support case.

## Storage and execution cost

| Format | Phase groups | Stored float64 values | Interior degrees of freedom | Stored array bytes |
| --- | --- | ---: | ---: | ---: |
| block2 | active; recovery | 18 | 15 | 144 |
| block4 | 0–2; 3–5; 6–7; 8–9 | 26 | 21 | 208 |
| block5 | adjacent pairs | 30 | 24 | 240 |
| full joint | all 40 entries | 40 | 39 | 320 |

`encode` implements the compact representation as phase masses plus per-group
conditional content distributions; `decode` validates and lifts it. The R15
owner adapter currently keeps the lifted 40-entry state and calls the original
40-state propagator/planner. The compact bytes above describe encoded arrays,
not actual total process memory, the current owner checkpoint, or a measured
runtime saving. Python-object overhead and transient arrays are excluded.

## Executed evidence

`COMPRESSION_VALIDATION.json` records the model identities, source hashes,
maximum invariant errors, and exact trace digest. The executable checks use
556 sparse, dense, extreme, and one-hot beliefs per mode, and arbitrary batch
dimensions. On 32 real R15 owner worlds from disjoint development seed values,
the same causal READ schedule exercises 576 legal observations, including 37
recovery erasures. The three formats each preserve support and complete 1,728
paired checkpoint continuations in total with zero impossible observations.
This is a representation/recovery correctness result; it does not test learned
reset timing or establish a net-utility advantage.

Reproduce from the repository root:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m tools.hcsn.reachable_state_r16_20261101.compression_checks
```
