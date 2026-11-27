# Posthoc ordinary-baseline audit of native003

## Outcome and status

A validation-selected ordinary fixed-prefix schedule exceeds the registered value head on the same 128 fresh MNIST images. The schedule's equal-price macro utility is **0.173333**, compared with **0.127708** for the value head: value minus ordinary is **−0.045625**. The value head has no strict win in any of the 36 complete CPU-cost scenarios checked here.

This is a **posthoc adversarial baseline audit**, requested after native003 fresh results exposed a collapsed ordinary MLP. It is not a replacement primary experiment or an independently preregistered confirmation. The fixed-prefix choices use original validation outcomes only, and are locked before additional fixed-1 inference. The decision to test this baseline family nevertheless follows knowledge of the primary fresh results. Its role is to challenge claims of superiority over ordinary controllers.

The original native003 summary remains byte-identical, SHA-256 `d77d73c891b4a5d0ab1b35008bee61a3d919693dee360bbb0618068f56c918ed`. Its source, protocol, selected heads, and data are unchanged. This audit's [SUMMARY.json](SUMMARY.json), [SELECTION.json](SELECTION.json), [SELECTION_LOCK.json](SELECTION_LOCK.json), [EXECUTION.json](EXECUTION.json), and [REVIEW.json](REVIEW.json) retain separate provenance.

## Selection and actual computation

Candidate prefixes are `{1, 8, 16, 24, 32}`. For each public read price, choose the prefix maximizing mean `correct - price * prefix` on the saved first 128 original validation traces; resolve ties in favor of the earlier prefix. No fresh image or fresh label enters this selection. The selected schedule is:

| Read price | Selected prefix | Validation utility | Fresh accuracy | Fresh utility |
|---|---:|---:|---:|---:|
| 0.005 | 32 | 0.386875 | 54.6875% | 0.386875 |
| 0.02 | 1 | 0.089375 | 10.1563% | 0.081563 |
| 0.05 | 1 | 0.059375 | 10.1563% | 0.051563 |

At price 0.005 this reuses native003's actually executed read-all reference. It does not perform another 32-prefix evaluation and does not pretend that reused computation is a new execution.

For prefix 1 the separate worker loads the same fixed backbone and actually calls `model.step` once for each of the 128 images. It writes a record for each image containing its prediction, logits digest, read count, model CPU time, and zero head/native calls. These new predictions agree with the existing STOP1 MLP predictions in all 384 image-price comparisons. The new fixed-1 computation is performed once and reused across prices, since the fixed backbone and fixed prefix have no price-dependent inference path. The ordinary baseline requires no learned head or native process.

The saved validation trace SHA-256 is `812caa2895466d0c134c74042b780c1e6ace28f79ff28bd52ea294522651edf4`. Before the worker starts, the lock pins this audit's selection and code, original native003 freeze, and original summary. The new worker verifies those hashes and the original 54-file extension freeze before inference. The read-only audit independently reproduces all three selected prefixes directly from the saved validation correctness arrays.

## Comparison with the frozen value head

| Read price | Ordinary reads | Value-head reads | Ordinary utility | Value-head utility | Value minus ordinary |
|---|---:|---:|---:|---:|---:|
| 0.005 | 32 | 32 | 0.386875 | 0.386875 | 0 |
| 0.02 | 1 | 16.4375 | 0.081563 | −0.055313 | −0.136875 |
| 0.05 | 1 | 1 | 0.051563 | 0.051563 | 0 |
| Equal-price macro | — | — | **0.173333** | **0.127708** | **−0.045625** |

At the low and high prices, the value head gives the same read utility as this simple schedule while adding controller/native overhead. At the middle price it uses more observations and is more accurate, but the additional accuracy does not pay for its 15.4375 extra mean reads under the declared utility. This is not a population or statistical-significance claim: the three prices are correlated measurements on the same 128 images, with one fixed backbone and one trained-head seed.

## Full costs and explicit reuse

The actual fixed-1 inference loop consumes 0.408464 parent CPU seconds, or **0.003191125 seconds per episode**, with 128 real model calls. Its full child process consumes **2.412390 CPU seconds**, including Python/Torch imports, source/checkpoint verification, model loading, inference, and worker report writes; wall time is 2.738313 seconds and peak RSS is 214,504 KiB. Parent selection/accounting consumes 0.126305 CPU seconds through the accounting cutoff. Therefore the **new physical audit CPU is 2.538695 seconds**. No old trace/reference cost is counted as new physical execution.

For deployment comparisons, the ordinary schedule is conservatively charged the shared train/validation trace and training-worker setup/overhead cost, even though selection requires only validation traces. This is 2.790961 seconds, measured as the complete training worker less the three families' measured searches; it includes shared imports, setup, and reporting rather than only the separately timed trace generation. Its shared deployment setup charge includes original native003 shared setup plus new audit setup, totaling 4.786233 seconds. It also pays the same 46.474767-second prior backbone training charge. It pays no other family's learned-head search cost. These charges are amortized over each alternative deployment's `N`, not added across price alternatives.

The ordinary CPU charge per deployment episode is:

`actual reference inference CPU/episode + (46.474767 + 2.790960977 + 4.786232702) / N`.

The low-price inference charge is the measured original read-all cost, 0.105187222 seconds per episode. The two higher prices use the new actual fixed-1 cost, 0.003191125 seconds per episode. Native003's value-head cost rows remain unchanged and include its own full search, trace/setup, native inference, and recovery charges. Comparisons use the same original grid: `N ∈ {1000, 10000, 100000}` and `lambda_CPU ∈ {0, .0001, .001, .01}`. The value head has **0 strict wins in 36 per-price scenarios** even under the ordinary schedule's conservative extra setup charge.

At `N=1000` and `lambda_CPU=.01`, the equal-price macro difference is approximately −0.046134 utility units; with zero CPU price it is −0.045625. These are accounting scenarios with stated unit conversion, not measured Joules or deployment forecasts. The final audit-orchestrator serialization occurs after its stated self-CPU cutoff. No native descendant is present in this audit worker, and prior native003 descendant CPU is not counted a second time.

## What this changes

The registered native003 results still demonstrate trainable, causal, price-responsive native execution with real early stopping. The registered comparison's positive macro difference against the collapsed MLP cannot support a claim of advantage over strong ordinary stopping policies. This audit gives a concrete counterexample within the same fixed-backbone/data setting. It neither establishes the ordinary family as universally optimal nor identifies a superior neuron architecture.

The audit summary SHA-256 is `6f2e2d42ce79e7ee8fe828ccb53a86290c6340bc51af25dca32909eea36c85b1`. The [read-only review](REVIEW.json) verifies the selections, 128 actual fixed-1 calls, 384 prediction equivalences, original-summary preservation, source hashes, and all 36 cost rows without any new inference or fitting.
