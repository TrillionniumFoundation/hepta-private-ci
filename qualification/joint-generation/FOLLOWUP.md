# Efficient-budget follow-up

The r1 frozen evaluator passed its declared narrow gates. Its 98 retained files
and execution source remain unchanged. That result does not close two broader
requirements of the first goal:

1. All r1 training arms executed both utility gradients and discarded unused
   work; its random route also executed a critic whose output was discarded.
   Those controls do not demonstrate an advantage over a baseline that uses its
   savings for additional useful training or generation.
2. Rejecting audio/video exactly like unknown strings did not constitute a
   typed all-modality interface. The new media adapter maps the existing HNMF
   modality/range vocabulary, validates media payload and synchronization, and
   keeps unavailable backends explicitly unsupported.

From the already retained r1 summaries, dynamic minus direct full inference has
mean raw utility +0.002344895 and +0.398578811 forwards. At the unchanged 0.02
price, its difference is -0.005626681 before critic cost. No r1 dataset was
constructed to establish this limit, and the old positive random-route comparison
is retained rather than rewritten.

The independent r2 protocol lives in `independent/plan.json`. It adds the
same-CE-weight anchor ablation, useful-only cached gradients, one-forward training,
complete build caps including search and critics, and efficient no-critic static
baselines. It measures process CPU and declared operator work separately and
prices actual CPU including build amortization for the primary system comparison.
An exact folded thumbnail encoder computes 58 input dimensions rather than doing
a second 202-dimensional encoder pass. All systems use the same native runtime.

New physical-source train/validation/test splits and a newly trained common base
are required. They share the finite semantic vocabulary with r1; they are not
claimed to be historically unseen semantic classes. Every source's instructions
and sensor variants stay together. The new test must remain unopened until the
protocol, source hashes and selection are frozen and validation is ready.

The first four r2 training/validation builds all exited 2 and never constructed
the formal test. Their signed failures, models and costs remain in verified
lossless archives under `runs/codex-cloud-efficient-r2-t1` through `t4`.

| Build | Content A-anchor utility | NDU-additive utility | Control CPU-net vs efficient reference | Outcome |
|---|---:|---:|---:|---|
| t1 | +0.019041 | +0.000679 | -0.009623 | Unready |
| t2 | — | -0.060660 | -0.145698 | Unready; two actual CPU cap breaches |
| t3 | +0.021224 | +0.006639 | -0.004409 | Unready; caps held |
| t4 | +0.024836 | +0.003498 | -0.004656 | Unready; caps held; raw control/random also negative |

These are validation mean contrasts, not held-out confidence intervals. t4
aligned raw critic gain and complete marginal service CPU using train-only
calibration, and allowed every arm affordable residual training with original
Adam/RNG state. Neither change closed the effective-control benefit gap.
Its [report](runs/codex-cloud-efficient-r2-t4/REPORT.md) and
[standalone smoke](runs/codex-cloud-efficient-r2-t4/standalone-smoke.json) separate
real trainable content/export evidence from the failed scientific claim.

First-goal efficient-budget acceptance remains blocked by demonstrated control
net-benefit failure. Audio/video generation and long interactions remain unrun
subsequent work, rather than claims made by a transport schema or by the r1 result.
