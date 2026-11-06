# MemoryCell — strict-source bottleneck gate (13 October 2026)

**Disposition: research negative / do not scale Cells / no production admission.**

This is a **read-only, exact-source** decomposition of the successful strict-as-of
six-arm matrix [GitHub Actions run 38335999452](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38335999452).
The generating source is `30bf3379c61d7140acf01113e000a100c29ff18b`,
Git tree `d42d0457f979986a194edd65173b49fa5a7d98f1`; the archived 22.6 MB
GitHub Actions ZIP (artifact `11785635178`) has SHA-256
`4d909737769b2c4ee146ec571499276dd911542d5b20b29c9adb1f5a4477a1f9`.
**236/236 internal SHA256SUMS were independently rechecked** without extraction.

## What actually finished

The protected time/withdrawal Reader policy ran **576/576 logical six-arm**
attempts across 16/32/48 checkpoints, with 0 failures. It executed
**1,499 Python regressions successfully**. The Reader had 48 successful actual
generation calls including post-policy diagnostics, with **543 cache hits**.
There were **zero emitted citation markers**, so semantic citation precision is
**undefined, not 100%**.

Count **16 unique test+transfer question identities**, not 48 repeated
checkpoint observations. Source-family independence is not independently
authenticated; the eight test questions overlap previously encountered source
families and are not an untouched future-window cohort.

## Separate the observed bottlenecks

| Strict original final checkpoint, test+transfer | Native document-level count |
| --- | ---: |
| Preregistered questions | 16 |
| Answerable per publisher native annotations | 13 |
| Publisher weak-support source absent from eligible candidate pool | **2** |
| Weak-support source present, but frozen top-1 chose a different window | **2** |
| Frozen top-1 already selected a weak-supported source | **9** |
| Native unanswerable | 3 |

Thus fixed-candidate Head reranking alone **cannot retrieve the two absent
sources**. The *maximum observed weak-document-source correction opportunity*
for reranking is two questions. These are not independently reviewed
sufficient-evidence windows; selecting one would not by itself prove a
correct Reader answer or semantic citation.

The five learned Head/Adapter arms each retained **all 16 same test+transfer
source choices, all 16 raw answer strings and all 16 delivered source excerpts**
identical to frozen. No measured source or answer gain occurred.

All **30** matched within-Head TRAIN checkpoint receipts have
**zero weak-supported training top-1 improvements**. At the final checkpoint
the four SGD readout arms' General-Cell mean weak-training loss *increased*
by about 0.17, while Temporal-Cell loss *decreased* by about 0.156. Even the
Temporally improving objective did **not** flip supported evidence top-1.
The prototype's cross-entropy is diagnostic and not an SGD objective.

The unchanged frozen Reader's observed paired token-F1 change relative to
a separately instantiated **zero-evidence copy** was about **+0.0035** on
test (with omitted/unscorable cases) and **−0.0197** on transfer.
This is a small, non-independent answer-overlap diagnostic, **not**
a verified claim that evidence reduces answer quality.

## Reproducible, negative gate

`scripts/memory_cell/stem_oct13_bottleneck_gate.py` verifies the original
ZIP outer pin and internal member manifest, the generating source/tree,
every one of 576 unique policy IDs, final-checkpoint frozen-matched
Reader/pool/answer receipts, the true positive/negative retrieval ceiling,
all 30 real Head TRAIN fit receipts, the 16 independent question-ID limit,
and the no-evidence Reader counterfactual. Its **8 synthetic tamper tests**
reject missing/duplicate policy attempts, model/prompt changes, silent source
byte substitution, source ceiling inflation, absent train receipts, and
relabeling 48 repeats as independent questions.

The companion workflow
`.github/workflows/hepta-memory-stem-oct13-bottleneck.yml` performs this
read-only audit on the exact pinned original ZIP and retains the complete
test, source and SHA256 records. Its successful audit is *not* a successful
learning experiment or authority to turn on production.

**Next intervention order:** establish independent citation/source
sufficiency, improve retrieval where weak support is absent, and evaluate the
frozen Reader with genuinely sufficient sources **before** allocating a larger
Head or Cell budget. Keep `production_accepted=false` and
`semantic_citation_precision=null`.


## Two strict-source executions: behavior identical, learned floats nonidentical

A second, independently hashed **successful** strict experiment used commit
`aa2dd9875b811292566c09b282f74d4a0bf8e7eb`,
tree `8a156b8e7684d5fdea8521152b421d686238cb47`,
Actions run [38337888398](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38337888398),
and ZIP artifact `11787116091` (SHA-256
`b4169dc496e5c6097fdfc41c082f123eb325c28e5d7b68485b1801ede1e0726c`).
Both independently pass **236/236** internal SHA256SUMS checks.
The six core Stem executable sources are byte-identical across these runs;
the intervening repository commits changed unrelated research files.

Across **all 576 logical policy outputs**, top-1 selection,
Reader supplied evidence, raw answer text, model/prompt identity, actual
input/output token hashes and canonical request hashes are unchanged.
That is **behavioral repeatability on the SAME question cohort**, not 576
fresh independent subjects and not learned superiority.

The persisted numerical state is **not bitwise repeatable**: of **341,064**
Head tensor scalars inspected, **123,748** differ, with maximum absolute
difference **7.62939453125e-6**. All **three** Adapter safetensors binaries
also differ. The per-run feature digests differ in 576 rows and the
persisted Head SHA-256 differs on 480 learned-arm rows. This minute
floating-point variation leaves the measured source/Reader decisions unchanged,
but **must not** be misrepresented as byte-identical model training.

The source-pinned gate now reads both exact artifact ZIPs and checks original
code bytes and model/Reader receipts. It explicitly distinguishes this
limited behavioral repeatability from missing bitwise training reproducibility,
independent task generalization, semantic citations, or production acceptance.
