# MemoryCell — 140 original-weight offline SmolLM2 diagnostic generations

**2026-10-16. Research only. No release, model activation, MemoryCell promotion, or production acceptance.**

## Why this exists

The hosted registered-Reader jobs under associative PR #2365 were still queued at
execution time. The repository's upstream `offline_smol_reader.OriginalSmol`
supplies a *different*, original-weight FP32/PyTorch research implementation
of the same pinned SmolLM2-135M architecture. It is **not** verified numerically
identical to `ReferenceReader` running Transformers/BF16 and is not a replacement
for that Reader. Historical fixed LoCoMo questions and annotation-selected
sources are already exposed development data, not prospective validation.

The immutable original model weights were checked against the four pinned
publisher hashes, and the complete eight-file reader inventory plus transport
manifest was separately verified against registered reader identity
`afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c`.
Full model transport size is **272,437,573 bytes**. The code now also requires
this complete `reader_weight_transport` check before another inference run,
then verifies in-memory weights remain frozen. This stronger pre/post check was
added *after* the 140 journaled observations; a separate one-query smoke run
proved the strengthened path without relabeling previous result lineage.

## Source and execution boundaries

The diagnostic consumes only the previously sealed 20-question selection.
The ordinary ranked experiment uses public source view `public.json` and
manifest, `rank/journal.json`, `rank/seal.json`. The privileged experiment
uses only Unicode V2 `plan.json`, `seal.json`; it **never** opens answers.
The original LoCoMo source and reference answer file are read in a separate
post-seal review command. Both exact journals are checksum-bound and reject
missing, extra, duplicated, retargeted or changed evidence identities.

Fixed generation: one frozen model, greedy decoding, at most 48 new tokens;
20 questions from 10 historical LoCoMo conversations. Conditions:

- Five ordinary retrieval conditions: empty evidence, BM25, RRF, question-conditioned
  Cell, RRF+Cell — exactly 100 Reader attempts.
- Two privileged diagnostic conditions: annotated evidence, annotated evidence
  minus one preregistered premise — exactly 40 Reader attempts.

The offline CPU host used PyTorch `2.10.0+cpu`, two threads. **Do not compare
latency directly with hosted CPU 2.5.1, BF16, or other hardware.** Reported
per-call generation times sum to about 82.7s (40-arm run) and 258.6s
(100-arm run), excluding model staging and end-to-end lifecycle costs.

## Observed frozen-weight results

All 140/140 requests returned nonempty decoded text. Fifteen questions had
nonempty string-valued reference answers and were token-F1 scorable; the other
five remain unscorable and in the planned denominator. These are diagnostic
string-overlap metrics, not independently adjudicated correctness.

| Reader input | Planned | Scorable | Mean token-F1 |
| --- | ---: | ---: | ---: |
| No evidence | 20 | 15 | 0.047917 |
| BM25 | 20 | 15 | 0.042409 |
| RRF | 20 | 15 | 0.060075 |
| Question-conditioned Cell | 20 | 15 | 0.049960 |
| RRF + question-conditioned Cell | 20 | 15 | 0.056619 |
| Privileged all annotated evidence | 20 | 15 | 0.133767 |
| Privileged minus one premise | 20 | 15 | 0.087914 |

On 15 scorable privileged pairs: **5 improved / 5 worsened / 5 tied** when
restoring the deleted premise, and mean token-F1 delta **+0.045853**. Of all
20 privileged questions, 12 have a single annotated source and 8 have multiple
annotated sources. Removing the only source in a one-source case tests
abstention, not multi-hop inference.

**Critical negative evidence:** all 140 generated answers omitted required
`[E1]`, `[E2]`, etc citation markers; the observable marker-delivery count is
0/140. Marker precision is **undefined when none is emitted**, not a 100%
semantic citation rate. No independent support entailment was evaluated.

BM25 delivered more complete source IDs in the underlying retrieval experiment,
but the offline Reader did not reliably use that evidence. RRF+Cell did not
outperform RRF here. Do not call this an improvement over a strong registered
RAG+Reader baseline or a validated cross-source MemoryCell benefit.

## Reproduce from PINNED inputs (not copied raw corpus)

Run from repository root with `PYTHONPATH=scripts/memory_cell`, CPU torch,
`safetensors`, `regex`, `jinja2`, `numpy`. Stage the exact registered eight
Reader files **and a self-reference-free `SHA256SUMS` transport manifest**.
Download the separately sealed public/rank and Unicode V2 plans from existing
pinned GitHub Actions artifacts and pin their hashes; do not supply `private.json`
to any model worker. Example commands (paths are your independently staged
read-only inputs, not new downloads performed implicitly):

```sh
python scripts/memory_cell/associative_offline_reader_diagnostic.py \
  run /staged/unicode-v2-plan /staged/original-reader /new/unscored-40
python scripts/memory_cell/associative_offline_ranked_reader.py \
  run /staged/public /staged/rank /staged/original-reader /new/unscored-100
# Independently, after BOTH journals are sealed:
python scripts/memory_cell/associative_offline_reader_compare.py \
  /staged/unicode-v2-plan /staged/public /staged/rank \
  /new/unscored-40 /new/unscored-100 /trusted/original-locomo.json \
  /new/aggregated-postseal-audit.json
```

The baseline logic in `offline_smol_reader.py` is reused, not forked into a
second serving/owner module. The local research attachment includes exact
journal/seal bytes and their SHA256SUMS, but **never distributes model weights
or original LoCoMo records in the GitHub commit**.

## Required next gate

(1) Verify official pinned Transformers/BF16 output and tokenizer parity on
identical inputs, retaining all differences; (2) compare a fixed reader that
can answer with complete evidence and cite sources, then attempt retrieval and
memory improvements; (3) split by actual independent source families/time;
(4) repeat with prospective data, independent semantic adjudication and all
lifecycle costs. `blocking-ci` and Architecture stay mandatory. No automatic
promotion, final use, graph emergence or source/fact authority follows.
