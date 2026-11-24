# MemoryCell: historical citation-chain failure despite correct task answers

**Status:** Independent *read-only calculation* from two completed, original
model-generation archives. This is a formal check of authored event JSON and
public query paths, **not** a human semantic-entailment review, a prospective
source population, a new reader execution, or production qualification.

## Exact inputs and reproducibility

- Original generating commit: `59f9eadd5cc919359079e04442f7343838a60057`.
- Original eight-question frozen event plan SHA-256:
  `9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897`.
- Qwen2.5-3B archived generation ZIP SHA-256:
  `831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98`.
- SmolLM2-1.7B archived generation ZIP SHA-256:
  `67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae`.
- Scored answer byte SHA-256: Qwen
  `74c37d754303e920c7fc1f4c5e694116148bead1530d22674a8138199dbd4caa`;
  Smol `3e38208ef999f9fb53c67af25a3c0d8e8fb4be9cc2f9cf501f2f59a83cb4576d`.

The checker verifies original ZIP hashes, every declared inner SHA256SUMS entry,
archive source commit, frozen source/label/question bytes, 48 genuine paired
raw/scored answers **per model**, each selected source excerpt and exact original
citation label mapping. It never regenerates an answer or silently repairs a
missing citation.

## Observed model-quality gap (eight authored test questions per arm)

| Reader and condition | Strict task correct | Correct + all program-declared sources cited | Correct + cited event path connects public question to answer |
| --- | ---: | ---: | ---: |
| Qwen · hybrid top-4 | 3/8 | 1/8 | 1/8 |
| Qwen · entity/time | **8/8** | **4/8** | **4/8** |
| Qwen · organized | **8/8** | **4/8** | **4/8** |
| Qwen · program-bound support | **8/8** | **4/8** | **4/8** |
| Qwen · one declared premise removed | 4/8 | **0/8** | **0/8** |
| Smol · hybrid top-4 | 1/8 | 0/8 | 0/8 |
| Smol · entity/time | 2/8 | 0/8 | 0/8 |
| Smol · organized | 3/8 | 0/8 | 0/8 |
| Smol · program-bound support | 3/8 | 0/8 | 0/8 |

Every displayed `x/8` value uses the original eight planned questions, never
just the subset with a citation. The empty-evidence arm was 0/8 for both readers.
The models had 48/48 successful generations apiece; there are no missing
attempts in these historical files.

Four Qwen composition/procedure answers were *task-correct* but cited only the
terminal hop (`[E2]`), omitting the preceding source establishing which
component belonged to the queried service. The four omitted first-hop sources
can be recovered from the **public query path and original event JSON** without
using final answer text to select evidence. On Smol, all three organized task
successes lacked even a citation marker; counting them as fully source-cited
would be false.

The procedure task additionally executes a constrained worker; the formal
path checker does not replace that worker or establish correct procedural
semantics. An observed path is also not a human-certified sufficient or
minimal evidence set. The explicit `supersedes` edge allows an update but the
formal path connection alone does not establish absence of contradictory or
revoked external evidence. These constraints make this a **negative source-
provenance diagnostic**, not a newly validated percentage of semantic
citation precision.

## Runtime and fail-closed checks

Implementation: `scripts/memory_cell/historical_event_citation_chain.py`.
Pure tests: `scripts/memory_cell/test_historical_event_citation_chain.py`.
Machine-readable eight-question census:
`scripts/memory_cell/data/historical-event-citation-chain-20261011.json`.

Use the historic original artifact extraction directory and ZIPs as follows:

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/historical_event_citation_chain.py ORIGINAL_DIR \
  --qwen-archive EXACT_QWEN_ARCHIVE.zip \
  --smol-archive EXACT_SMOL_ARCHIVE.zip \
  --qwen-scored-sha256 74c37d754303e920c7fc1f4c5e694116148bead1530d22674a8138199dbd4caa \
  --smol-scored-sha256 3e38208ef999f9fb53c67af25a3c0d8e8fb4be9cc2f9cf501f2f59a83cb4576d \
  --output NEW_REPORT.json
```

The same module exposes `audit_evaluation` for a later completed nine-arm
reader experiment, but **this historical commit does not rewrite the pending
nine-arm source, does not change its strict task success rubric, and does not
retroactively attach a newer verifier to an older generating commit**. An
independent, exact-source replay and future human reviewer would still be
needed for a semantic quality claim, including any proposed 99% threshold.

The separate 40-call calibration and 72-call nine-arm trial remains queued in
GitHub Actions. Its reader gain, longitudinal performance, cost of deployed
retention/revocation/recovery, any parametric-memory advantage, and production
qualification are still unverified.

## Byte-identical compact report reproduction

The full read-only CLI output above includes all 96 per-attempt case records.
The checked-in `historical-event-citation-chain-20261011.json` is instead a
**lossless-for-aggregates compact view**: it preserves each reader's task
and formal-citation totals, source pins and all correct answers with missing
program-declared citations, but deliberately omits other per-answer details.
These two file shapes should not be compared byte-for-byte directly.

Generate the full report with the command above, then reproduce the exact
published compact file by running:

```sh
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/historical_event_citation_compact.py \
  NEW_REPORT.json NEW_COMPACT_REPORT.json
sha256sum NEW_COMPACT_REPORT.json
```

Expected compact SHA-256:
`39e41b03d3bdb2a41c64b904fab4fb02ab1cd4a12d4973a04adbda11f7d71d49`
(16,301 bytes, final newline). Independently replayed from the original
Qwen/Smol ZIPs and the pinned eight-question plan. Six model-free conversion
tests check incomplete, duplicate, conflicting and falsely promoted receipts.
The converter neither revises the original citation audit nor claims a
semantic-entailment certificate, prospective outcome or production admission.

## Logical-revision correction in citation-path verification (2026-10-11)

A historical formal-path checker previously treated any cited path of matching
event attributes as active, even when the original source scope also contained
a **visible explicit `supersedes` correction** to one of those cited edges.
This could produce a false-positive "connected" formal citation from revoked
history. The read-only path check now uses cited evidence exclusively for
positive edges but consults all original, same-scope events at or before the
public query's logical revision to invalidate explicitly replaced edges.
Future revisions cannot retroactively revoke historical claims, and sources
from different scopes cannot form one accepted chain.

Three added regression tests establish obsolete-path rejection, revision-as-of
preservation and cross-scope isolation. Local source-pinned replay of both
historical model ZIPs (96 genuine answers; 42 checked manifest members) found
**zero changed per-answer formal path results** and identical historical
by-arm metrics. The fix strengthens future counterexample behavior without
rewriting original model outputs, changing task scores, human-certifying
support, claiming >=99% semantic precision, or qualifying production.
