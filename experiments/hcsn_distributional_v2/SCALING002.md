# SCALING002: unchanged CPU diagnostic under a separate admission

SCALING001 was registered before the complete content audit. Its frozen entry
gate requires the original analyzer to certify all 176 runs. That analyzer
returned 175 valid and 1 invalid: the FSDD Transformer seed 9202 producer used
float32 cross entropy, and its difference from the analyzer's float64 reference
was 0.000002164839845164579, above the registered absolute tolerance 0.000002.
The original source, protocol and strict result remain unchanged. SCALING001 has
no formal timing workers; its existing constructor checks and one small
random-input preflight retain their original identities and costs.

A separate, explicitly post hoc producer-exact audit independently checked all
176 original runs. It retained the original failure and verified that all
previously complete scientific comparisons, predictions, selections and
thresholds remain unchanged. This is an engineering integrity reconciliation;
it does not turn the original strict gate into a pass. See
`CONTENT_SUPPLEMENT001_PROTOCOL.json` and
`results/content_analysis_supplement001/ANALYSIS.json`.

## New admission, same measurements

`scaling_admission.py` registers `SCALING002_PROTOCOL.json` and writes an explicit
`results/scaling001/NOT_EXECUTED.json` marker. SCALING002 requires the preserved
original 175/1 result, the independent supplemental 176/0 result, all six
scientific reconciliation checks, the complete main and LIF studies, the final
LIF analysis and the successful original-pointer cost normalization.

The original 30 configurations, actual constructor counts, random seeds,
synthetic inputs, original preflight, warmups, three measured repetitions,
single worker, 300-second CPU limit and 600-second wall limit are copied by
exact value. All 70 original executable dependencies retain their hashes. The
new driver calls the frozen `scaling_eval.benchmark` and
`scaling_eval.summary_report` functions directly; their implementations are not
edited or copied into a changed timer. The only additional executable dependency
is the admission driver itself.

Each worker uses random weights and a common synthetic sequence. The measured
optimizer operation includes zeroing gradients, forward, loss, backward,
gradient checks, clipping, Adam update, and parameter/optimizer-state finite
checks. Full worker wait4 CPU additionally includes imports, construction,
serialization, warmups, admission checks and exit. The suite's outer wait4
includes all 30 workers and its coordinator; nested timers are not additive.

## Reproduction

From the repository root, with the CPU environment in `REPRODUCE.md`:

```bash
python -m experiments.hcsn_distributional_v2.scaling_admission register
python -m experiments.hcsn_distributional_v2.scaling_admission run
```

The archived registration already exists in the delivered checkout, so these
commands document the original invocation. A rerun must use a fresh protocol
path and output directory through `--protocol` and `--output`, and preserve the
original marker and evidence. Do not overwrite sealed results or reclassify the
original gate. A future study with changed admission or measurements needs a new
driver and study identity.

The outputs retain the original summary interface: `SUMMARY.json.rows`,
`REPORT.md`, all individual case receipts, `COMPLETE.json`, and the outer
`SUITE_EXECUTION.json`. Completion means all 30 registered cases were attempted
and receipted, including resource failures; it does not require all cases to
succeed. Results describe this CPU implementation, with random weights and
batch size 1. They do not establish content quality, GPU or energy performance,
large-model scaling, or performance at equal quality.
