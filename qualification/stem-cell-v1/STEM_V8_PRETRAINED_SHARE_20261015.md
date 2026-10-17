# V8 real archived pretrained Encoder sharing with 64–4096 private Cells

**DRAFT / SHADOW_ONLY / DENY_ALL — scientific resource mechanism, not a new Stem winner, human task result or production admission.**

Parent: V7 PR #2364, head `ae320aaf80227ca399c6dde422097fbd62da8d57`. Additive research-only files; no change to V5/V6 fixed source, Rust Worker, CAS/CNS, training owner, Reader, FinalUse, NDU or main.

## Original source/model provenance

Reused the authentic archived GitHub Actions artifact **11586991191** (ZIP SHA-256 `07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af`). Verified and locally unpacked only the original six-layer MiniLM Encoder BF16 safetensors (`53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db`), original WordPiece vocab/tokenizer/config, and original published LoCoMo corpus. Full SHA values are pinned in `stem_v8_pretrained_share.py`; original encoder model commit `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` is recovered from the archived Hugging Face metadata. The experiment **does not** use Granite97, mmBERT, EmbeddingGemma2 or the unidentified 421M checkpoint and cannot rank them.

Model receives **genuine archived public dialogue turns**, not synthetic feature vectors. Model source text (and published publisher-answer fields in the original archive) never enters Git tree or uploaded experiment receipts. The `source_only_records` selection accesses only `conversation` and source identifiers after parsing the full original corpus; this **is not an isolated external label-owner sandbox**, nor proof that a third-party model loader could not inspect other files. No model answer generation or independent human correctness scoring occurs.

The six-layer BERT forward uses the exact original archived BF16 model tensors converted to FP32 for a manually written reference operator path; a local lowercased WordPiece candidate performs **no silent token truncation**. The independent original numerical probe implementation and the new Encoder implementation generated identical FP32 CLS/pooler bytes **inside this environment**, but both differ from the numeric SHA published by the previous isolated host. That discrepancy is preserved in every receipt: `archived_cross_host_reference_exact=false`. The experiment **does not** establish official HF `transformers`/`tokenizers` parity or cross-host bitwise reproducibility; model weight byte integrity is independently verified.

## The physical causal contrast

Hold fixed one actual pretrained Encoder, exact original input bytes, all active Cell Head weights, FP32 arithmetic, and one frozen source inventory. Repeat each scenario twice. 32 of N private Heads are active per dispatch. Every Cell owns a separate physical 384→8→384 gated residual Head with exactly **6,914** FP32 scalars. The baseline invokes the actual six-layer Encoder once **per Cell**. The shared arm invokes it once per complete `cache_identity` (the original V7 principal/purpose/epoch/generation/model/tokenizer/preprocess/modality/input material binding) and reuses the identical vector across matching Cell Heads. Both physical paths calculate original predictions; `torch.equal()` checks all 32 outputs, never just semantic parity or mocked counters. Full input/output material counts and costs are recorded, and each source combination is SHA-first.

| Scenario, 32 active Cells | Distinct full identities | Baseline physical forwards over 2 repeats | Shared physical forwards | Result |
| --- | ---: | ---: | ---: | --- |
| Identical public source + authority | 1 | 64 | 2 | 32/32 outputs byte-identical each repeat |
| Four original public sources | 4 | 64 | 8 | same |
| 32 distinct source texts | 32 | 64 | 64 | same; no savings |
| Same source, 32 principals | 32 | 64 | 64 | same; deliberately **no cross-principal reuse** |
| Personalized per-Cell Encoder prefix | 32 | 64 | 64 | same; no savings |

With the independent six-token numerical anchor, each complete N-cell research process performs **523 real pretrained Encoder forwards** (this is a genuine observed function-invocation count in source; not a hardware trace or independently signed model-host attestation). A fresh process loaded a real single Encoder and N physically allocated private Heads at each N; there was **no** N-way concurrent Encoder serving or N-model residency. The raw LoCoMo source text, raw tensor outputs and full model weights remain local only. The committed JSON contains source/weight/tensor digests, full two-sample measured timing arrays and negative-claim flags; no original dialogues or target answers.

## Actual four isolated CPU results

| Resident Cell Head count | Physical trainable Head scalars (not trained) | Observed process RSS after model/Heads (MiB) | Encoder physical forwards |
| ---: | ---: | ---: | ---: |
| 64 | 442,496 | 311.7 | 523 |
| 256 | 1,769,984 | 318.4 | 523 |
| 1,024 | 7,079,936 | 345.7 | 523 |
| 4,096 | 28,319,744 | 423.8 | 523 |

The RSS values are physical *whole-process* measurements, not just model tensor footprints, and cannot be compared to the earlier V7 *Head-only* RSS as if environments/work were equal. Only two timing repetitions per scenario were collected; the reported descriptive `p95` is effectively a near-maximum order statistic and **is not a p95 SLA or stable throughput estimate**. FP32 CPU, one Torch thread; no GPU/energy measurements. The measured large reuse benefit applies to *actual identical bounded input identities*, not to arbitrary differently conditioned Cell requests. This is one-source-dispatch end-to-end through a pretrained Encoder and Head only; it excludes Reader decoding, training/optimizer memory, WAL, power failure and any inference executor FinalUse.

## Regression and fail-closed scientific gates

- 16 standard library unit cases: 15 source/contract checks always run; one optional original material test runs **only** with `HEPTA_V8_REAL_ROOT` explicitly set. Synthetic receipt fixtures are for input rejection tests and cannot be promoted to model evidence. Tests reject forged model/authority flags, missing case/scenario rows, mismatched training Head count, fake forward conservation, reuse across principals, altered tensor identities, nonfinite timings and fake output SHA fields.
- The genuine material-positive test reopens *original* MiniLM tensors, reruns an independent original-reference numeric BERT, and checks that all 10 original source families are present. A true original four-size run additionally validates SHA/material/cost counters and bitwise physical predictions for all five input-identity regimes.
- Hosted read-only CI must run on the **exact new HEAD**, including separate model archive download/verification (if available), before hosted model execution can be claimed. An Actions job queued or cancelled is not a pass. Independent model-host signing and official HF numerical/tokenizer parity remain unverified.

**Scientific disposition:** Physical pretrained feature sharing for identical authority-bound input is demonstrated in this isolated CPU test. This does **not** establish trained Cell learning improvements, optimal Stem selection, multimodal understanding or V6's required stable retention. All production, automatic Cell split/fusion, main merge, NDU/System2 admission and FinalUse remain **DENY_ALL**.
