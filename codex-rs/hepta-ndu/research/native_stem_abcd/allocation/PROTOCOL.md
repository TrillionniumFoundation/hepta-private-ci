# R9: quadrature and exact short-circuit monitoring

Parent #1843, bce81311faf7f7295c4c41bd25eef2c8a49e66c8. This protocol is
pushed before efficacy runs. It is an exploratory follow-on informed by R8,
not external registration or a blind independent trial. Prior files stay intact.

Retain the continuous uniform state law, known affine plant, observed Markov
preferences, quartic terminal cost, entropic recursion, and inherited width-scaled
nonlinear Stem. Width64/256 means 498/1842 actual parameters, not physical-state
or language-model scaling. All methods within each width/seed start from exact
same random bytes; no warm start, pretrained encoder, or optimal-action labels.

Full factorial: 2 widths x3 seeds(11,23,47) x4 methods(Adam,L-BFGS,explicit-adjoint
HVP trust-ncg,ordinary-AD HVP trust-ncg) x2 training rules(CC5,GL5) x2 monitor
implementations(full,short-circuit) =96 fresh-process fits. Rotate order by
width/seed. GL5 and CC5 each use625 positive tensor-product points. GL5 changes
polynomial exactness at equal node count, NOT density or the true population.
This is an integration-rule intervention, not proof of smaller neural integrand
error for every parameter. Inherited learning rates and solver options stay fixed.

Primary is the paired full-versus-short-circuit monitor effect within CC5 at
width256, for every solver and seed; report joint success counts and first
observed successful check times, plus cost-only diagnostic and paid work.
Secondary is GL5-versus-CC5 at width64 within the short-circuit monitor; the
complete factorial remains visible so interactions and contrary results survive.
C-versus-Adam and ordinary-AD/L-BFGS controls are reported within every cell.
No winner, budget, seed, checkpoint or rule is selected from final evaluation.

The EXACT R8 gate remains max(J_CC5,J_CC9)<=.04850 AND
abs(J_CC9-J_CC5)<=1e-6, with12 wall seconds including setup, all optimizer work,
and monitoring. No GL5 substitution in this gate. Cadence remains .5seconds
at the latest accepted candidate, initially and terminally also checked.
Short-circuit computes CC5 first: if CC5 exceeds .04850, the original predicate
is already false so CC9 is skipped. Otherwise it computes CC9 and uses the
original predicate. At a fixed finite candidate this is logically equivalent,
not an approximate cheap predictor. Skipped CC9 is null, not a fabricated score.
The final monitor is full so each delivered candidate has both original costs.
All monitor work stays in elapsed wall/CPU. A check completing after12seconds
is NOT success; null observed time remains censored. This is first OBSERVED
detection, not exact hitting time. Different monitor runtimes change available
optimization work and poll timing, which are intended measured effects.

The two rules target the same continuous objective but finite quadrature gives
different surrogates. The legacy gate also constrains each candidate's CC5 bias:
more accurate GL5 training need not make CC5-CC9 smaller. Keep this gate even
if a genuinely low-cost candidate fails it. Do not silently replace it by
CC9/CC17 consistency, add a penalty for passing it, or count after-cap successes.
No new regularizer, graph optimization, or optimizer reset is added here.

Freeze initial/final/checkpoint tensors and FIT records before final evaluation.
Post-stop score all candidates on CC9,GL9,GL5,CC5 and four fresh scrambled
Sobol1024 sets(seeds2026101491..94), plus changed amplitude/dynamics/horizon.
Evaluate CC17 additionally on every final tensor in the independent audit.
No final evaluation resumes fitting. All root values, laws, seals, monitor
checkpoints and solver work counts are retained. Finite-rule agreement is not
a uniform integral-error certificate or global neural optimum. No learned
probability head exists; calibration is N/A, not zero.

Audit every monitor cost actually computed, every skip's mathematical condition,
timing/predicate, final chosen tensor, complete96-run census and all final
predictions. Recompute skipped CC9 only after fitting to check logical rejection;
charge this audit work separately. Independently check selected action-tree
costs in NumPy and all initial four-method groups. Keep all misses and failures.
Record CPU/wall, fit and process peak RSS, HVPs, monitor calls and skips. Imports
and serialization are in whole-child costs. Timing has no external attestation.
Full FLOPs,energy,GPU remain unknown. This is assistant-container CPU research,
not project-cloud/native deployment, a viscosity theorem, or LLM superiority.

Implementation references: NumPy leggauss documentation for positive Gaussian
rules and degree2n-1 exactness; SciPy1.17 trust-ncg documentation for HVP support.
The inherited pinned numerical environment is retained. Mathematical tests and
training-only smoke work precede the sweep and are not efficacy observations.
