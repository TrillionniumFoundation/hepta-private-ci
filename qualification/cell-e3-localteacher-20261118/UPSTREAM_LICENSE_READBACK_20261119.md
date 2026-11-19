# E3 model-rights readback — 2026-11-19 UTC

Scope: read-only upstream public license and metadata comparison. **No new teacher/model call, weight download, training, license grant, or business qualification.** Original E3 execution and negative outcome remain at [#6705](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6705), commit `5e027a1d0c49a2b1408e90491b4cc0bc1660725f`.

## Verified public surfaces

| Surface | Observed source | Implication |
| --- | --- | --- |
| Original model | [Qwen/Qwen3.8-Flash-Next model card](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) and [LICENSE](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/LICENSE) | Model metadata and distributed LICENSE both say **Qwen Community License 1.0**, not Apache-2.0 |
| Abliterated derivative | [orcarouter/Qwen3.8-Flash-Next-Uncensored card](https://huggingface.co/orcarouter/Qwen3.8-Flash-Next-Uncensored) and [LICENSE](https://huggingface.co/orcarouter/Qwen3.8-Flash-Next-Uncensored/blob/main/LICENSE) | Card metadata reports **apache-2.0**, but its distributed LICENSE is **Qwen Community License 1.0** |
| An IQ4_XS GGUF public listing | [mradermacher/Qwen3.8-Flash-Next-Uncensored-i1-GGUF](https://huggingface.co/mradermacher/Qwen3.8-Flash-Next-Uncensored-i1-GGUF) | Card labels Apache-2.0 and offers IQ4_XS; a similarly named GGUF is **not** proof that the ai395 local file came from this repo or revision |

Qwen Community License 1.0 includes source-notice preservation and conditions for large commercial services. In particular, it specifies a separate-license condition for certain **commercial Model-as-a-Service or AI Work Assistant businesses**, with an internal-use exclusion defined in the license. The actual full LICENSE, not this summary, controls. This is an engineering rights-risk note, **not legal advice or a license adjudication**.

## Original local artifact and experiment boundary

The measured ai395 T2 checkpoint was labelled `Qwen3.8-Flash-Next-Uncensored-IQ4XS-NGQ4`; original measured GGUF size **98,403,356,224 bytes**, SHA-256 `cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e`. That local hash binds the bytes used in E3, **not** a verified upstream repo/revision/weight conversion chain. The old E3 report explicitly restricts the authorized context to **private internal research** and leaves the public/commercial right unresolved. No new access, service reconfiguration, rehash of 98 GB, inference or training occurred during this readback.

The original comparative result stays unchanged: T1 final **0/6**, T2 final **1/6**, their union **1/6**, gain over best teacher **0**. Information and logical call caps were matched; actual physical compute was not. Neither mutual complementary expertise nor student negative-transfer effects were established. The additional A repair collection has the same absence of complementary recovery and is not a future independent holdout.

## Exact outstanding evidence before wider E3 use

1. Bind the local `cedf…` GGUF to a specific upstream repository, immutable revision, exact filename/bytes and converter/quantizer lineage with original download receipts; a similar filename or inherited model card does not suffice.
2. Preserve the actual applicable upstream and intermediate license/notice bytes and record the precise proposed product/recipient/use. Resolve any commercial service/AI-work-assistant authorization using the applicable terms, not the derivative card's Apache metadata.
3. Obtain a genuinely distinct, authorized teacher and compare on independently held tasks with matched tools, information, inference/verification and *measured physical compute*. Test the trained student's transfer and negative transfer, not merely oracle-union answers.
4. Do not reclassify public GitHub maintainer lineages as authenticated E5 users, the exposed B/B2 panels as independent confirmation, or mechanical E6 `ADOPTED` as native acceptance.

**Gate remains HOLD_NO_GO.** No PR merges, production activation, external communication or other executors' worktrees are authorized by this note.
