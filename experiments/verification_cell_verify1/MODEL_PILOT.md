# VERIFY-1 actual-model ACK-only pilot

This is a controlled synthetic study of learned check scheduling. Natural-task generalization remains **HOLD** and production authority remains **NONE**. The historical phase-1 result is unchanged. No result in this document claims that model execution has completed; the native `result.json` and its complete operation journal determine that status.

## Frozen scope

The protocol fixes 12 training, 12 calibration and 12 confirmation cases: two source groups per split, each containing six fault families. Groups change synthetic target values and have distinct case identities; they reuse the same generation mechanisms. They are not independent natural tasks. Confirmation cases are paired across seven policies, giving 84 primary trajectories. Four intervention settings on the first confirmation group add 24 actual policy trajectories.

The model sees only a registered step count and up to three acknowledgement booleans. Prompts contain fixed public task semantics. Task identities, source groups, target values, fault labels, request digests, database contents, readbacks, outcomes and timings never enter prompts. The initial public input is identical across all cases. Most value faults remain indistinguishable from clean tasks under this information boundary. Lack of ensemble gain is a valid result of this design.

Training and calibration panels complete all three effects without optional interruption. Their independent labels come from an actual SQL query of stored values. A missing acknowledgement alone is **not** a value error. The forecast event is `goal_value_error_at_step3_without_optional_interruption`. Actual policy stopping changes the state trajectory, so accepted-trajectory errors use separate actual-state labels. Initial-score risk–coverage uses the paired `fixed_check` trajectory, which always completes all three effects before its check, as the full-schedule reference.

## Actual model and adapter computation

| Item | Exact scope |
| --- | --- |
| Base 1 | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), revision `c1899de289a04d12100db370d81485cdf75e47ca` |
| Base 2 | [HuggingFaceTB/SmolLM2-360M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct), revision `a10cc1512eabd3dde888204e902eca88bddb4951` |
| Runtime | Native MLX 0.31.1 and MLX-LM 0.31.2; installed loader, Qwen3 and Llama source digests are pinned in `model_backend.py` |
| Raw score | Teacher-forced conditional sequence log likelihoods for separately tokenized `YES` and `NO`, normalized over those two candidates |
| Decoder | No sampling, no generated text, no temperature adjustment; exact prompt and candidate token IDs retained |
| Readout adapters | Three actual logistic readouts fitted over Qwen's frozen final hidden state, with separate seeds and training-trajectory bootstrap samples |

The YES/NO score is not automatically a calibrated probability of error. Candidate sequences must be nonempty, at most eight tokens and prefix-free. A one-token pair needs one model forward; a multi-token pair needs two teacher-forced forwards and sums every candidate token's conditional log likelihood. No token-length normalization is applied. `mx.eval` and `mx.synchronize` occur inside the measured operation to include actual GPU evaluation rather than graph construction alone. See the primary [MLX evaluation documentation](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.eval.html) and [MLX-LM model implementation](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/models/qwen3.py); execution is bound to the reviewed installed 0.31.2 sources, since current upstream APIs may differ.

Each readout is fitted on training data only. Mean and scale come from training features, followed by division by the square root of the feature dimension. Three fixed seeds, trajectory bootstrap membership, exact training-data hash, coefficients, intercept, training objective, model identity and source groups are retained. A separate numerical-parameter hash excludes seed and provenance labels; metadata changes cannot inflate the number of different fitted heads. LLM weights remain frozen. These are trained readout adapters, **not LoRA adapters**, and their identities do not establish independent evidence. Raw pretrained likelihood policies and newly fitted readouts receive different training opportunities; the comparison does not isolate architecture as a causal factor.

## Policies and budget interpretation

| Policy | Actual inference at each assessment |
| --- | --- |
| `single` | One Qwen neutral-prompt forward request |
| `repeat_two` | Two separate Qwen neutral-prompt requests; repeated deterministic outputs are still correlated |
| `roles_two` | Qwen neutral and auditor prompts, each actually evaluated |
| `readout_heads_two` | Two actual Qwen hidden-state requests, then separate fitted readouts |
| `bases_two` | One Qwen and one Smol neutral-prompt request |
| `constant_prior` | Laplace-smoothed training-case frequency, no inference |
| `fixed_check` | Fixed step-3 optional check; same training prior for its descriptive score |

Two-voter policies average their scores. Individual error votes use the preregistered threshold 0.5. A third role and third readout are evaluated only as calibration-panel diagnostics. Every primary model vote has its own actual inference receipt; outputs are not copied to inflate voter counts. Equal two-voter opportunity does not imply equal tokens, actual forward passes, wall time or training cost. These are all retained separately. The one-voter arm intentionally leaves one opportunity unused, with the repeated-prompt arm as its compute-allocation comparison.

Initial forecasts are recorded before effects. Optional scheduling occurs after steps 2 and 3, using the forecast available at that point. The declared check cost is 0.2, error loss is 1 and optional budget is 0.4; a check is selected when score × loss is at least cost and budget is sufficient. These are declared decision-loss units, not wall seconds. The host always retains a separately reserved terminal SQLite readback before acceptance. Model reports never authorize effects or substitute for that check.

The four causal policy interventions occur at step 2 with optional budget 1: risk 0.01 versus 0.9 at cost 0.4; and cost 0.1 versus 0.8 at risk input 0.4. Raw model scores are preserved separately from overridden policy inputs. Identical public evidence, prompt and model hashes bind each paired intervention. Selected checks and resulting stops are actually executed. These are scheduler-input interventions, not neural activation interventions.

## Bounds, failures and costs

Hard count limits are 900 inference requests, 1,800 forwards and 600,000 input tokens. Prompt length is at most 512 tokens. The 1,800-second elapsed limit is cooperative and checked before inference; it is not a GPU process-kill guarantee. A three-request API compatibility check is registered, retained and charged before training. The worst-case scheduled request count is 651, before early interruptions reduce it.

The output directory is create-only. Planned trajectories are frozen before loading models. Started, failed, completed and never-executed trajectories remain distinct; a failure is not replaced by a fresh trial. Every measured operation records source/attempt context, wall time, controller CPU time, actual forward/token counters and errors. Model loading, asset hashing, feature extraction, readout fitting, checks, reconciliation and outcome labeling are included. The exact asset preparation manifest is retained, including its separately measured preparation wall time. File payload bytes are not network wire bytes. GPU energy, provider cost and complete physical cost remain unknown.

Calibration data produce Brier diagnostics, with model/policy/event/source binding, before confirmation execution. No calibration mapping is fitted, no threshold is tuned on confirmation data, and no conformal or adaptive trajectory probability certificate is produced. Missing-label bounds in reports are descriptive bounds, not confidence intervals.

## Native execution

Materialize the exact phase-1 package from the already verified formatted-source capsule. Its `contracts.py`, `runtime.py` and `metrics.py` digests must match `model_protocol.PHASE1`. Model asset preparation must first finish with `READY`; all required config/tokenizer/weights bytes are verified against the pinned manifest. An absent optional file is allowed only with an explicit `OPTIONAL_404` receipt. Unlisted visible model files are rejected.

Run the unit tests from the isolated phase-3 code root:

```sh
python3 -m unittest discover -s experiments/verification_cell_verify1 -t . -p 'test_model_*.py' -v
```

The native unit-test dependency location is the sibling `phase1-dependency/experiments/verification_cell_verify1`. The cloud tests can use the existing phase-1 source checkout. Unit-only scores are confined to tests; the runnable experiment always constructs the actual `MLXBackend`.

Run the frozen pilot with reviewed paths and the exact READY manifest digest:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /opt/homebrew/bin/python3 -m experiments.verification_cell_verify1.model_runner \
  --output /absolute/create-only/output \
  --phase1-root /absolute/phase1-dependency/experiments/verification_cell_verify1 \
  --asset-manifest /absolute/ready-assets/manifest.json \
  --asset-sha EXACT_MANIFEST_SHA256
```

`result.json` includes explicit engineering gates, complete attempt denominators, accepted actual-state errors, initial risk–coverage, measured common-error clusters, detection lead, unnecessary interruptions, paired intervention results and cost by phase/arm. Each primary policy must accept all clean and reconciled-missing-acknowledgement controls and reject all known wrong-value controls; rejecting everything cannot pass. Actual effect, label and accepted host-readback receipts must match every completed trajectory. Every vote and head feature must resolve to its own same-case/arm/step completed inference operation, and the entire expected decision and panel roster must be present exactly once. Backend smoke forwards cannot substitute for policy inference. Raw operation receipts, model inputs, heads, typed reports and SQLite databases remain available for audit. The native result must be read before changing any arm's execution status.

## Review stages

Keep source and evidence changes separate. The six code stages are protocol/accounting plus this preregistration, pinned MLX backend, real readout fitting, online policy execution, ledger-completeness audit, and summaries/CLI. Each has its associated narrow tests. Check the final formatted stage sizes against the 800-line limit before publication; repartition files if needed without changing experiment semantics. No historical qualification file is rewritten.
