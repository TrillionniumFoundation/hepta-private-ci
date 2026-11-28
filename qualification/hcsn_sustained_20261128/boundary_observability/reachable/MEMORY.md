# Recoverability when the receiver remembers previous boundaries

For the stock identity sender with zero recurrent feedback in this example, the three input levels map to three log-boundary levels whose closest pair is more than .13 apart. Every tabulated boundary sequence therefore identifies its ternary controls, even allowing additive error of .001 per boundary observation. The following values are sharp worst-case absolute errors in predicting the next physical first-passage probability at the fixed common input +.77 on the 32-atom stock grid. Inputs within the window take the same three values as the reachable-state experiment, and the last observed input is zero.

| Number of observed boundaries | Fixed reset, 729 realizable histories | Arbitrary initial distribution, worst moving boundary sequence | Arbitrary initial distribution, constant zero boundary |
|---:|---:|---:|---:|
| 1 | .109493 | .500000 | .500000 |
| 2 | .085371 | .302821 | .299365 |
| 4 | .053161 | .296958 | .186830 |
| 6 | .020582 | .288840 | .153498 |
| 7 | 0 | .281435 | .140025 |
| 11 | — | .267052 | .105356 |
| 32 | — | — | .037365 |
| 64 | — | — | .008948 |
| 128 | — | — | .000520 |

For trajectories starting from the known stock reset, grouping the 729 histories by the visible suffix gives the exact finite-dictionary minimax radius by half the largest within-group range. A full seven-frame record determines the starting state and complete input sequence, making forward replay exact. A receiver with an explicitly carried state can therefore transmit one observed boundary per step in this fixed-parameter submodel.

For arbitrary initial distributions at the beginning of the observation window, the transition for each pair of boundary levels is a stochastic matrix on the live grid and the single refractory state. Fix a visible control path, multiply its matrices, then apply the next-hit vector. Half the difference between the largest and smallest entries of the resulting vector is the minimax error for that path. Point masses on the two attaining coordinates witness the lower bound, and the midpoint attains it. Exhaustive backward products give the worst over all paths with a zero final boundary up to depth eleven (59,049 paths at depth eleven). The program verifies each maximizing witness by a separate forward propagation from both endpoint atoms. Zero-boundary powers quantify loss of initial-state information through 1,024 observed boundaries. Long-timescale decay is specific to this capped discretized grid and its reset law. The freely chosen initial atoms in the arbitrary-prior columns need not arise from the six-frame fixed-reset experiment.

[Exact radii and witness controls for all shocks and both grids](boundary_memory.json) · [Backward enumeration and forward replay](boundary_memory.py) · [Single-frame observable port study](README.md).
