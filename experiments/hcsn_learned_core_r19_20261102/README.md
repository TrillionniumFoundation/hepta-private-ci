# Learned full-state content and independent controller fitting

This candidate performs real BPTT through a forty-coordinate learned-model
phase/code belief and a neural content head, with a learned positive timescale
through `torch.matrix_exp`. Its public source law is the inherited finite R15
first-passage/recovery generator. It is not the full continuous He-Xiong model.

The latent intervention model is explicit: a public WRITE code supplies a
column-softmax distribution over latent content codes while preserving phase;
the read channel is a separately row-normalized learned emission matrix; time
propagates by `exp(exp(log_scale)*Q*dt)`. Consequently the stored tensor is a
normalized conditional state of this declared learned model. It is not asserted
to be the exact physical owner's class posterior. A discriminatively trained
40→32→4 head reads all coordinates, not a scalar activity gate.

Ordinary candidates include a fitted per-address GRU, stable dense SSM, typed
cache and the ordinary same-Q HMM realization of the learned filter. The latter
is mandatory and can reproduce the analytic candidate exactly. Independent
training of these equivalent families does not manufacture an exclusive
analytic capability. All cores receive common typed routing, supplied alias
maps, public observations/durations and source metadata. This is symbolic
alias retrieval, not learned semantic addressing or real AV binding.

Eighty optimizer jobs cover five cores, two controllers and eight fit seeds.
Matched updates are not matched parameter counts, memory or CPU. The head
initialization, symbol encoder and complete offline paid training observations
are common. Only purchased responses enter the actor history; test scoring
labels and unpurchased responses cannot affect the controller. The validation
pool always retains the same-Q HMM. All fitted weights, light thresholds and
ordinary selections are published by digest before test worlds are opened.

The current-query controller forecasts a common deadline and chooses STOP or a
priced high-quality READ at that deadline. It does not implement the original
mid-query WAIT/REFRESH tree or optimize all future queries. Its expected READ
correctness uses model predictions, rather than an oracle future label. Light
and value models are independently trained; the factorized-state intervention
is separately labelled a same-weight execution diagnostic.

From the repository root with the current Torch CPU runtime installed:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -m experiments.hcsn_learned_core_r19_20261102.campaign \
  --stage prepare --output experiments/hcsn_learned_core_r19_20261102/run_01
```

The prepare stage requires verified `PUBLICATION.json`. Before confirm, remotely
publish `run_01/SELECTION_FREEZE.json` and create `POSTTRAIN_PUBLICATION.json`
containing its `selection_freeze_sha256`, commit SHA and `readback_verified=true`.
Then invoke the same command with `--stage confirm`. All outputs are create-only.
Full outer CPU includes interpreter/Torch imports, collection, all candidates,
validation/selection/checkpoints, tests, ablations and output. Logical observation
fees are separate from CPU and from unmeasured hardware energy.
