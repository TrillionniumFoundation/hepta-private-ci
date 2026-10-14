# R16: two-step nonconvex positive-risk NDU, global quotient certificate

Parent R15 exact SHA 0c66cdcc94decfd57b4203d898ca6d26edf4c8a2. Preliminary numerical root scouting and pilot rational mechanism tests preceded the protocol, so this is exploratory, not blind preregistration. Existing files, gates and model selections are immutable.

Fully known finite law X in {-1,+1}, P0 uniform 0/1, epsilon1 and epsilon2 independent uniform ±1. P1=P0 xor 1_{epsilon1=+1}; P2=P1 xor 1_{epsilon2=+1}. Trainable forward H1=aX; H2=bH1+epsilon2/10. Stage cost P1/20, terminal (H2-X)^2+P2/50, discount gamma=9/10 in BOTH nested positive-risk entropic certainty-equivalent recursions, rho0=1/2 and rho1=1. Parameter penalty (a^2+b^2)/4 is added OUTSIDE entropic expectation.

The objective factors J(a,b)=C(ab)+(a^2+b^2)/4, C''(t)>=81/50. AM-GM yields J>=C(t)+|t|/2, equality at a=b=±sqrt(t) for t>0. Required certificate: fixed 10^65 outward integer intervals, 36-term exp Taylor, 12-term log/atanh, no floating proof oracle; isolate positive product minimizer, test origin strict saddle and lower bound restricted b=0 regret. Candidate was obtained by preliminary numerical scout and is not the proof.

Fixed efficacy: eight initializations [(0,0),(.1,.1),(-.1,-.1),(1,1),(-1,-1),(2,-2),(1,-1),(2,2)] x Adam, BFGS, L-BFGS-B, trust-exact, identical actual full-law objective and starting bytes. Child process CPU cap 0.75 sec, record nonpreemptible overshoot. Global quality: Euclidean distance <1e-6 to certified minimizer set and cost gap <1e-9. Seal weights before evaluating. Preserve all saddles, failures, independent leaf checks, logs, source hashes and any driver timeout. A missing driver timing cannot be reconstructed from fit timings.

Mathematical scope: finite-state, two-step positive-risk, parameter-nonconvex but separable product special case; NOT a theorem for generic deep nonlinear FBSDE, unknown world learning, arbitrary continuous laws, LLMs or viscosity PDEs. No production, main merge, CURRENT or native contract changes. Hosted CI requires separate exact-head verification.
