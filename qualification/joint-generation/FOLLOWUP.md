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

The first six r2 training/validation builds all exited 2 and never constructed
the formal test. Their signed failures, models and costs remain in verified
receipts under `runs/codex-cloud-efficient-r2-t1` through `t6`; earlier complete
builds also have byte-verified lossless archives.

| Build | Content A-anchor utility | NDU-additive utility | Control CPU-net vs efficient reference | Outcome |
|---|---:|---:|---:|---|
| t1 | +0.019041 | +0.000679 | -0.009623 | Unready |
| t2 | — | -0.060660 | -0.145698 | Unready; two actual CPU cap breaches |
| t3 | +0.021224 | +0.006639 | -0.004409 | Unready; caps held |
| t4 | +0.024836 | +0.003498 | -0.004656 | Unready; caps held; raw control/random also negative |
| t5 | +0.014986 | +0.012584 | -0.002427 | Unready; caps held; raw control/random also negative |
| t6 | +0.007445 | +0.012055 | -0.014405 | Unready; caps held; affine raw control/random +0.001884 |
| t7 | — | — | — | Exit 1; shared admission left no candidate allocation |
| t8 | — | — | — | Exit 1; shared CPU 12.274880402s exceeded the unchanged 10s cap |
| t9 | +0.023052 | +0.004811 | -0.002094 | Exit 2; all caps held; affine raw control/random +0.001311 |

These are validation mean contrasts, not held-out confidence intervals. t4
aligned raw critic gain and complete marginal service CPU using train-only
calibration, and allowed every arm affordable residual training with original
Adam/RNG state. Neither change closed the effective-control benefit gap.
Its [report](runs/codex-cloud-efficient-r2-t4/REPORT.md) and
[standalone smoke](runs/codex-cloud-efficient-r2-t4/standalone-smoke.json) separate
real trainable content/export evidence from the failed scientific claim.

The common exact-output optimization in t5 admitted 84 residual control rounds
versus 45 static NDU rounds. Final control updates were 389/450/450 versus
388/431/431, but its full-content utility still trailed by 0.001265 on average;
its own routing lost another 0.000780. More optimization steps do not guarantee
better decoded raw utility. The [t5 report](runs/codex-cloud-efficient-r2-t5/REPORT.md)
retains the actual build, scope and complete-cost boundaries.

The core content/NDU generation claim and the stronger adaptive-continuation
claim have separate evidence states. Core validation contrasts are positive but
not independently tested. The frozen r2 dynamic gates remain failed. Neither a
service smoke nor a transport contract permits an overall first-goal pass.

The [t6 affine report](runs/codex-cloud-efficient-r2-t6/REPORT.md) shows positive
same-weight routing means for every seed, but only 164/172/169 control updates
and no residual rounds. Shared preparation consumed 6.543 CPU seconds; a large
TRAIN preparation maximum was repeated in all eight future control measures'
CPU forecast. Actual control cost was lower, leaving about 0.977 seconds unspent.
This is conservative opportunity cost, not fake billed work. The prospective
forecast stores all raw TRAIN samples and reserves median repeated cost plus one
observed excess; actual budget guards, prices and all benefit gates stay fixed.

First-goal efficient-budget acceptance remains blocked by demonstrated control
net-benefit failure. Audio/video generation and long interactions remain unrun
subsequent work, rather than claims made by a transport schema or by the r1 result.

The [t8 report](runs/codex-cloud-efficient-r2-t8/REPORT.md) retains the complete
shared metadata that was missing from t7's early failure. All original costs,
models, calibration samples, traceback and nonzero status are preserved. The
equivalent incremental ledger cache passed 151 independent source tests and
exact old/new hand-fixture comparisons; its actual-update timings were mixed,
with only 0.15% aggregate saving. It did not close the actual resource blocker.

One prospectively declared [timer-only diagnostic](runs/codex-cloud-efficient-r2-shared-timing-d2/REPORT.md)
partitioned a new execution into 43 disjoint high-level CPU spans. It used
2.528051049s CPU, of which 2.506054746s was assigned to spans, and reproduced all
three t8 base files and its native library byte-for-byte. It retained a real
169ms output-encoding outlier. The multi-second slowdown was not reproduced;
its cause remains unknown. This is a separate development diagnostic, not a
replacement pass or permission to repeat identical qualification for favorable
CPU timing. No subsequent qualification or formal evaluation was run.

The next build needs a concrete supported repair under the existing protocol.
Current evidence does not identify one that closes the resource variation or
the effective-control benefit gap. No cloud-quota error was observed; the actual
failure is the frozen scientific CPU budget. GitHub identity/PR API queries
remain separately denied with `Forbidden`; Git branch transport succeeded.

The subsequent fixed paired launch probe retained four complete shared
executions and actual numerical-backend identities; it did not reproduce t8
slowness or support blaming the idle Python parent. Concrete local allocation
and decoder-observation reuse then passed source checks and were frozen before
the [t9 build](runs/codex-cloud-efficient-r2-t9/REPORT.md). That complete build
held every cap and retained positive core content/NDU and same-weight routing
means, but its complete effective-control CPU-net gate still failed. Its
[cost decomposition](runs/codex-cloud-efficient-r2-t9/COST_DECOMPOSITION.md)
identifies a -0.003729 content-model gap, partly offset by +0.001311 routing and
+0.000324 complete CPU pricing. NDU/control trained 386/367 updates per seed.
All candidates were limited by their operator allocations, with CPU headroom.

The next implementation targets repeated low-view encoder arithmetic during
continued training. Shared dense pretraining remains unchanged so the common
base bytes stay fixed; existing data/RNG/loss and all benefit gates remain.
Its real variable-step work and floating-point reordering require hand-fixture
gradient, optimizer and admission tests before any new source-frozen build.
No operator saving or acceptance is credited before implementation/measurement.
