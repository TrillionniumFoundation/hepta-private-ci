# R15 executed nonconvex forward Stem — positive certificate, negative solver evidence
Exact complete-square identity:
J(a,b)=179/400+(ab-3/4)^2+(a-b)^2/4.
Thus the exact unrestricted global optimum is 179/400, uniquely up to sign pair a=b=±sqrt(3/4). At (0,0) the true gradient is identically zero but the Hessian has minimum eigenvalue -3/2, so it is a **saddle** with exact cost excess 9/16.
24 real SciPy fits (8 deterministic initializations x BFGS, trust-exact, L-BFGS-B) ran. Global successful endpoints by method: BFGS 5/8, trust-exact 7/8, L-BFGS-B 5/8. All raw outcomes including saddles retained in the conversation source packet. This is nonconvex IN THE LEARNED PARAMETERS with two genuinely sequential forward layers and an independent terminal Bernoulli noise. **It is risk neutral**, not a new two-step nonzero-risk entropic proof; no universal solver superiority or neural/LLM scaling inference.
The first development test detected an incorrect sum-of-squares constant; the identity was repaired using exact fractions and all 6 tests rerun successfully. Historical R14 results, deployment models and CI contracts are unchanged. Hosted CI has not been qualified on this work.
