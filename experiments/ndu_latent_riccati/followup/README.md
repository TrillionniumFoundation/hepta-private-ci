# NDU–Merton generative portfolio: isolated P0/P1/P2 shadow follow-up

**Status: DRAFT / RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**

This *additive* follow-up is stacked on [the frozen continuous-latent research PR #3055](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3055). It does not modify that pilot's preregistered `protocol.json`, `SOURCE_FREEZE.json`, training, decoder, heldout split, analysis, or existing cloud-run request. The previous pilot's observed heldout outcomes cannot be reinterpreted as confirmatory evidence for this experiment. All future experiments require a separately frozen protocol and untouched samples.

## What this code actually does

- `portfolio.py` supplies a **small reference optimizer**, computing an exhaustive optimum on a bounded **finite fractional-allocation grid** for at most four *same-protocol, same-domain* Cell candidates. This is neither a continuous global optimizer nor a Merton/FBSDE solution.
- A conditional utility estimate and **paired, external calibration** losses determine the shadow objective; risk includes the NoChange baseline, joint scenario variance, CVaR90, variable resource cost, and **once-per-active-Cell** cost. A candidate with negative standalone utility may have positive joint hedge value.
- For equally weighted scenario samples, CVaR90 uses exactly the worst 10% of empirical probability mass, including a fractional boundary observation when 0.1×N is not an integer. Averaging the worst ceil(0.1×N) observations can dangerously **underestimate** a hard tail-risk limit; this correction changes only the P0/P1/P2 shadow reference code, not #3055 or the preregistered #3039 experiment.
- Inputs missing a calibration/objective identifier, paired scenarios, unique payload identity, compatible protocol/domain, finite utility, or admissible budgets fail closed.
- Receipts include an immutable-input replay digest and **DENY_ALL**. Replaying a digest is not source authentication, external future-window attestation, a signer, or final-use authorization.
- `continuous_direction_step` implements differentiable Euler combination of the **already registered** base flow plus bounded compatible Cell directions. Weight zero gives exact base-flow parity; numerical gradients can reach Cell heads. It does not train heads or access ground-truth facts.
- `supervised_cell_update` trains **only** zero-initialized low-rank Cell weights against a frozen base flow/decoder and an explicitly external raw-decoder training loss. It rejects optimizers containing any other parameters. This is P0 supervised plumbing, **not** NDU-aware joint training.
- `masked_logit_step` is a **P2 contract primitive**: same-vocabulary logit deltas are combinable, while the subsequent unmask action is atomic and only chooses currently masked positions. It is **not** a trained Diffusion LLM or proof of text-generation quality.
- `test_portfolio.py` contains 16 deterministic tests, including 30 randomized profiles checked against an independent scalar enumeration.

## Mathematical non-claims that must survive code review

1. **Mixing losses is not mixing outputs.** Weighted standalone semantic losses are only a calibration proxy. For a nonlinear decoder, `L(decode(z + sum(w_i*delta_i)))` is generally not `sum(w_i*L(decode(z+delta_i)))`. A selected portfolio must be independently re-evaluated on *actual raw decoded* text/audio/image/video.
2. CVaR/variance reported here concern **paired calibration scenarios**, not an identified conditional stochastic process, causal future returns, heldout risk, or actual production loss.
3. The bounded grid is an exact finite enumeration only for the values it is supplied. No smoothness, dynamic programming optimality, Pareto globality, QP/MPC globality, or learned NDU efficacy is claimed.
4. The `objective_digest` and `calibration_digest` are caller-supplied *identifiers*; this library does not authenticate them. Selection is informational and may not influence live tools, irreversible streams, deployed artifacts, or production model promotion.
5. `masked_logits_v1` and `latent_velocity_v1` candidates may **never** share a continuous portfolio. Actions and entire discrete unmask plans still need separate atomic selection.
6. A shared error across all modalities, an unknown future shift, or an incorrectly labeled calibration window cannot be repaired by output-risk covariance algebra.

## Running the isolated checks

With Python 3.11, NumPy and PyTorch (CPU is sufficient):

```bash
cd experiments/ndu_latent_riccati/followup
python -m unittest -v test_portfolio.py
```

Locally the exact source blobs were tested with Python 3, NumPy 2.3.5 and CPU PyTorch 2.10.0: **16 tests passed**, including randomized exhaustive reference checks. These are *local numerical regression tests*, not a qualifying native Rust CI receipt, dedicated-cloud run, or a scientific improvement result. The exact two committed Python blob SHAs were compared with the local `git hash-object` values to protect against source drift.

## Strict P0–P4 dependency/gate matrix

| Stage | Existing/follow-up work | Required to claim closure | Current |
| --- | --- | --- | --- |
| P0 real continuous latent | #3055 learned 4-input codec, shared encoder, continuous flow, Riccati/QP mathematical audits; here: direction step, exact zero-delta parity, gradient unit test | Named frozen encoder/flow + **trained** Cell deltas + actual decoded real-output quality + nonlinearity/solver errors + verified dedicated run | **OPEN** |
| P1 NDU efficiency | Here: finite grid oracle, fixed activation charges, baseline variance, covariance hedge, CVaR cap | Freeze same-information and same-actuator static/MoE/risk-neutral/fixed-risk/free/NDU comparison; equal measured total cost; preregistered heldout CVaR, ambiguity, correctness and diversity superiority | **OPEN** |
| P2 masked diffusion LLM | Here: aligned logit-delta and atomic unmask mechanism | Real fixed dLLM checkpoint/tokenizer, trained Cell heads, matched ordinary decoding, token-level/mask/stop tests, no changed backbone/reward/data/budget | **OPEN** |
| P3 natural multimodal | #3055 still synthetic numeric text, tones, 16×16 imagery and video; no natural speech | Licensed natural paired text/image/speech data, later natural video; cross-modal semantic and temporal synchronization; irreversibility and streaming gates; raw outputs and independent readback | **OPEN** |
| P4 joint training | #3055 already has a narrower frozen-codec 2×2 flow/Riccati training/inference design | Separately frozen full factorial including joint training with the real differentiable optimizer; no hidden future labels, gradient/critic calibration, equal-update and measured-time fairness, independent unseen worlds; next-generation authorized model lifecycle | **OPEN** |

### Next research experiment (new registration required)

**Keep #3055 frozen.** Train Cell direction heads as distinct compatible latent adapters from the **same** encoder features, without adding extra observations to the NDU arm; record physical call/encoder/decoder counts. In one release-blocking follow-up:

1. First pass known LQ oracle, nonlinear local-Riccati error, zero-delta parity and bounded risk-budget tests.
2. Train fixed continuous-latent Cell heads once. Keep backbone and external objective immutable across controls.
3. Collect scenario losses on **training/calibration only**; fit risk/utility critics with time/episode-grouped folds, never inspect hidden truth during inference.
4. Independently roll out **selected combinations**, decode raw outputs, and compute semantic loss/CVaR/ambiguity/conditional lawful diversity; do not promote a mixed-standalone-loss proxy as a raw-output result.
5. Compare validation-selected static, MoE gate, risk-neutral MPC, fixed-risk MPC, free same-actuator controller, complete NDU and no-change, with a complete inference **wall/process/accelerator + amortized training** cost ledger.
6. Freeze code, model hashes, baseline choice, source seed namespace, evaluation dates, effect threshold and failure policy **before** generating fresh heldout worlds; retain negative runs and quality failures.
7. Only after independent, repeated and cost-matched gain, introduce P2 natural text and later P3/P4. An unsatisfied scientific hypothesis is a negative result, **not** a blocker to be tuned away.

### Known separate blockers

- #3055's dedicated runner request ([Actions run 39609872030](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39609872030)) has no completed execution receipt; an accepted/queued job is not a dedicated-cloud pass.
- #3055's [blocking-ci 39612160175](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39612160175) failed, including cargo-deny dependency advisories, macOS Bazel dragonbox fetch HTTP 503 and Windows sandbox ACL tests. Security advisories are not waived by the research shadow tests.
- Production NDU covariance/conditional support, independent future-window observer, model CAS/CNS/Fence, Final-use, named-host 64–4096 Cell resource receipts and native Rust compatibility remain independent gates.

This follow-up has no effect authority, no result-based test rewriting, no inference-time hidden label access and no permission to merge into production solely because 16 small unit tests pass.
