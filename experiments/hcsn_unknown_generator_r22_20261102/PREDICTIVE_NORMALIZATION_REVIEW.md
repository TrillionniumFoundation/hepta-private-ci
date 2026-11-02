# Ordered predictive-law contract

Let the shared initial-pair posterior have positive coordinates `h[a,b]`. Its one-draw predictive head is `h[x0,x1] / sum(h)`. For the four later transitions (`t=2,3,4,5`), choose a row by:

| Model | Context row |
| --- | --- |
| lag1 | `x[t−1]` |
| skip2 | `x[t−2]` |
| full2 | `4*x[t−2]+x[t−1]` |

For each row `r`, let positive Dirichlet posterior coordinates be `alpha[r,j]`, row total `A[r]`, and the number of uses in the candidate ordered six-value sequence be `C[r,j]`, with total `n[r]`. The integrated probability is

\[
P(x_0,\ldots,x_5)=\frac{h[x_0,x_1]}{\sum h}
\prod_r\frac{\prod_j(\alpha_{rj})_{C_{rj}}}{(A_r)_{n_r}},
\qquad (a)_k=\prod_{i=0}^{k-1}(a+i).
\]

There is **no multinomial coefficient**: this is the probability of one ordered sequence, not the probability of a transition-count class. Different ordered paths are already distinct entries in the4096-element table. Adding count multiplicities here overcounts them.

Equivalently, start from the training posterior rows and update the row counts only along the current test-sequence prefix. This is the Polya posterior-predictive chain. Repeated visits to a row must use the updated virtual counts; resetting every visit to a fixed posterior mean reproduces the plug-in approximation rather than integrating one shared transition row.

Each such chain normalizes by successive conditional summation, so the complete4096-value table sums to1. A nonnegative normalized mixture across models, training-group components, raw versus orbit, or all24 symbol pullbacks remains normalized. Coupling independent overwrite-key parameter q gives same/distinct columns `P*(1−q)/16` and `P*((1−q)/16+q/12)`, and therefore `4*sum(same)+12*sum(distinct)=1`.

`predictive_reference.py` implements a different computation: it first forms grouped transition counts, then evaluates the rising-factorial moments using60-digit Decimal arithmetic on the exact floating-point input coordinates. It never calls the candidate sequential implementation or a world generator. It expects a4×4 positive head and a4×4 row array for lag1/skip2 or flattened16×4 rows for full2.

It also supports `homogeneous`: a4-coordinate initial marginal followed by allfive first-order transitions, t=1..5. This preserves first-step transition evidence for a strong common first-order component. It is a time-homogeneous transition model, not automatically a stationary stochastic process: stationarity additionally requires the initial marginal to satisfy `p0*T=p0`, which the fitted free head need not satisfy.

This is exact under the declared conditional model of independent Dirichlet rows and a shared initial-pair head. It is not automatically the exact Bayesian posterior of the actual synthetic family generator, whose pi may couple different rows and the head. Likewise, mixture weights selected using held-out public predictive log scores should be called learned predictive/model weights unless the implementation integrates the joint shared-parameter held-out likelihood required for a full Bayesian model-index posterior.

A shared global raw/orbit coefficient is useful for the four-arm factorial. If it is fitted on complete-sequence log score, still evaluate query-conditional Brier/calibration and real READ utility separately; finite-sample full-joint log-score improvement need not produce monotone improvement on the masked final-address task. All four arms must receive the same public fit/validation streams, repaired head and key-law estimation. Fresh calibration/confirmation remains independently frozen.
