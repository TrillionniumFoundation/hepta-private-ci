# Independent design review: continuous latent NDU experiment

This review specifies interpretation boundaries and checks before heldout
execution. It does not register favorable outcomes or replace the experiment's
versioned protocol. The previous finite-portfolio v1.1 result remains negative
for its registered primary efficacy claim.

## Three evidential levels

1. **Solver and structural mechanism.** A known joint linear state `(z, p)`
   with zero intrinsic preference diffusion and genuine cross-coupling permits
   exact continuous-time Riccati verification. Independent condensed quadratic
   optimization or an independently formulated boundary-value solution must
   agree as the time grid is refined. Full-costate versus `Z`-only, active versus
   fixed valuation, cross-block removal, and low-rank approximation are
   structural diagnostics. They do not establish natural-language quality.
2. **Learned continuous generation.** A trained encoder, continuous multistep
   generator, and decoder must produce outputs. Input modalities must carry
   complementary information; generated outputs must have independently
   checkable facts and more than one legal style. Any synthetic task remains a
   synthetic mechanism experiment, even when its interfaces are text, audio,
   image, and video.
3. **Incremental NDU value.** The relevant comparator has the same observations,
   actuators, training data, and inference cost opportunity. A controller with
   extra preference actuators trivially has a larger feasible set than fixed
   preference. The latter is an ablation, not the strongest efficacy baseline.

## Data and semantic evaluation

- Use continuous task attributes and heldout attribute combinations, not only
  mixtures of a few prototypes. Each modality should expose an explicitly
  declared subset of facts, with nuisance variation and independent heldout
  corruption. Modality complementarity should be measured by omission tests.
- Generate multiple lawful output styles independently of factual content.
  A distributional style metric must distinguish legitimate variability from
  factual uncertainty. Report conditional variance or mode coverage against the
  declared target distribution, alongside validity. More noise alone is not
  better diversity.
- Define truth and external losses once on a fixed scale. An internal
  preference state cannot modify the evaluation weights. Report factual error,
  worst-tail factual error, cross-modal consistency, and a strict joint
  correct-and-resolved rate. A coherent but uniformly wrong output must fail.
- Retain raw decoder outputs for a reproducible sample and prediction arrays
  for every evaluation case. A latent metric alone is not multimodal output
  evidence. Keep quality, control effort, and measured cost separate so control
  penalties cannot hide semantic deterioration.
- Inputs provided to policies must exclude truth, corruption identities,
  unrevealed future observations, and target encodings. A training target can
  supervise a terminal critic, but inference must use only the critic's
  context-conditioned estimate. Test this data boundary in code.

## Controls and factorial design

Freeze the codec and initial base model per training seed. Include an ordinary
continuous flow/diffusion sampler, terminal guidance, a free neural controller
with the same joint `(a, nu)` control channels, fixed-valuation LQR/MPC, and the
full NDU controller. Give all adaptive methods comparable validation and
training opportunity. Report parameter counts and compute even where exact
equality is impossible.

The two-by-two intervention is base versus NDU-aware training crossed with no
NDU versus NDU inference. NDU-aware training must backpropagate through the
actual solver and rollout, not merely train a separate risk-weight heuristic.
All cells require the same external evaluator. Initialization, data draws,
optimizer budgets, and stopping rules must be explicit; otherwise the training
effect is confounded with additional optimization.

Active valuation requires an actual control `nu`, a preference state affected
by that control, a nonzero adjustment cost, and a subsequent effect on the
generation dynamics or objective. A fixed formula updating a risk coefficient
is insufficient. A generic latent integrator should be described as the
operationalized valuation state, not assumed to prove psychological preference.

## Statistics and primary claim

- Freeze the protocol, source manifest, heldout seed namespace, endpoint,
  practical-effect margin, and baseline-selection rule before heldout access.
- Prefer at least five independently trained seeds when feasible. Use paired
  worlds and sampling noise across arms. A hierarchical seed/world bootstrap is
  descriptive with few seeds; include per-seed outcomes and do not imply large
  model-training-population certainty from many worlds and few models.
- Select the strongest eligible baseline on validation only. If primary
  superiority is semantic-tail reduction, require preservation of mean quality,
  correct-and-resolved output, and lawful diversity. Specify the permitted
  measured cost budget before test execution.
- A training interaction, dense/low-rank tradeoff, or distribution-shift benefit
  remains secondary unless registered otherwise. Report all arms and conditions
  even when the full NDU method loses.
- Do not tune against the same heldout sample, pool a new run with the old
  negative pilot, or promote a favorable secondary endpoint after inspection.

## Cost and mathematical boundaries

Report complete forward wall time with the runtime, device, thread count, batch
size, warmup, and synchronization policy. Also report each amortized/offline
cost separately: encoder, base dynamics, critic, derivatives, Riccati solve,
matrix factorizations, feedback rollout, decoder, training, and validation.
Linear-layer MACs are not total cost. Model-quality versus latency and explicit
control effort are distinct empirical frontiers.

State-independent additive noise in risk-neutral fully observed LQ must leave
the feedback gain unchanged. Sigma sensitivity in that setting would indicate
a bug. A rank-deficient preference diffusion means `Z` cannot recover the full
costate; that comparison intentionally removes information and is not a fair
competitive baseline. Projection, clipping, state-dependent coefficients,
nonlinear terminal decoders, and low-rank Riccati truncation require an
approximation label unless separately proved. Gradients must agree with an
independent finite-difference calculation on a smooth case.

## Closure vocabulary

Implementation defects, evidence-integrity defects, and verified execution
receipts are engineering blockers. Registered scientific hypotheses can fail
after a correct experiment; a failed hypothesis is a result, not permission to
retune until success. Native Hepta integration, natural multimodal generation,
and scalable foundation-model efficacy remain separate scope claims unless
directly tested. An unassigned Actions job is not a dedicated-cloud execution
receipt, and locally passing checks cannot close that receipt requirement.
