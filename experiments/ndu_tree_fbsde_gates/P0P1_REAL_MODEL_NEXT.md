# P0/P1 real-model evidence preflight (research-only)

This is a new **fail-closed panel-shape gate**, not a pretrained model runner.
It inventories 4 model families (Laya421, Granite97, mmBERT-small,
EmbeddingGemma2), 4 logical Cell scales (64/256/1024/4096) and 4 comparator
arms (frozen/linear/gated/physically shared 421M control), giving 64 complete
slots. Every slot requires an external claimed independent evidence origin,
model/weights/runtime, unchanged objective/Reader/dataset/host identity,
the SAME group/input/independent outcome reference, physical Encoder and Head
forward counters and >=100 raw positive finite batch latencies.

Missing energy remains null, never a fabricated zero. Scope and generation
authentication, genuine weight reads, GPU and energy metering, real Reader
and scorer execution, privacy and license admission, physical memory and
cross-process verification are NOT established by text declarations. Even an
entirely syntactically valid externally asserted panel always returns
`p0_accepted=false`, `p1_accepted=false`, `DENY_ALL`. A separately
qualified independent observer must authenticate the bytes and experiment
before any claim.

Use existing #1775/#1885/#1897/#1779 real-model experiment producers;
do not create a competing model loader. Use PR #1550 for math reference
and current PR #1923 for Tree-FBSDE research gates. No production owner changed.

Reproduce:
`python3 -m unittest discover -s experiments/ndu_tree_fbsde_gates -p 'test_p0p1_physical_gate.py' -v`

The tests use only fixtures to exercise acceptance/rejection logic; **they
are not pretrained model tests or 4096-Cell full runtime runs**.
