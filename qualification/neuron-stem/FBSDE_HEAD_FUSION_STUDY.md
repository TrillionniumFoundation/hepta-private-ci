# Exact failure-bound Head fusion control — NOT an FBSDE acceptance

Separate research-only execution on the historical failed
[Actions 38518554636](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38518554636)
acquisition archive, artifact **11875899646**, ZIP SHA-256
\`cd9997b69e88b88f0817985fca00cb5b359936bcd5589fd49cc2c5ac78cb200a\`.

The original experiment exceeded its unchanged **100 ms process CPU** per
view limit: the failing call consumed **108,513,446 ns**, of which
**108,133,707 ns** was in the Head stage. Its real original trained small
Head was therefore **rejected**, no prediction was returned, and the source
run's \`scientific_pass\` remains **false**. The failure is not rewritten.

The separate CPU candidate concatenates the *already trained* frozen
\`value.weight\` and \`gate.weight\` matrices into a single forward-only
linear projection, concatenating biases likewise, before timing. It then
applies the original tanh/sigmoid and untouched final projection. No
weights are refitted or optimized. Both the original and fused arithmetic
use the **same** pinned archived six tensors and 64 deterministic
**synthetic** numerical feature rows, plus saturated-gate parity vectors.
A direct test rejects changed argmax or logits diverging beyond 1e-6.

CPU measurements at both **one and two threads** include 20 warmups per
candidate and 513 alternating-order invocations per candidate. Prepacking
cost is retained separately; fused resident tensor copies count separately
and cannot be called device-memory savings. Record process CPU p50/p95/p99/max,
wall metrics, true source/Head/receipt hashes, and absence of any new
pretrained, task-gold or production model. The archived failed case text
and its exact normalized 384-vector are **not** reconstructed: performance
on the 64 test vectors is NOT proof of remedy for the historical 108 ms
anomaly, nor a stable 100 ms bound across processes, hosts or scheduling.

The CI job downloads the original ZIP, requires its *exact* external SHA,
and performs weights-only checkpoint loading. It uploads only new numeric
reports, never training data, model tensors, original ZIP or private tokens.

Local diagnostic:

\`\`\`bash
PYTHONPATH=qualification/neuron-stem python3 -m unittest -v fbsde_head_fusion_tensor_checks
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_head_fusion_probe.py \
  --archive /path/to/original-failed-artifact.zip \
  --threads 1 --output /new/fusion-one
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_head_fusion_probe.py \
  --archive /path/to/original-failed-artifact.zip \
  --threads 2 --output /new/fusion-two
\`\`\`

Do not alter the original pre-registered FBSDE, model selector, objective,
budget gates, blocking-ci or FinalUse. Any actual adoption would require
prospective independent task quality, end-to-end per-request CPU/FLOPs/p95/p99,
failed attempts and calibration/OOD evidence under an admitted versioned
head with the same \`100 ms\` limit.
