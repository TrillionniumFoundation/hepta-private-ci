# Full-model CPU work and cross-process recovery

All 14 registered timing configurations and the selected-model recovery fixture completed. Three timed repetitions follow declared warmups. Optimizer timing includes zeroing gradients, forward, cross entropy, backward, clipping, Adam.step and the finite-output check. Imports and setup are included separately in each complete worker receipt.

## Measured CPU seconds per complete optimizer step

| Model | B=4, T=32 | B=4, T=128 |
| --- | ---: | ---: |
| distribution_free_dual | 0.202282 | 0.978704 |
| distribution_conditional_dual | 0.165153 | 0.899142 |
| distribution_free_ordinary | 0.200579 | 0.922552 |
| active_mean_collapse_free_dual | 0.160687 | 1.150819 |
| legacy_free | 0.131034 | 0.539925 |
| two_gates | 0.010953 | 0.054001 |
| transformer | 0.005640 | 0.009060 |

At B=4,T=128, the distributional free-dual step takes **18.12×** the ordinary two-gate CPU and **108.02×** the small Transformer CPU. These measurements do not support a whole-model CPU speed advantage. The earlier prepared-operator microbenchmark compares two implementations of the distributional kernel; it cannot be transferred to a different backbone comparison.

These are small, random-weight, synthetic CPU microbenchmarks on a shared host. The baseline Transformer calls PyTorch SDPA; there is no fused HCSN GPU kernel or hardware energy measurement. The main content study separately evaluates equal training-CPU budgets. Timing alone does not establish a quality-cost frontier.

## Selected-model streaming and recovery

The trained checkpoint is bound to successful summary, selection, source/data/protocol identities, complete worker exit and the full physical model configuration. Merely matching NPZ tensor shapes is insufficient; an ordinary-feature checkpoint is explicitly rejected.

The selected MNIST free-dual seed9201 model runs 256 synthetic steps at B=2, saves after step113 with nonzero refractory mass, and resumes 143 steps in a distinct Python process (PID 21 → 22). Every suffix logit and final tensor is bitwise equal to uninterrupted execution.

Full-sequence versus step-by-step logits differ by at most **7.153e-07**, with 0 argmax disagreements. Maximum probability mass error is **3.695e-06**. The checkpoint contains **968 bytes** of persistent float32 state at every step: elapsed time plus content, full spatial/phase probabilities and physical boundary. This excludes weights, output history, optimizer/BPTT storage and any baseline KV cache.

For B streams, D layers, content width W, C physical channels, S spatial cells and R phases, the measured layout is 4B[1+D(W+C(S+R+1))] bytes. Constant persistent state does not prove constant training memory or sufficient long-context recall: training stores time-indexed operators and autograd state.

Complete suite CPU is **98.293059 s**. Its **95.665581 s** worker total includes nested resume and must not be added again. The separately measured model/state load component excludes interpreter startup and source checks; no production restart-latency claim is made.
