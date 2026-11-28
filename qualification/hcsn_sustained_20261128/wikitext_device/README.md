# WikiText-2 on a physical GPU with real trained checkpoints

The seed-887 twelve-epoch HX and SDPA word models from PR #7280 each contain 1,144,579 trainable parameters, a 32-dimensional hidden state, two blocks and the same hierarchical 33,278-word distribution. We verified both checkpoint byte hashes, source and official test-token hash. The models were evaluated without training on an AMD Radeon 8060S Graphics using Torch 2.13.0+rocm10.0.0 and ROCm 7.15.26333. A device dot product produced 140. The [protocol](PROTOCOL.md) was frozen before either primary evaluation.

### The original 128-position setting and explicit extrapolation

The original model defines 128 learned absolute position vectors and the training protocol reset context after each 128 predictions. Replaying all 245,568 official test targets at 128 positions on GPU reproduced the original CPU test NLL within 1.4e−7 for each model. To examine a specific deployment beyond that window, we reused those 128 vectors periodically and retained hidden state or attention keys until the chosen window ended. Both models restarted at each new outer window and predicted exactly the same official words.

| Context | HX NLL | HX perplexity | SDPA NLL | SDPA perplexity |
|---:|---:|---:|---:|---:|
| 128, original protocol | 5.79081 | 327.28 | 5.75989 | 317.31 |
| 256, cyclic positions | 5.78699 | 326.03 | 5.94068 | 380.19 |
| 512, cyclic positions | 5.78557 | 325.57 | 6.03022 | 415.81 |
| 1,024, cyclic positions | 5.78495 | 325.37 | 6.06973 | 432.56 |
| 2,048, cyclic positions | 5.78467 | 325.27 | 6.09104 | 441.88 |

At 2,048 versus the trained 128 configuration, HX changed by −.00614 nats [−.00752, −.00484] per target and SDPA by +.33115 [.31531, .34865]. Descriptive paired intervals use 5,000 resamples of contiguous 4,096-target blocks of this single official test stream. Agreement with the unmodified strict-window model and with a second presentation of the same extended tokens using irregular chunks and eight singleton appends is recorded in the raw JSON. At the original context, the trained SDPA model was better. The extension tests a specific zero-shot position/state convention and provides no performance measurement from native long-context training or from other attention architectures.

### Storage and actual greedy decoding speed

Each trial conditions on a contiguous span from the real official test stream and generates 16 words autoregressively. The prefix contains `capacity-15` true tokens, so the last prediction sees a context of exactly the specified capacity. The word head computes normalized direct-word and group probabilities, plus all within-group probabilities, and takes the exact argmax over 33,278 actual outcomes on each step. The group-wise independent check over 133,112 scores per arm produced maximum log-probability error below 2.7e−6 and probability-mass error below 1.16e−7. Four paired runs used matching prompts and alternating arm order, with a real device synchronization for the end-to-end measurements. The last-15 GPU timing begins after the prefill and first predicted word.

| Maximum context | HX vs SDPA words/s | HX vs SDPA ms per subsequent word | HX vs SDPA persistent state | HX vs SDPA peak incremental allocator bytes |
|---:|---:|---:|---:|---:|
| 128 | 895 / 1,231 | .761 / .530 | 256 / 65,536 B | 759,808 / 813,568 |
| 512 | 1,156 / 1,674 | .537 / .316 | 256 / 262,144 B | 1,225,216 / 1,059,328 |
| 2,048 | 649 / 1,457 | .683 / .387 | 256 / 1,048,576 B | 4,973,056 / 3,929,600 |

The first throughput column measures prefill plus 16 generated words, summarized by the median of four run throughputs; individual repetitions are preserved. Financial histories carry two 32-element FP32 vectors. SDPA stores two layers of full-width keys and values. The financial per-stream carry stays fixed; prefill buffers, temporary readout matrices and model weights still occupy memory. The original FP32 model with periodic positions did not yield a speed advantage over cached SDPA in these three measured medians, despite its smaller persistent state. The full vocabulary head and the small, single-sample setting are material to the scope.

### Post-primary controls

After observing the periodic-position primary scores, we evaluated every official target under two additional position conventions, clamping subsequent positions to learned vector 127 and assigning a zero vector after 128. We also measured full and last-128 causal attention at both layers. At maximum context 2,048, HX NLL under periodic/clamp/zero-tail positions was 5.78467/5.78584/5.78611. SDPA ranged from 5.96763 for zero-tail + local attention to 6.11653 for zero-tail + full attention. Periodic full/local gave 6.09104/6.08081. Across 1,798 deterministic valid queries (every 128th position from position 255), the full periodic SDPA assigned about 82.3–84.1% of attention mass per layer/head to keys at least 128 positions away. The attention mass describes where a measured model read. It does not isolate the cause of held NLL differences. The controls cover these published position/cap choices and were evaluated after the primary result.

[Primary scores, computational equivalence and bootstrap](wikitext_scores.json) · [All paired per-128-target NLL sums](WikiText_blocks.npz) · [Physical clock records](wikitext_clock.json) · [Raw latency samples](wikitext_times.npz) · [Control scores and attention mass](control_scores.json) · [Control raw sums](control_block_sums.npz).

### Replay

Place the original seed-887 model, scalar-finance sources, both complete weight files and `test.npy` at the `ROOT` paths checked by `evaluate_wiki.py`. Their identifiers are preserved in that script and in the original study's receipts. On the original host, `ROOT` was `/tmp/hxwiki-pr-9284-long887`. Run `python evaluate_wiki.py ROOT`, `python clock_wiki.py ROOT` and `python extrapolation_controls.py ROOT` beside `stream_wiki.py` in a fresh output directory. The zero-shot controls use the original weights and word probabilities throughout.
