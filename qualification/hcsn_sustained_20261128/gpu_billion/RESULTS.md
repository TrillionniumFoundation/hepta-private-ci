# Verified physical billion-parameter CUDA execution

With a real Tesla T4, Torch 2.14.1+cu130, CUDA arithmetic probe 140, the six-layer model executed all 1,016,475,200 parameters. The study reconstructed exactly the source's twenty selected audiovisual clips, all 72 text prompts and all original price/transport arrays. One common seeded parent exposed seven matrices containing 4,980,736 writable scalars. There were sixteen training clips, two development clips and two held clips from disjoint actor splits. The held subset is a hardware-execution specimen and is too small to support inferential accuracy claims.

| Candidate | Device fit seconds | Mean held NLL | Held correct out of two |
|---|---:|---:|---:|
| Initialized | 0.0000 | 4.33486 | 0 |
| Six forward writes plus shared projection | 0.464 | 9.68532 | 0 |
| Shuffled hidden labels | 0.2102 | 8.41989 | 0 |
| Same-site AdamW BP | 7.168 | 4.32944 | 0 |

Total work was 27.06 seconds. The forward write used 4,282,546,688 peak allocator bytes and BP 6,285,382,144. One AdamW step on the training batch includes creating the optimizer and first-use kernel costs. These are hardware and workload observations. The primary loss is worse after the forward write, so the much shorter fit time does not establish a time-to-equal-quality advantage. All 1,152 recorded gallery scores across four candidates and two splits were rescored in NumPy, reproducing each correct count and every NLL within 4.78e−7. Each row retains the seven before/after hash identities and number of changed scalars. The service's allocation, computation, collection and release receipts correspond to this exact job. This does not consume or replace the full three-seed CPU edit panel or the original shared-host GPU queue.
