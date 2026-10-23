# Controlled multimodal generation, v2

This is a source-frozen extension of the learned four-modality pilot. The v1/v1.1 source, protocol and negative confirmation remain intact. A passing implementation gate is distinct from an empirical benefit, dedicated-host execution, native runtime integration or foundation-model capability.

## Implemented control problem

The public state consists of acquired encoder reports, remaining budget and a bounded observed-disagreement preference state. The finite controller chooses another observation or commits to a supported semantic portfolio and zero to three real residual refinement steps. Initialization, each refinement and one immutable all-modality emission are explicit operations. All four outputs are mandatory. Generation depth is selected at commitment; newly observed latent failures do not yet trigger replanning within refinement.

The terminal utility is the conditional entropic certainty equivalent of negative external output loss, minus priced generation work. Acquisition recursively aggregates the contingent continuation utilities at the current preference, minus its own price. Preference changes only from public acquired reports. `generation_control.py` solves this finite recursion; a separate bottom-up implementation verifies every reachable state. Depth/action switches use a `1e-12` improvement tolerance. This finite result is not a general stochastic FBSDE solution.

Each acquisition costs the original modality proxy plus one controller unit. Initializing, refining and emitting each cost one model-work proxy plus one controller unit, so a depth-d generation costs `4 + 2*d`. Budgets 8/12/16 begin after the initial text event. Actual initial-text encoder MACs are nevertheless counted. These proxy units are not hardware FLOPs. Every output is produced by actual learned weights; canonical targets and hidden truth enter training/evaluation, not online selection or emission.

## Training and fair comparison

The original 400-step supervised model is followed by 100 steps of supervision at all four generation depths. Both final models start from that same checkpoint. They then receive 40 AdamW updates of the initial latent layer, shared refinement and all four decoders; raw encoders and the calibration law remain fixed.

The matched supervised branch minimizes normalized reconstruction under each portfolio, plus a vertex anchor. The NDU branch reselects a finite recursive policy and differentiates its utility through the same external terminal-loss tensor used for selection. Both branches perform the same dense Linear forward work and number of optimizer updates. NDU additionally requires policy compilation and recursive differentiation, which are reported separately; this is not a claim of equal lifecycle compute.

The external loss retains v1.1 semantics: each modality's normalized reconstruction error is clipped at two before averaging, then cross-modal nearest-prototype disagreement is added with weight 0.25. Its derivative is piecewise: contradiction is locally constant away from argmin ties, while clamping and policy changes are nonsmooth. First/last-step receipts separate the NDU-utility gradient from anchor gradients by parameter group and report selected generation depths. Parameter movement alone is not evidence that NDU supplied a refinement gradient.

The pre-result protocol amendment adds the matched supervised updates. It changes neither the primary contrast's threshold nor the test outcomes: the amendment was committed before development training and before any new heldout generation.

## Reproduce

Use Python 3.12, NumPy 1.26.4 and PyTorch 2.5.1 CPU in an isolated environment. No pretrained-model download or external model API is required.

```bash
python -m unittest discover -s experiments/multimodal_output_portfolio -p 'test_*.py' -v
PYTHONPATH=experiments/multimodal_output_portfolio python -m unittest discover -s experiments/multimodal_output_portfolio/v2 -p 'test_*.py' -v
python experiments/multimodal_output_portfolio/v2/run.py --output /tmp/hepta-v2-development --tier local-cpu --smoke
python experiments/multimodal_output_portfolio/v2/run.py --output /tmp/hepta-v2-confirmation --tier local-cpu
```

Output directories must not already exist. The full run requires every source dependency to match a committed checkout. Smoke uses a separate development namespace and seed and cannot pass the confirmation gate. Before fresh heldout worlds are generated, the model, calibration, finite policies and validation-selected static alternatives are frozen. Inference encodes only modalities actually acquired; policy caches must not grow during heldout execution.

Each run preserves checkpoint files, calibration and candidate tables, independently audited policy results, per-world actual generation traces, output hashes, separate offline/online costs, training gradient evidence, paired bootstrap contrasts, source hashes, failure receipts if applicable and an artifact manifest. The sole primary test is IID budget-12 joint NDU versus matched supervised static; secondary intervals are descriptive and unadjusted.

## External execution

`run_cloud.sh` and the branch-specific workflow consume an explicit `CLOUD_RUN_REQUEST.json` pinning an implementation commit and protocol hash. Hosted CPU unit/smoke verification and dedicated full execution are independent jobs. Dedicated execution selects group `trillionnium-android-gpu` and requires runner `desktop`. Its completion additionally needs external Actions evidence of a nonzero assigned runner ID and executed steps. Queueing a request or asserting environment variables does not close this gate.

## Remaining scope

This stage does not establish native HEPTA runtime integration, latent-dependent control within refinement, learned identifiable preference dynamics, a general stochastic FBSDE solver, natural-data all-modal foundation-model validation or a universal/global model optimum. The old v1.1 failed primary effect remains a valid negative result. A new result must meet the registered gates independently; failed outcomes and attempts are retained.
