# Retained first-cycle discounted math — HOLD

This stage reads the four already published near800/near960 DDE arrays from #6224, inherited unchanged by #6235. It does not import or call a candidate model, spatial generator, DDE solver, adapter, optimizer or training loop. It changes no mesh and launches no new trajectory. Only independent analytic continuum quadrature and retained arithmetic are new.

Source was pushed before execution at 14cefc8404a057f897c371619c50d780fa185942. The complete 24 retained query rows and 12 unique continuum cases at both 80/120 digits are retained, together with original stdout/stderr, source/input guards and cost. All guards agree; the 60.0473s analytic audit was not restarted. Density and CDF endpoint normalization prevent rare integral values from being swallowed by absolute quadrature tolerance. Compared reference quantities agree to at most 4.39e-80 relative across the two precisions; this agreement is not a certified interval error enclosure.

The fixed law has initial remaining phase Uniform[0,.025], reset .32 or .32725, mu=-.12, sigma=.35, q=.15 and delay=.2; queries are .001/.003/.02/.04/.08/.16. Inputs use the explicit exact-binary64 convention, including the float support used by the retained solver. All horizons are below the delay, so a new hit cannot yet release again.

Let f/F/S be active first-hit density/CDF/survival and a(s)=min(w,T-s). Positive references are M=int a(s)f(s)ds/w, H=int exp(-qs)f(s)[1-exp(-qa(s))]ds/(qw), and A=int exp(-qs)S(s)[1-exp(-qa(s))]ds/(qw). H discounts absolute hit time, including waiting for initial release. At T>w the phase kink T-w is split. The implementation evaluates A as positive release-only occupation minus a separately integrated positive hit loss; it does not infer that rare loss by subtracting rounded O(T) totals.

| Retained tight case at .02 | Relative M error | Relative H error | Relative total Z error | Relative inferred new-hit Z error |
| --- | ---: | ---: | ---: | ---: |
| near800, atol1e-18 | 1.328133% | 1.328153% | 3.17e-13 | 1.371668% |
| near960, atol1e-18 | .985059% | .985072% | 7.65e-14 | .911826% |

Unreleased initial phase is O(1) at .02. Excellent total R/Z precision therefore does not establish rare new-hit precision. Stored FP64 Z minus its known initial-phase component is used only to diagnose this issue; subtraction does not restore bits absent from the stored state. Early-gap/below-floor M/H/Z-newhit and rare active hit loss retain the unchanged 1e-12 relative-reference floor and have no relative admission.

The audit also measures exact first-cycle identities: R=u+M, Pactive=1-R, qA=K-H-exp(-qT)Pactive, and Z=Zinitial+exp[-q(delay-T)]H. Active probability includes the upper permanently-active escape coordinate. Stored residuals are not clipped or corrected. Near960's largest active and discounted-active balance residuals are about 4.00e-12 and 3.95e-12. A total-mass residual is not an accuracy bound for a rare event. Signed mark -.7 is checked through all stored flow fields.

All original inputs and the exact upstream executing-source hashes are pinned. The new read-only verifier uses only the retained files and Decimal/NumPy arithmetic; it does not call the analytic reference again. The reference convention, source-freeze identity and complete original receipts remain independently reviewable.

Draft / HOLD_NO_GO / all_closed=false. This exposed diagnosis does not qualify a new prospective risk gate, a physical parameter box, arbitrary initial laws, gaps below .001, long-horizon renewal, complete old filtering/training, new-profile gradients, baselines, full cost/energy or adoption. It changes no existing #6235 source, body or exact-head CI result.
