# LoCoMo nine-arm frozen retrieval — label-separated evidence (October 12, 2026)

**Research-only negative result, not independent task accuracy or production admission.**

The original sealed published LoCoMo cohort has ten source-family proxies,
80 source-only questions split 48 train / 16 selection / 16 held-out evaluation,
and 5,882 history turns. Original code/source commit:
`fcc24ad653700ad5f47f09350cf7815242dc5de8`.

Pinned original GitHub Actions artifact IDs and ZIP SHA-256 values:

| Data | Artifact | SHA-256 |
| --- | ---: | --- |
| Public source | 11728164433 | 51e18514c68f31220f4dcd072914f6e015aa9733b6c5b4a4d4e3b14dac25ec37 |
| Six-arm unlabeled decisions | 11729394703 | 3fb1c3272314d31b42ece1c74aa0250e2ecb06c6060cb011071d4654fef6f097 |
| Selection-only labels | 11728632417 | ba8e2282034c5bb51fe319e8909e11d028619f85dfbbce5a6fff78284f9f220c |
| Evaluation-only labels | 11728856834 | d09823324003ab431301e60fbbb280e216ca03b686e178d4f36fb6d492981978 |

A separate local standard-library implementation of the registered BM25/recency
and equal-weight reciprocal-rank fusion matched all **480 of 480** original
six-arm source decisions exactly. It then generated **720** unlabeled decisions
for nine frozen retrieval arms. New decisions JSONL SHA-256:
`d3c09d944f5bfc855056d109fa0cc379a9a2dc11a3e628556af0448f8be82197`.
The three commands ran separately: generation and immutable decision write,
selection-family label scoring and policy freezing, and only then evaluation-label
scoring. A corrupted input-receipt digest was correctly rejected before selection.

| Frozen arm | Selection fully covered /10 eligible | Evaluation fully covered /13 eligible | Evaluation source bytes |
| --- | ---: | ---: | ---: |
| lexical_k2 | 1 | 4 | 4681 |
| lexical_k4 | 2 | 8 | 8636 |
| **lexical_k8** (selection winner) | **4** | **9** | 17085 |
| recent_k2 | 0 | 0 | 4776 |
| recent_k4 | 0 | 0 | 10128 |
| recent_k8 | 0 | 0 | 18936 |
| fusion_k2 | 0 | 0 | 4449 |
| fusion_k4 | 0 | 1 | 8834 |
| fusion_k8 | 1 | 3 | 17990 |

**Decision:** current equal-weight recency RRF is dominated by plain lexical
retrieval in these published cases, so do not allocate more Cell/LoRA steps
on the pretext that fusion is better. Keep lexical_k4 and lexical_k8 on the
source-byte/weak-support coverage frontier. These 13 are *document-level
publisher-annotated support* cases, not 13 independent sufficient-context
judgments or 13 correct Reader answers. Unknown/unanswerable = 3/16.

The hosted read-only workflow repeats the current nine-arm code and the original
480-decision parity check with separate selection and evaluation target downloads.
The historical published evaluation questions are now exposed; never use them
for further hyperparameter search or claim a prospective generalization gain.
Only two family proxies appear in evaluation and independent family admission is
not authenticated. Reader F1, independently reviewed entailment, total query
cost and actual production recovery remain unmeasured. Both significant
MemoryCell-over-strong-RAG improvement and production qualification remain false.