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

## Same original failing request, not only synthetic features

The new \`fbsde_failed_view_fusion.py\` reconstructs the actual source
\`test:2872\` / view \`0\` from the original failed ZIP. Before use, it verifies
ALL **1,786** chained test-view attempts against the preserved
\`last_attempt_sha256\`, then checks the source/view text fingerprints.
It invokes the original *declared hashing-reference* Encoder (not mmBERT),
verifies the raw 384-dimensional feature vector against the independently
retained replay SHA-256
\`ec410720bec0173fe0b631553d7e37925a3b4a647aa059a8e24402697df2eb39\`,
and reapplies the original saved mean/scale/clamp.

On that **actual rejected input**, local Torch float32 source-head diagnostics
found maximum logits difference \`0\` and argmax changes \`0\` between original
and fused kernels. This check alone does not certify all potential finite
inputs or end-to-end request budgets. No raw source text, copied Head tensors,
gold answer, retrained model or revised production gate enters the report.

New separate CPU research jobs run 513 alternating measurements at 1 and
2 threads, and retain **every sample** plus head-only process CPU
p50/p95/p99/max and over-100-ms counts. Even if no new overrun is observed,
the historical original **108,513,446 ns** request remains rejected:
the causal explanation for that long tail, reproducibility of a rare
scheduler/runtime event and a full-system budget-qualified replacement
are not established. The original CPU cap stays exactly 100,000,000 ns.

\`\`\`bash
PYTHONPATH=qualification/neuron-stem python3 -m unittest -v fbsde_failed_view_tensor_checks
PYTHONPATH=qualification/neuron-stem python3 qualification/neuron-stem/fbsde_failed_view_fusion.py \
  --archive /path/to/original-failed-artifact.zip --threads 1 \
  --output /new/failed-view-one
\`\`\`

### Reconstructed-failing-input local result (negative)

A distinct *local* CPU run on the exact recorded failed view, using the source
ZIP above and frozen original Head, completed **513 alternating paired
invocations per arm and CPU thread setting**, with 20 warmups. The full raw
CPU/wall samples are retained by the local research runner; they are NOT the
future queued GitHub job's results.

| Original failed input | Original Head process CPU p50 | Fused Head process CPU p50 |
| --- | ---: | ---: |
| 1 CPU thread | 17,126 ns | 19,940 ns |
| 2 CPU threads | 16,744 ns | 18,938 ns |

The maximum original-vs-fused logits difference was exactly **0** and there
were no argmax flips. In this small Head-only test, the fused version was
**slower**, unlike the earlier synthetic-vector microbenchmark. The 100 ms
historic complete-view failure did not recur; that is NOT a tail-rate
certificate, actual repaired operation or proof that the runtime explanation
has been isolated. Pairing and per-host variance cannot generalize a
single measured stream to other CPUs, even with the same pinned weights.

The scientific conclusion is **no supported computational win on the
historically rejected input**. Do not promote the fused kernel based on
the earlier synthetic p50/p99 result, hide the unfavorable measurement or
relax the original 100,000,000 ns budget.

Do not alter the original pre-registered FBSDE, model selector, objective,
budget gates, blocking-ci or FinalUse. Any actual adoption would require
prospective independent task quality, end-to-end per-request CPU/FLOPs/p95/p99,
failed attempts and calibration/OOD evidence under an admitted versioned
head with the same \`100 ms\` limit.
