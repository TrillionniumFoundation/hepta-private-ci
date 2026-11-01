# Exact finite Bellman forest optimization

The original planner evaluates the same WAIT and READ successor horizon separately. The first candidate concatenated numerical belief matrices before multiplication; this changed BLAS reduction order and produced 53 near-tie action differences on 2,304 development fixtures, despite differences of at most 3.33e−16. That candidate remains failed and is archived under `development/attempt_01`. Numerical closeness does not excuse those different actions.

The frozen candidate instead carries a forest of the **original logical arrays**. For every original recursion node it preserves the matrix multiplication shape, the original input array, the elementwise multiplication/division/summation sequence, the original floating fee subtraction order, and the original max/argmax rule. WAIT and READ reuse one already-identical `p @ P1` calculation. Neither branch mutates it. Equal-horizon nodes are processed together, but their numerical matrix products are not concatenated.

Only the validity checks are combined across rows. Full-state projection still checks the original finite/nonnegative-with-tolerance/normalized contract and copies the original arrays. Block projection still performs every frame's original `@ COLLECT` and `@ SPREAD` operation, with the same strict nonnegativity, normalization and positive-support checks; their rowwise validation is shared. Validation concatenation never supplies a numeric state used in a matrix product.

For READ and REFRESH, every token branch is retained. A zero-likelihood observation receives the same prior substitute and the same zero branch weight. WAIT projects after propagation in the full planner and does not project in the anchored planner. Actual observations project at the same original points. No emission, likelihood, fee, event, target, policy, law matrix, or probability floor changes.

At horizon zero only the STOP score is finite. An internal one-column terminal table avoids allocating the three negative-infinity columns; taking its maximum gives exactly the same score. The public `values` dictionary still contains only STOP there. Logical `belief_evaluations` counts include the same original tree nodes and rows, even though Python recursion and validation calls are fewer.

The immutable kernel cache retains original transitions and their original `matrix @ reward` values. These depend on the law and interval, not prices, belief, representation or observations. Cache entries include the law object's identity and immutable model identity; no actions, outcomes or fitted parameters are cached. Its wrapper capacity is 64 entries. The inherited law's transition cache remains separately accounted and has no claimed arbitrary-time bound.

This reasoning concerns the declared finite algorithm and controlled floating implementation. The frozen differential evidence and fresh execution comparison are the actual bit-equality checks; there is no claim that a different BLAS/runtime, changed law, unrestricted model mutation or production ownership has been qualified.

The same optimization applies to the same-matrix ordinary HMM comparator. Incremental planner acceleration cannot establish an HX-exclusive core gain or change earlier anchored-versus-full, D−B, multimodal, GPU or energy gates.

## Identical normalization predicate

The final candidate preserves the inherited `np.asarray(dtype=float)` conversion, finite test, negative allowance (`-1e-13` for full; zero for packed probability), and `2e-11` absolute normalization tolerance. With scalar reference one, `rtol=0` and finite FP64 row sums, the inherited `allclose(sum, 1, rtol=0, atol=2e-11)` is precisely `all(abs(sum - 1) <= 2e-11)`. Evaluating this same predicate directly avoids general `isclose` argument handling; it does not introduce a new tolerance or change any state number. The original per-row sum shape/order is retained. Independent boundary tests include tolerance endpoints, nextafter neighbours, the negative allowance, nonfinite inputs and FP32 input conversion.
