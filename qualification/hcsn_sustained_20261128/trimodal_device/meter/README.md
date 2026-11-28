# Frozen-model latency, streaming memory and device telemetry

The physical AMD Radeon 8060S benchmark uses the seed-137 first-full-pass checkpoints from the native training directory. Four paired five-second runs per case use counterbalanced arm order, fixed data permutations within pairs, genuine optimizer updates for training, and greedy token generation for streaming. All original timing samples and approximately 10 Hz telemetry accompany the summary. This is a shared integrated APU with other real CPU workloads.

| Mode | Financial throughput | Matched SDPA throughput | Financial median latency | SDPA median latency |
|---|---:|---:|---:|---:|
| Full training, batch 96 | 15,046 examples/s | 14,071 examples/s | 6.283 ms/batch | 6.990 ms/batch |
| Full prefix recomputation, batch 1 | 1,243 output tokens/s | 1,532 output tokens/s | 14.116 ms/utterance | 9.071 ms/utterance |
| Cached generation, batch 1 | 2,019 output tokens/s | 1,788 output tokens/s | 7.266 ms/utterance | 10.759 ms/utterance |
| Cached generation, batch 16 | 26,054 output tokens/s | 27,943 output tokens/s | 10.656 ms/batch | 8.247 ms/batch |

Medians above aggregate the four trial summaries. Each generated condition yields 17 fixed output slots, masks completed sequences by padding, and begins with 34 genuine context tokens including the target marker. Cached inference evaluates only new inputs. At batch 1, financial decoding stores 256 bytes of recurrent state (two width-32 FP32 vectors) and attention allocates 14,400 bytes of K/V state (two layers, both keys and values, 50 positions, width 18). Batch 16 requires 4,096 and 230,400 bytes. These exact state counts exclude parameters, embedding tables, activation scratch space, and output tensors. Peak live framework allocations under cached batch 1 were approximately 92.10 MB financial and 92.07 MB SDPA, so the 56.25× state difference does not translate into a comparable reduction in total memory at this short sequence length. In four paired repeats each cached arm was faster twice at each batch size. The arithmetic state size has much firmer evidence than the sign of a speed change.

### Equality and selected endpoints

The retained incremental layers implement the same financial recurrence and causal attention as the full-prefix models. On every one of 3,933 held condition sequences, we appended irregular blocks of length 1, 8 and 25 followed by 16 single tokens, and compared every logit at all 50 positions. Each arm yielded 17,698,500 comparisons. The financial maximum absolute logit discrepancy was 9.30e−6 and SDPA's was zero; both had zero argmax differences. The financial implementation uses a per-layer state independent of sequence capacity, while the attention implementation preallocates and fills the two layers' causal KV tensors. This benchmark's learned positional embedding bounds both models to 50 positions.

### Power and occupancy

The exposed amdgpu hwmon reports APU package power tracking (PPT). The sampled idle windows measured 84.25–84.83 W, with other CPU load at 32.6–36.1% and reported GPU occupancy of 1.0–22.5% within these idle windows. Train windows averaged a median 84.51/84.55 W for financial/attention; full-prefix generation measured 84.52/84.58 W. The corresponding gross package energies for training were 5.62/6.01 mJ per example. For batch-one full-prefix inference they were 68.00/55.18 mJ per generated token. Idle-adjusted deltas take both signs in repeated windows. RAPL exposes labels for core and package energy but denies access to the cumulative energy counters for this unprivileged experiment. The measurements bound observed whole-package operating conditions. They do not identify per-model incremental GPU energy or an energy advantage on an idle appliance.

[Training and recomputed-prefix run metrics](device_meter.json) · [Complete original latency and power samples](device_meter_raw.npz) · [Cached run metrics and numerical parity](stream_result.json) · [Complete cached timing samples](stream_raw.npz) · [Streaming implementation](stream.py) · [Measurement implementation](stream_measure.py).

### Independent CPU evaluation of sealed GPU-trained weights

All four original development checkpoints were replayed on one CPU thread. The largest target log-probability discrepancy was 4.46e−5 on development and 5.35e−5 on the two selected held arrays; one financial development argmax changed on a valid token, with zero held argmax changes. For each budget, the single-seed 4,000-resample interval below clusters by the 16 held actors. Positive NLL differences favor SDPA.

| Budget | Financial minus SDPA visual NLL | Audio | Transcript |
|---|---:|---:|---:|
| 1 pass | +.1413 [.0760, .2185] | +.1535 [.1340, .1720] | +1.1576 [1.1443, 1.1712] |
| 60 update seconds | +.5940 [.4411, .7465] | +.0751 [.0438, .1073] | +.0387 [.0211, .0521] |

Greedy token accuracies at 60 seconds were 8.08%, 10.83%, 24.45% for the financial model versus 9.72%, 12.27%, 32.82% for SDPA in visual, audio and transcript order. These are unmasked vocabulary outputs on low-bandwidth features and twelve scripted transcripts. [Native-weight CPU replay](native_recount.json) · [All CPU-replayed target log-probabilities and greedy outputs](native_recount_scores.npz) · [Recount and cluster-bootstrap source](native_recount.py).
