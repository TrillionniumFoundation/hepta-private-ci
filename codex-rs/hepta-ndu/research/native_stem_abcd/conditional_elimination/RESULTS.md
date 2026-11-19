# R24 completed — conditional Bernoulli-risk elimination and rigorous old-witness counterexample

**Exact parent** R23 PR #2206 at 244b373d2bc4e20bb427b1941583bb328d6cfd19. Protocol was actually pushed BEFORE all three R24 4,000-cap efficacy certificates. No model weights were fitted, resumed, or changed, and R21–R23 qualifications remain intact.

R24 algebraically eliminates both inner Bernoulli outcomes into exact logcosh conditional functions, and uses 33 rational strongly-convex scalar tangent envelopes at each of four initial (X,P0) combinations. The new lower is max(R22 exact centered lower, conditional-risk lower), hence globally valid and no weaker on the SAME parameter box. It does not assume global convexity in learned weights. All proof/prune decisions use exact Fraction; float only prioritizes the search.

| width | R22 gap | R23 gap | R24 gap | R24 splits | R24 CPU s | R24 certified |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2 | .00990816 | .00948989 | 0.009908157897112 | 525 | 13.260119 | YES |
| 3 | .01561546 | .01513566 | 0.015552666033249 | 4000 | 126.766487 | NO |
| 4 | .13046635 | .09844534 | 0.128212414396649 | 4000 | 146.270052 | NO |

R24 is cheaper than R23 on this assistant CPU slice but does not achieve better final gaps. Its fixed quarter-step tangent anchor grid leaves extra enclosure slack near the selected candidates; this is disclosed instead of posthoc densifying the grid. This experiment does NOT establish superior certificate scaling.

**More decisive strict posthoc witness:** Original R21 archived **w3-s6-bfgs** has a proved upper bound .6518681756413304, while the exact original frozen width3 candidate has proved lower bound .6670003697789101. Hence the candidate's true global excess is **strictly greater than .0151321941375**, making the unchanged .01 target MATHEMATICALLY IMPOSSIBLE for THIS width3 candidate. The witness is an already fitted old weight vector, not R24 new training. Its signed float64 tensor SHA256 is 3b93b227b433cd15a8c622a3eed07886dbff3b009aac8667cabf2e4fe987f5c9. Width4 has a candidate-vs-witness cost-gap lower bound only .00613908, which does **not** exclude .01 certification.

**Verification:** 10 new analytical/moment/strong-tangent/90-digit independent mpmath tests passed; 16 unchanged R22/R23 mathematical tests passed; seven actual saved-file tamper tests passed under `python -O`. Initial command accidentally discovered R23's same-named tamper test suite, which failed from absent historical paths: retained, corrected directory, then all R24 7/7 passed. No research fit or score was changed. Read-only audit verifies complete 8525 split identities/covers and exact final frontier rational minima, source hashes including old R21/R22 files, and 1134 deterministic exact expensive box bounds; it does NOT recompute all 8,525 expensive child lowers. Audit uses 16.965097 CPU seconds. A separate original R21 archive SHA and complete 120-row index were reread; three witness tensor hashes individually checked.

**Resources:** R24 certificate CPUs 286.296658 seconds, per-width peak RSS 98.25/120.51/118.51 MiB; tests/audit/archive/plugin actions extra. No new gradient fitting, no GPU, energy/FLOP, native hardware or full work TCO claim. Existing project/global CI success is not asserted; keep Draft and no main/CURRENT/production change.

**Scope:** known 16-leaf positive-risk two-step finite-state system; this is not a general continuous-law, arbitrary forward-model, high-dimensional FBSDE or language-model theorem. Next research investment should FIRST replace provably suboptimal width3 incumbent, with a fresh **prospectively frozen** candidate and identical proof budget, then tackle width4 dependency with adaptive risk tangents or structured variable elimination. Such future work is not reported as executed in R24.
