# P0 QVI sibling reconciliation

Draft research only; DENY_ALL. No production activation. This branch reconciles signed QVI obstacle calculations with finite-value admission.


Exact parent: #4431 HEAD cc4e7bc205fb61e2dab14ae6e03c115cbfe70b1a; reviewed #4432. Original direct regenerative_value(Stop(1e308,1e308,.1,0,-1,0), 0) returned inf; the repaired public value API raises ArithmeticError. The qvi continuation generator remains an analytic identity, not an independently rounded residual certificate. Research-only local Python/SciPy tests: 22/22 PASS, 0 skipped; no full CI, native GPU or HX coupled-global proof. Preserve negative P1 results and all P0-P5 remaining blockers.
