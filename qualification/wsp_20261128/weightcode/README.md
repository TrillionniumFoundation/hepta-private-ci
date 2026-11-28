# WeightCode/SCAN public reproduction evidence

This package contains a completed fixed CPU matrix and its public source pins.
It contains no pocket4 model, private Hepta checkpoint, credentials or trading data.
The accompanying `colab_status.json` states whether the separate same-grammar
rule-to-data run has actually completed or is still awaiting evidence.

## Outcome and interpretation

The published 257-parameter WSP program reproduced its full canonical child hash
exactly. On the public sealed split it changes new-command exact match from 0 to
99.8053%, preserving old-command exact match at 99.6%. This reruns a program
originally authored by Claude Opus 5.5; it is not a new independent GPT discovery.

The fixed 65-label Adam/LoRA comparisons begin with token CE only 5.23e-9 on their
training rows. Their lack of new-command gain does not establish that gradient
learning cannot perform the task. The explicit grammar supplies knowledge beyond
those 65 labels; published grammar-generated training reaches 99.6%, and its
independent fixed-configuration reproduction is recorded separately.

The WSP program probes 299 of 2,568 final-new inputs and every final-old input
without labels, so this is a label-heldout public reproduction, not a fresh
completely unseen-input experiment. Inferences about HeptaTrader are not made.

| Fixed arm | Final new EM | Final old EM | Selected parameters changed |
|---|---:|---:|---:|
| base | 0.0000% | 99.6000% | 0 |
| embedding_only | 0.0000% | 99.6000% | 128 |
| head_weight_only | 0.0000% | 99.6000% | 128 |
| head_bias_only | 23.3645% | 99.6000% | 1 |
| embedding_head_weight | 0.0000% | 99.6000% | 256 |
| embedding_head_bias | 79.5950% | 99.6000% | 129 |
| head_weight_bias | 26.5966% | 99.6000% | 129 |
| full_published_edit | 99.8053% | 99.6000% | 257 |
| random_support_norm_seed0 | 17.6012% | 36.5000% | 257 |
| random_support_norm_seed1 | 0.7009% | 99.6000% | 257 |
| random_support_norm_seed2 | 0.0000% | 99.6000% | 257 |
| f1_last_seed0 | 0.0000% | 99.6000% | 0 |
| f1_last_seed1 | 0.0000% | 99.6000% | 0 |
| f1_last_seed2 | 0.0000% | 99.6000% | 0 |
| f1_full_seed0 | 0.0000% | 99.6000% | 0 |
| f1_full_seed1 | 0.0000% | 99.6000% | 0 |
| f1_full_seed2 | 0.0000% | 99.6000% | 0 |
| lora_r4_seed0 | 0.0000% | 99.6000% | 0 |
| lora_r4_seed1 | 0.0000% | 99.6000% | 0 |
| lora_r4_seed2 | 0.0000% | 99.6000% | 0 |

CPU matrix wall time: 1591.693s. All restore operations verified the complete original canonical hash.


## Files and reproduction

`source/scan_extension_protocol.json` was fixed before extension results were
observed. `results/manifest.json` records protocol, runner, source and environment
identities. `results/arms/*_selection.json` records every BP candidate and the
check-only decision before its selected final reading. The source scripts call
the pinned upstream model/optimizer implementations.

Clone the pinned upstream commit, use its public downloader to fetch and verify
the declared model/data, run the official `weightcode reproduce scan` example,
and run `source/run_scan_extension.py` with paths adjusted as a recorded harness
change. The recorded local execution path is deliberately preserved in evidence;
do not present an unrun path adaptation as another verified reproduction.

Large archives use ≤450,000-byte chunks. Concatenate the listed parts in order,
verify the complete SHA in the adjacent `.manifest.json`, then decompress. Each
archive retains exact filenames and public scientific arrays.

Read `source/wsp_research_handoff_20261128.md` for primary-source literature,
the distinction between metadata inspection and circuit analysis, and Hepta
information-path/span/true-recursion diagnostics. Literature suggestions are
not converted into measured Hepta performance claims.
