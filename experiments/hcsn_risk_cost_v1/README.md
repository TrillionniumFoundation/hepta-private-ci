# New risk model: matched CPU cost supplement

This post-baseline supplement adds the actual `risk_margin_j_risk` model to
the existing small-scale CPU quality/cost panel. Original J/G measurements
cannot be used as measurements of the new first-event-risk/projection model.
The original72 workers, results,50-source closure and protocol remain unchanged;
the risk family's55-source closure also remains unchanged.

Eighteen new candidates use the same two tasks, seeds9301–9303 and scales
16×1,32×1,64×2. The cost worker, optimizer,20-second training CPU allowance,
learning rate0.001,batch32,validation checkpoints at15/20CPU seconds,quality
targets0.50/0.75/0.90,and inference batches1/32 are reused without alteration.
Only the model factory is replaced inside an isolated child process. The new
risk model has the same active parameter count and exact initial tensors as
the original J/G model at each scale; train-only preflight verifies this.

Both selection and every quality operating point are locked before heldout
access. The earliest eligible checkpoint reaching a validation target is
used. A pair qualifies only if both heldout accuracies reach that same target,
differ by at most two percentage points,and all three paired seeds qualify.
There is no interpolation,extra training,replacement seed or post-test tuning.
These are descriptive quality-conditioned points,not statistical equivalence.

The merged analyzer verifies the original72 and new18 rows under their own
protocols,initializations,minibatch prefixes,checkpoint hashes,prediction
metrics and inference replay. It compares the risk model with the three
external baselines(two gates,LIF SNN,Transformer); the original J/G model is
an additional diagnostic control. Inference timing includes the new killed
generator/risk operator,free-boundary/value computation and probability
projection. Complete isolated-worker `wait4` CPU includes setup,training,
validation,I/O,heldout evaluation and timing. Training is nested within this
cost. Peak RSS is whole-process memory. CPU wall timing is on a shared host.

```bash
python -m experiments.hcsn_risk_cost_v1.study preflight \
  --output experiments/hcsn_risk_cost_v1/results/train_preflight001
python -m experiments.hcsn_risk_cost_v1.study register \
  --preflight experiments/hcsn_risk_cost_v1/results/train_preflight001/PREFLIGHT.json \
  --output experiments/hcsn_risk_cost_v1/results/risk_scale001
python -m experiments.hcsn_risk_cost_v1.study run \
  --output experiments/hcsn_risk_cost_v1/results/risk_scale001
python -m experiments.hcsn_risk_cost_v1.analyze \
  --main-study experiments/hcsn_cost_scaling_v1/results/scale001 \
  --supplement-study experiments/hcsn_risk_cost_v1/results/risk_scale001 \
  --output experiments/hcsn_risk_cost_v1/results/merged_analysis
```

Registration and publication of the new seal precede supplement training and
heldout evaluation. This panel remains an exploratory test on previously
observed datasets. It measures no energy,GPU performance or foundation-scale
training,and it cannot claim a same-quality speed advantage where its quality
gates do not qualify.
