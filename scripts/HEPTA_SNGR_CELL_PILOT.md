# SNG-R shared-stem DecisionCell / NDU shadow: first neural end-to-end pilot

**Research-only, opt-in, synthetic data; no production selection, no effect authority.**

This is the next evidence layer after [`HEPTA_SNGR_SHADOW.md`](HEPTA_SNGR_SHADOW.md). It is an actual local PyTorch neural forward/training/evaluation implementation, **not** a Laya-421M run, learned continuous-time FBSDE, proof of global well-posedness, multimodal text generation, or verified performance on real Hepta memory/retrieval episodes. It does not install/activate a new runtime, artifact, external objective or service. The selected objective and production NDU remain untouched.

## Explicitly scoped experiment

- **Task:** an independently hidden binary world label; the agent can either guess or pay to obtain an additional noisy +/- observation. The simulator supplies conditional reliability in `[0.60,0.85]`, per-probe cost in `[0.02,0.14]`, and at most five observations. All policies receive **identical held-out worlds and potential evidence streams**. Never pass the hidden label or future evidence into a live model input.
- **Physical Stem:** one randomly initialized, 1-layer, 4-attention-head, 24-wide PyTorch Transformer encoder over typed observation tokens, shared among all Cells. This is **not a downloaded or pretrained model**. Its 5,112 parameters are trained jointly with the heads, frozen with no trainable parameters and eval-mode guarded in evaluation, reused by each Cell operation and never copied per logical Cell.
- **Logical Cell Heads:** three distinct small heads for posterior probability, learned continuation utility and discrete conditional utility-noise sensitivity `Z`. They have 1,395 parameters together; the whole network has 6,507. Cached representations and scopes are per-episode, with exact state keys, explicit model identity and a maximum of 63 physical Encoder invocations per episode.
- **Forward/Backward graph:** from the observed state generate two potential next-states `(+1, -1)`, assign normalized conditional chances using the predicted posterior, back up continuation utility minus actual observation costs, and compare with stopping. A learned continuation head amortizes the remainder of the horizon; a depth-matched baseline terminates with the immediate posterior stop value. No external effects or tools are dispatched by this shadow.
- **Stochastic sensitivity:** for the centered discrete martingale increment `m in {-1,+1}` with `P(m=+1)=q`, `Sigma=4q(1-q)`, `B=2q(1-q)(U_+-U_-)`, so `Z Sigma=B` and `Z=(U_+-U_-)/2`. The same calculation rejects degenerate/nonfinite q. This is a **discrete-time martingale regression**, not a Brownian FBSDE solver, nor a parameter derivative. The separate `Z` neural head learns analytically supervised *active selected-continuation* sensitivity. Its disagreement with the graph-implied `Z` is diagnostic; it is **not** a global error certificate.
- **Training:** supervised against synthetic Bayes-DP labels for the same declared stochastic control problem, with independent randomized continuous reliability/cost per row. Full paths are split by independent random episodes/seeds, and the held-out hidden labels are excluded from all inference inputs. No real-world task labels, RL improvement or causal learning claim.

## Equal-budget controls and limitations

The experiment evaluates `stop_now`, `fixed_3`, horizon-truncated `bellman_h2` (immediate leaf), `ndu_h2` (learned continuation), and `value_bellman_h2` (same learned continuation and identical additive Bellman semantics). An additional `ndu_adaptive_h2` / `value_bellman_adaptive_h2` pair uses the **same** learned Head to suppress deeper search when estimated continuation advantage is at most 0.009 utility units; this is a *fixed heuristic shadow-gating threshold*, not a proven optimal NDU stopping rule. Two analytical controls are `oracle_full` (knows the simulator law, not the hidden label) and `oracle_policy_neural_answer` (oracle stopping, learned final label head). The same `max_calls` cap applies; **actual calls still differ substantially** and are reported separately. An optional synthetic charge of `0.001` utility unit per physical Encoder invocation is explicit, not an empirical power or cloud-price measurement.

A risk-neutral additive utility BSDE backup is compatible with the Bellman recursion. Consequently, `ndu_h2 == value_bellman_h2` is a required parity invariant, not evidence that NDU magically outperforms the same Bellman policy. `bellman_h2` differs because it does not use the learned continuation at the search frontier; any gain there is a **learned-value/continuation advantage**, not isolation of FBSDE-specific causality.

The analytical oracle is not a compute-matched deployable model. Independent world samples are held out, but examples belong to **the same synthetic task family**; this does not establish generalization to new domains, real retrieval, prompt injection, longer horizons, multimodal I/O or real Laya checkpoint compatibility.

## Exact local commands

From repository root, with optional CPU PyTorch installed (tested locally with Python 3.13 and PyTorch 2.10.0+cpu):

```bash
python3 -m unittest discover -v -s scripts -p 'test_hepta_sngr*.py'
python3 scripts/hepta_sngr_cell_pilot.py --demo --seed 17 --steps 450 --episodes 256
```

PyTorch is **not a Cargo or repository dependency**, and the module imports it only in explicitly requested training/execution functions. With no PyTorch installed, the algebra, input-security and cost guard tests continue to run; network-training-specific tests are skipped, not counterfeited.

## Recorded local results (synthetic 2026-10-17 pilot)

For seed 17 / 4,096 independently generated training rows / 450 optimizer steps / 512 held-out synthetic rows / 256 paired evaluation worlds:

| Policy | Task accuracy | Utility after evidence + 0.001/Encoder charge | Mean real Encoder calls | Mean evidence probes |
|---|---:|---:|---:|---:|
| `stop_now` | 0.4766 | 0.4756 | 1.00 | 0.00 |
| `fixed_3` | 0.8008 | 0.5613 | 1.00 | 3.00 |
| `bellman_h2` | 0.8086 | 0.6906 | 13.03 | 1.70 |
| `ndu_h2` | 0.8242 | 0.6958 | 13.62 | 1.88 |
| `ndu_adaptive_h2` | 0.8086 | 0.6917 | 11.16 | 1.65 |
| `value_bellman_adaptive_h2` | 0.8086 | 0.6917 | 11.16 | 1.65 |
| `value_bellman_h2` | 0.8242 | 0.6958 | 13.62 | 1.88 |
| `oracle_policy_neural_answer` | 0.8086 | 0.7029 | 1.00 | 1.69 |
| `oracle_full` | 0.8086 | 0.7039 | 0.00 | 1.69 |

- Held-out posterior MAE **0.0421**, continuation utility MAE **0.0217**, conditional `Z` MAE **0.0138**, all compared against the **synthetic Bayes teacher**, not real-world labels.
- Paired 1,000-resample bootstrap percentile interval for `ndu_h2 - fixed_3` charged utility: **[0.091, 0.177]**. For `ndu_h2 - bellman_h2`: **[-0.007, 0.020]**, crosses zero; no superiority claim. `ndu_h2 - value_bellman_h2` is exactly zero by construction. `ndu_adaptive_h2` also matches `value_bellman_adaptive_h2` exactly, and uses approximately **18% fewer** actual Encoder calls than the ungated `ndu_h2` (11.16 versus 13.62), with paired charged-reward difference **[-0.026, 0.016]**; this interval does not establish non-inferiority or a consistent improvement.
- The encoder/head weights are a 6,507-parameter model, not an ablated 421M checkpoint. Hypothetically assigning one 465-parameter head to each of 1,000 logical Cells yields **1,880,448 bytes** FP32 for one 5,112-parameter Stem plus the heads, versus **22,308,000 bytes** for 1,000 copies of a 5,112-param Stem plus individual 465-param heads. This is only a **model-weight accounting projection**, not measured GPU residency, throughput, latency, or a 10T-model equivalence claim.
- `model_snapshot_sha256` on seed 17: `2701e71b622f54cca8cd4089e892fa1aaad47c7ec8585640eda544f4b5c92186`. `synthetic_training_dataset_sha256`: `702f551c79be922ed66eb77548dcced7d5ce004acec5f885acebda854b32cd0d`.
- For seed 23, charged reward `ndu_h2=0.6192`, `bellman_h2=0.6242`, `fixed_3=0.5574`; seed 41: `ndu_h2=0.6247`, `bellman_h2=0.6215`, `fixed_3=0.5373`. **NDU vs depth-2 Bellman is not consistently better across seeds**.
- On the seed 17 named CPU run, p95 episode wall time was approximately **6.5 ms** for `ndu_h2`, versus **0.45 ms** for `fixed_3`; scheduling, CPU frequency, and PyTorch version affect these values. This pilot does not establish production p95.

The experiment explicitly does not report posterior accuracy or inference latency as Hepta production results; those claims require a qualified named host, actual pretrained/finetuned Laya weights, real immutable task/outcome episodes, temporal holdout, cost/energy measurement, independent causal evaluation and artifact admission.

## Next gates

1. Complete PR CI including Rust cargo check/fmt/clippy on exact submitted source SHA; existing blocking CI is not bypassed.
2. Obtain a legally usable, pinned and real pretrained Encoder checkpoint in an authorized named host. Bind tokenizer/preprocessor and model digests to each trained Head and assert wrong-base rejection. No fallback to pretending the random 6.5K-parameter model is Laya.
3. Bind independently supported Hepta read-only retrieval episodes (complete candidate sets, reference answers/evidence, independent outcome observers), and compare System1/Cell-only/Cell+Bellman/Cell+NDU on matched training information and total lifecycle costs.
4. Only after real-task value improvement and OOD calibration hold, qualify bounded trained continuous-time `FBSDE` coefficients, interface residual/error, risk-sensitive nonlinear NDU and multi-modal Cells; each is a separate research claim.
