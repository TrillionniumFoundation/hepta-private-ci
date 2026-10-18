# NDU/System2 short-horizon FBSDE shadow contract

This qualification contract records a bounded forward/backward stochastic step as a digest-linked System2 trajectory. A problem carries a local contraction certificate: the horizon is limited and the product of the step contraction bound and horizon must remain below one. This is metadata for a mathematical/evaluation gate; it is not a proof that a neural approximation solved the problem.

Each successful step binds the exact problem, trajectory, step index, parent state, next state, (Y), (Z), noise, utility interval, residual, memory, and latency. The next step can consume only the previous step's exact state digest. Failed, cancelled, indeterminate, replayed, over-budget, or drifted steps fail closed. A trajectory becomes successful only after all bounded horizon steps have been appended.

The module does not solve an FBSDE, train weights, call a worker, or grant authority. It is intended to wrap an independently verified numerical solver and a held-out evaluator. The short-horizon contraction pattern follows the standard existence/uniqueness strategy based on a contraction mapping; deep FBSDE methods provide a separate numerical approximation path for high-dimensional problems.
