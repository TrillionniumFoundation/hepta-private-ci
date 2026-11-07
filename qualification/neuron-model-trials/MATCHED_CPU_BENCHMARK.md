# Three-arm repeated CPU model diagnostic (shadow-only)

The [three-weight physical run #38095795540](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38095795540)
loaded all three publisher-pinned public Laya variants and completed one
synthetic forward per arm. Those **single latency samples are not percentiles**
or production throughput evidence.

The new workflow \`hepta-neuron-matched-cpu.yml\` runs only when the existing
\`hepta-neuron-physical-smoke\` label is explicitly added to PR #1494.
It downloads each approved public weight directory at revision
\`7b928d828b7b0e022f929d9bd2e44165aa270148\` into disposable runner
storage, checks actual bytes and the pinned Laya Python SDK source, then
starts a fresh CPU process for each model. It forces the same synthetic
label-free English choice input, 512 input tokens maximum, 192 option tokens
maximum, two torch CPU threads, five warmups and one hundred measured
single-request model forwards.

Per-arm diagnostic JSON retains actual parameter counts, SDK/model/weight
digests, raw 100 latency observations, nearest-rank p50/p95/p99, model load
time, token count, and Linux process VmRSS/VmHWM before/after loading and after
forward calls. The independent replay script **recomputes** these
statistics and rejects conflicting model identities, altered sample
percentiles, missing arm receipts and fabricated production permissions.
It does not independently authenticate who generated the observations.

The diagnostic upload contains only JSON; no weights, HF cache, user data,
labels, credentials or production authority tokens are retained.

**Do not interpret this diagnostic as** backend batching, 4,096-Cell
throughput, a production p99 SLA, multilingual accuracy, OOD calibration,
real task benefit, NDU net gain or an authorized model replacement.
The shared runner's operating environment and tokenizer token counts may
differ; a named-host controlled replay and independent evaluator are required.

Offline tests:

\`\`\`bash
python3 -m unittest discover -s .github/scripts -p 'test_hepta_neuron_cpu_benchmark.py' -v
\`\`\`

Explicitly pre-materialized local weights (no implicit network at inference):

\`\`\`bash
python3 scripts/hepta_neuron_cpu_benchmark.py \
  --catalog qualification/neuron-model-trials/upstream-weights.lock.json \
  --arm laya --artifact-dir /absolute/pinned/laya \
  --sdk-python-sha256 VERIFIED_INSTALLED_LAYA_SOURCE_SHA256 \
  --warmup 5 --samples 100 --threads 2 \
  --output /absolute/new/laya-cpu-diagnostic.json
\`\`\`

Only the independent learning/effect evaluators, future observations,
replay and production owner can establish meaningful Hepta gain. All existing
production model selection, route cutover and Cell lifecycle fences remain
unchanged by these tools.
