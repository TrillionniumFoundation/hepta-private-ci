# A known future regime shift changes the optimal action at the same present intensity

Under the Table I normalization, an asset value of 70 and current shock intensity 1 can call for continued operation or immediate abandonment in the coupled experiment. With one quarter-year before the intervention, the 1,024-step original grid brackets the decision transition at [67.75, 68.44] with future intensity 1, and [74.24, 75.00] with future intensity 4. Shifting the grid origin by half a cell yields [67.41, 68.10] and [74.62, 75.38]. In both grids 70 is well outside the ambiguous cells, on opposite sides of the two policies. A time-local substitution of the present intensity into the stationary formula gives 67.4415 in both situations. These are computed decisions in an extension of the financial model. A neuron's measured policy is a separate empirical question.

The announced intensity rise also lowers both channel values at the registered site V=75. The units below follow the paper's normalized monetary simulation. Deltas are announced path minus the same-grid 1→1 null, a quarter-year before arrival.

| steps/year | offset (grid cells) | 1→4 equity | 1→4 one-year issue | 1→2 equity | 1→2 one-year issue |
|---:|---:|---:|---:|---:|---:|
|64|0|−4.332|−5.033|−2.341|−1.889|
|128|0|−4.335|−4.919|−2.355|−1.670|
|256|0|−4.307|−4.648|−2.319|−1.506|
|512|0|−4.302|−4.626|−2.320|−1.716|
|512|0.5|−4.300|−4.568|−2.334|−1.692|
|1024|0|−4.291|−4.358|−2.328|−1.765|
|1024|0.5|−4.302|−4.608|−2.333|−1.738|

The bond effect is sensitive to grid placement. The 1,024-step estimates differ by 0.250 for this readout. The discrete barrier is observed only to a cell, and finite mesh movement can cause the site at 75 to sit on different sides at different resolutions. The stationary analytical one-year issue with intensity 1 and asset 75 is 49.74982. After advancing a full stationary year the 1,024-step solvers produce 49.54026 and 49.76986. Their corresponding stationary equity values are 4.26049 and 4.33427, versus analytical 4.32106. These checks support the sign and order of the reported counterexample. They do not establish the continuum free boundary to within one grid cell. Full values, intermediate times, constant and reverse switches at all four sites are in grids.zip.

## Recursion and independent replay

Let K be the trinomial expectation on log assets and let A(q)=(1−exp(−qΔ))/q. For an alive issuer the j-step bond continuation is c A(q)+exp(−qΔ) Kd_next(j−1); its j=M value is the new issue quote. The equity continuation is A(r)[δV−(1−π)C+d_cont(M)−p]+exp(−rΔ)KE_next. At each decision date recover αV/m on debt and zero on equity if this continuation is nonpositive. On a lattice exact maturity and decision can coincide, with recovery paid if default occurs first at that date. Terminal values at the regime change are the analytical post-change equity and a full set of stationary residual-maturity debt prices. A one-dimensional quadrature computes terminal equity. The positive lattice matches the first two log-increment moments; upper and lower ghost values extrapolate linearly in asset level. The running one-period cash flow is frozen at the current grid state. The grid policy had a single contiguous stopping region at every date in all 35 runs.

Independent Monte Carlo used 160,000 paths per initial site and common random numbers for the 1→1 and 1→4 pair. It priced actual discrete-policy cashflows, used the first-passage density to rederive the terminal bond, and encountered no truncated-grid exit. At V=75 on the 256 grid it estimated paired equity −4.34174 (SE 0.02168, grid −4.30680) and bond −4.68662 (SE 0.01843, grid −4.64800). The bond contrast differs by 2.095 standard errors, just outside its nominal 95% interval. It is retained. Across sites and both valuations the largest single-policy |z| was also 2.095. A Monte Carlo path replays the grid law; it does not remove the continuous-time discretization error.

Run solve.py for the specified grids and offsets and replay.py on the default 256-grid cached policies. The first two Euler cashflow approximations and the binary action imply that differentiating a shifted discrete action index is not justified. The source's stationary smooth pasting at contact does not establish a differentiable time-dependent policy-index message.
