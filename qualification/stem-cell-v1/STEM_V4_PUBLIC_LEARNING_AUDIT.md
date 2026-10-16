# V4 — independent original-source adjudication of real pretrained Cell learning

**Research only · DRAFT · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO · no main merge, no FinalUse, no model promotion.**

## Original evidence sources

- Fixed completed genuine public ModernBERT shared-Encoder / BANKING77 four-intent learning job: GitHub Actions [38523539731](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38523539731), artifact ID **11877613315**.
- Original outer artifact ZIP SHA-256 **fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a**.
- Original publisher: PolyAI-LDN/task-specific-datasets commit **57ec275d8078af65b7731c2a98be812d844a6d6b**, 64 fixed fit / 32 heldout samples, four fixed intents (NOT all 77 BANKING77 classes), CC-BY-4.0, Casanueva et al. (2020).
- Exact SHA-256 train **b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b**; test **d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d**.

## Independent physical data lineage

The exact publisher train/test files were independently fetched through GitHub and hashed; the original 64 fit + 32 heldout IDs were **recomputed from original normalized text** using the registered salted content-hash selection and publisher category, with fit heldout separation and duplicate/overlap elimination. The SHA256 of the complete selected ID arrays matched original evidence:

- fit ID array **2919d3f35bfc274f7dfee1adcccf7a0992fbc1a4566ef221464b196d6c2bf683**
- heldout ID array **33bfdba7bdfe5a3fad0d591b0a0899bbf2e6796a71b04ccc51bc0408022ac925**

This exact source result was computed in the independent analysis process. The submitted V4 **read-only Actions job repeats it itself** from original pinned public CSVs, not from the producer selection assertions, *after* reopening the original archived predictions.

\`banking77_independent_v4.py\` does **not** import the original pretrained producer, training or scoring packages, Torch or transformers. It independently checks the exact 18-member Actions ZIP, full artifact SHA, original complete prediction byte seals, independent model weight file SHA, archived terminal/run/Encoder digests, the publisher sample ID set and correct class labels, and rejects any source or model/forecast identity drift, extra forecast field or duplicate. It recomputes accuracy, per-intent accuracy, multiclass Brier, mean NLL and paired exact McNemar from all 32 original sealed logits per arm. Missing original publisher bytes cause the CLI to **fail closed**. The internal archive-only recount helper does **not** claim independently authenticated source bytes, even if its arithmetical scores agree.

No raw original utterances, model tensor bytes, raw publisher labels or original full predictions are committed in Git. CI uploads a sanitized independent report only.

## Actually observed post-seal real-model arithmetic

From the byte-pinned **actual original trained** 16-Cell dense and 16-Cell top-2 sparse model archives, independently recomputed:

| Arm | Correct before | Correct after | Brier after | NLL after |
| --- | ---: | ---: | ---: | ---: |
| Dense16 | 8/32 (25.0%) | 23/32 (71.875%) | 0.3820432498685225 | 0.6915541568258448 |
| Sparse16 Top-2 | 9/32 (28.125%) | 17/32 (53.125%) | 0.5770228329211649 | 1.0150894535640618 |

Paired exact McNemar double-sided descriptive p values:
- Dense16 before→after: 1 old-only vs 16 new-only, **p=0.000274658203125**.
- Sparse16 Top-2 before→after: 8 old-only vs 16 new-only, **p=0.15158963203430176**.
- Dense16 after vs Sparse16 after: 10 dense-only vs 4 sparse-only, **p=0.1795654296875**.

These are after-the-fact tests on a **small 32-case historic same-dataset panel**. They do not establish multiple-comparison-adjusted candidate superiority, independent prospective source families, pretrained contamination exclusion, cost-matched dense/sparse comparability, independent signed human ground truth, generalizable reasoning or actual 421M replacement. The **real-model result is a 16-Cell public text canary**, not a 4096-Cell learning claim. The newer V3 4096-Cell fleet contains **untrained int16 parameter Heads** and is a distinct physical-cost mechanism.

## Tested mechanism and exact-HEAD CI

Five local source/adversarial test methods passed in Python 3.13 ordinary and \`python -O\` modes. They cover source original byte changes, deterministic source selection/label reconstruction, unsafe/duplicate ZIP entries, duplicate/NaN predictions, tampered original sealed logits and exact paired comparison. One local test uses the actual original archive mounted on the isolated analysis host and explicitly leaves \`source_bytes_independently_verified=false\` without original raw source bytes. A missing historical ZIP in ordinary source-only CI causes that optional case to skip, **not** a real evidence PASS; the separately required physical original-source job must finish on its own exact PR HEAD.

The GitHub CI review workflow fetches original artifact from GitHub Actions with read-only token; obtains immutable publisher CSVs without credentials; checks entire bytes against original publisher digests; produces only CREATE-ONCE sanitized report; and **never grants** model selection, deployment, split, NDU/System2 or FinalUse.

## Further real learning experiment — still blocked

Next candidate must train a 384D/4096-Cell gated real-data setup against: frozen Head, matched parameter count dense and sparse, actual pretrained frozen Encoder baseline, replicated 421M and *shared* 421M alternatives, source-disjoint future temporal windows, full training/inference/retention/migration costs, loss of old-task success and independent evaluator. No new claim is justified until the physical experiment has completed with original evidence and matched controls.
