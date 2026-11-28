# Constant streaming state in the six-layer audiovisual encoder

The native six-layer encoder now accepts chunks via `AVText.encode_chunk(embedded_frames, state)`. The returned embedding describes the chunk's last position and the returned state carries the complete physical recurrence into the next chunk. The attention alternative retains the exact past keys and values. The default full-window encoder retains its original method. The physical and attention implementations load the exact original weights with strict state-dictionary loading. This sibling implementation preserves the immutable source used in the recovered CREMA-D results.

Across four arms, two floating precisions and four execution modes, all 32 output/derivative comparisons passed. With gradient flow across all chunk boundaries, the largest FP64 gradient discrepancy was 9.99e−16 and forward embeddings agreed exactly at the original float32 projection. The largest FP32 gradient discrepancy was 1.19e−5 and the largest forward difference was 5.97e−8. Checks include all weights used in the embedded encoder and the full input gradient; the audiovisual frontend and text embeddings are outside this specific test.

| FP32 inference, batch 1, width 96, six layers, 256 embedded frames | Persistent state bytes | One-frame chunks, ms | 16-frame chunks, ms | All frames together, ms |
|---|---:|---:|---:|---:|
| Literal physical HCSN | 5,376 | 184.61 | 106.68 | 96.61 |
| Smooth price control | 5,376 | 189.60 | 117.75 | 107.40 |
| LIF | 3,072 | 120.96 | 54.60 | 47.75 |
| Causal attention | 589,824 | 112.95 | 10.03 | 4.27 |

Measured on one ai395 CPU thread, three native cold-free inference clock observations per row. The volume measures the logical live tensors passed between chunks. At 16, 64 and 256 frames HCSN carried 5,376 bytes each time, while causal attention carried 36,864, 147,456 and 589,824 bytes. At 256 frames attention's materialized cache was 109.7 times larger than HCSN state, yet it ran faster at every reported chunk size. LIF used less persistent state than HCSN. The full-window attention path used native Torch causal SDPA. Streaming attention used an exact concatenating cache and a causal mask for noninitial multi-frame chunks. Cache allocation strategy and attention backend affect elapsed time. Training activations, model weights, intermediate workspaces and process-wide RSS are outside this state-size measure.

The three physical arms share a finite state, which gives different sequence prefixes the same summary in some cases. The original task front ends support 12 positional slots. The longer measurements use seeded synthetic embedded frames to isolate the encoder's mechanics. They provide resource measurements independent of sequence-length quality. Long-stream accuracy requires its own benchmark.

All four models have equations and weights identical to the immutable source on the original interface. Reproduce on a native PyTorch installation with the original `billion_recovery/original/scripts` directory and `crema/src/law4.npz`. The command is `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python verify_and_time.py ORIGINAL_SCRIPTS LAW_FILE results.json`. Raw clock repeats, derivative checks and full outputs are in `results.json`.
