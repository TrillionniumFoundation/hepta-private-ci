# Fresh confirmatory comparison, stage A

Status: implementation prepared; no formal data or model execution at source authoring.
The word confirmatory identifies the sealed protocol. The first small matrix is a
mechanism pilot and cannot establish general superiority or large-model scaling.

## Identity and admission

Use a new root-assigned namespace beginning `hcsn-confirmatory-v1/` and at least
40 characters. No prior HCSN, P1/P2/P4, TaskADV, HPCA, UCI or N256 final set is
accepted by this package. The runner accepts no external data or checkpoint.
The source base is PR6880 `602e2db1ed9cbf6d10b120973b021c2733995b10`; exact new
source/protocol bytes and transitive numerical dependencies are hashed at freeze.
Python, NumPy and Torch versions, CPU capabilities/affinity, Torch build/parallel
backend and actual threadpool identities are bound before model execution.

Commands, run from the repository root only after root allocates namespace,
seeds and resources:

```sh
python -m qualification.hcsn_confirmatory_v1.run freeze --manifest NEW_FREEZE.json --namespace ROOT_ALLOCATED_NAMESPACE --seeds ROOT_ALLOCATED_SEEDS
python -m qualification.hcsn_confirmatory_v1.run fit --manifest NEW_FREEZE.json --output NEW_ATTEMPT
python -m qualification.hcsn_confirmatory_v1.run final --manifest NEW_FREEZE.json --output NEW_ATTEMPT --selection-sha256 EXACT_SELECTION_SHA256
```

Freeze generates no task examples and invokes no model. Fit creates the attempt
exclusively and only generates train/dev. All selected candidates, failures and
NoUpdate choices are saved before final. Root must bind the emitted selection
SHA before invoking final. Final creates an exclusive consumed marker before any
holdout generation; failure cannot be silently retried or replaced. A changed
program, task, runtime or source requires a new freeze, namespace and attempt.

## Independent tasks and clocks

All four generators have no HCSN imports and produce four observed channels.
They are synthetic mechanism probes, not realistic multimodal benchmarks.

| Task | Observations and independently generated target |
|---|---|
| First passage | Brownian prefix with observed drift; exact probability of hitting zero in a new 0.5-second continuation from its last margin. Prefix crossing is not an absorbing-history event. |
| Burst | Hidden symmetric two-state rate process sampled with exact transition probability; Poisson observations conditional on each sampled edge rate. Target is expected next-second count under the continuous rate process, divided by four. Observed interval counts use held edge rates, not exact within-interval MMPP paths. |
| Asynchronous | Alternating noisy sensors with known different calibration, explicit availability masks, irregular timestamps; final clean sinusoidal state is hidden target. |
| Association | Two observed signed-key/value pairs, irrelevant distractors, final query; recover the value associated with that key. No labels come from HCSN output. |

Train, dev and final IID intervals independently lie in 40–120 ms. Final clock
intervals lie in 180–450 ms, with unchanged physical signal/rate laws and sequence
length. This is a declared duration/distribution shift, not a pure resampling
invariance test. Train/dev never use the final-clock range. Physical intervals
remain individual integer microseconds; no averaging or interpolation occurs.

## Matrix, information and parameter fairness

Initial matrix: four tasks × three independently assigned paired seeds × four
methods; 48 train, 24 dev and 48 final windows per clock regime; length 12. Freeze
permits one to five seeds for staging, and records the chosen set. CPU FP64,
single intra-op/inter-op thread and deterministic algorithms. Prepared HCSN uses
four spatial bins, two refractory phases and four content channels. These are
approximations of a finite process, not an exact moving diffusion or full HX equity.

Every method receives the same task/source description, train/dev permission,
frozen encoder, feature basis, standardized training features and editable
`readout.weight/bias` mask. The shared encoder prior in semantic_program.py
routes named observed channels into drift/boundary/content, independently of data
or feedback. It is an explicit common prior; no encoder pretraining occurred.
Last/mean flow features, mean event rate and a query–content interaction are
identical for every method. This feature engineering is not credited as learning.

- Direct: ridge solve on fixed features, bias unpenalized; one candidate.
- Local BP: 64 full-batch Adam steps from zero, learning rate .02.
- Semantic program: assistant-authored named-feature weight assignment, one shot.
- Program then BP: the same program followed by the same 64 BP steps.
- Every candidate is compared once with the zero NoUpdate readout on dev.

Ridge lambda .001 defines the same standardized readout objective for direct and
BP. No hyperparameter search or code revision follows dev feedback in this stage.
The semantic program has no loss/residual/evaluation callback and is not coordinate
descent. Its coefficients are unvalidated hypotheses and may lose to NoUpdate.
The executable source is copied into the attempt. Assistant tokens, API bill and
design time are unknown and must never be reported as zero. This is a small actual
assistant-written program, not a reproduction of MIT discovery or pretrained
network reverse engineering.

## Costs, statistics and claim limits

One hash-chained CostLedger reserves work before it runs and retains failures.
The shared total ceiling is 180 wall seconds across fit/final, plus explicit work
caps in the freeze. Checks occur at operation boundaries, not a hard OS deadline;
root must provide host admission/watchdog if a hard cap is required. The few-minute
target is a budget, not an observed runtime claim. Process/framework setup,
feature extraction, solves, optimizer work, dev/final and serialization contribute
to wall cost. The cost sidecar follows primary receipt serialization/checkpoint;
sidecar/stdout/exit costs require root's external process meter. Sharing extracted
features saves campaign work; each independently
deployed method must also be charged its own feature extraction. Per-arm reported
standalone time is explicitly a lower bound, not a complete training-speed ratio.
The shared setup timer includes model construction, new data, full features and
normalization; each arm's standalone lower bound includes that complete setup.

Primary metric: raw prediction MSE per task and clock regime. First-passage targets
are probabilities, so this is probability-regression error, not observed-event
calibration. Retain every prediction, target, ID and squared error. Report paired
seed-level differences and all failures; do not treat windows or timesteps as
independent training replicates. Three-seed pilot: descriptive values and ranges
only, no significance claim. A later adequately powered, newly frozen study may
use seed-cluster resampling and Holm correction across predeclared contrasts.
Do not pool raw MSE scales across the four tasks or select a winner on final.

Stage A tests readout adaptation only. Stage B must add a separately frozen common
mask for dynamics and communication (drive, boundary, writer, readout), program/BP/
hybrid experiments, and independently measured recurrent state. A conditional
ridge readout is not a closed-form optimizer over those nonlinear parameters.
Architecture comparisons belong to another coherent stage: real GRU; official
ncps CfC or explicitly unavailable; named diagonal linear continuous-time SSM
without calling it Mamba; explicitly specified LIF surrogate network; causal
Transformer with real attention. Match input/clock access, parameter ranges,
training/selection budgets, all setup costs and capacity curves. Missing baselines
remain unrun; none can inherit an HCSN or generic tanh result.

