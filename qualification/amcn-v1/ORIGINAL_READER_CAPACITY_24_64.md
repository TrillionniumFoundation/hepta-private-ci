# Original Reader 24-to-64 token paired capacity diagnostic

Research SHADOW / DENY_ALL. Archived BF16 30-layer Reader weights; manually reimplemented FP32 CPU path (official HF parity **unverified**). Eight original, deliberately **gold-selected** LoCoMo questions from four retrospective families, one unchanged question/prompt/source bundle per arm. The private original input, token journal and publisher answer text are **not** committed.

The local original run produced 16 additional Reader answers at 64 max output tokens, with **16/16 recorded numeric token-prefix agreement** against original 24-token generation for two witness/lesion arms. This was validated in an isolated analysis environment, not on the user's dot host; this public source-only negative gate does not independently authenticate that original execution.

| Original same-prompt condition | 24-token limit | 64-token limit |
|---|---:|---:|
| Witness: publisher answer substring proxy | 4/8 | 5/8 |
| Witness: exact answer equality | 0/8 | 0/8 |
| Lesion: substring proxy | 0/8 | 0/8 |
| Witness generated tokens | 161 | 336 |
| Lesion generated tokens | 178 | 293 |

Same Reader input tokens across the two output ceilings per condition (witness 1,425, lesion 1,266). **Actual output cost differs**, and witness vs lesion prompts differ in length. Publisher answer text was used to choose the eight cases *before* generation. A substring does not prove semantic correctness, sufficiency, source entailment, or any MemoryCell learning gain. No independent evaluator, official HF parity, real future windows, prospective source groups, or model promotion.

This artifact only ensures the published negative numbers and NO-GO interpretation remain stable. It is not the private complete 16-attempt physical audit or an E1/E2/E3 positive result. Do not merge, select, fuse/split cells or grant FinalUse.
