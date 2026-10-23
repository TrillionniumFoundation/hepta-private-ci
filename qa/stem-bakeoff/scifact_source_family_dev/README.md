# SciFact source-family retrieval diagnostic — historical, negative result

This isolated QA directory is not wired into the Memory A–I qualification gate.
It changes neither that protocol nor its two-phase training/seal boundary. No
Reader, learned Head, model weights, future cohort, or independent scientific
superiority is supplied here. The graph is a typed **lexical incidence** graph,
not a trained or entity-grounded GraphRAG implementation.

## Actual execution and denominators

The original publisher's pinned bytes provide 5,183 abstract documents and
1,109 labeled historical claims (809 official train + 300 official dev). We
repartition those known public claims; this is not the official hidden test set.
The source-paper/cited-paper/exact-normalized-claim connected components total
568 observed families. Exact source-paper mapping is missing for 373 claims;
quarantining every component containing one excludes **412 claims / 194 families**.
We do not replace these cases or approximate matching to increase the count.

The frozen hash split leaves development 548 claims / 295 families and heldout
**149 claims / 79 observed families**. Of the heldout claims, **82 claims / 49
families** have annotated evidence and form the metrics below. The other 67
claims have no annotated evidence and remain unknown, not false or successful
abstentions. Unobserved shared-study/lab/pretraining ancestry is still unknown.

| Frozen arm | Any gold document @5, /82 | Complete rationale in delivered context, /82 |
| --- | ---: | ---: |
| BM25 | 69/82 = 84.15% | 67/82 = 81.71% |
| BM25 + title graph RRF | 30/82 = 36.59% | 23/82 = 28.05% |
| BM25 + title/abstract graph RRF | 41/82 = 50.00% | 31/82 = 37.80% |
| BM25 + permuted title/abstract graph RRF | 62/82 = 75.61% | 48/82 = 58.54% |

**All three frozen graph variants were worse than BM25.** Preserve these results;
do not retune fusion or sample selection after viewing this heldout outcome.
The full report also retains all-gold-document recall, @10, family-macro values
and paired positive/negative/unchanged family counts, without significance claims.
Answer accuracy is `null`: retrieving a document is not returning a correct
answer. A complete rationale means all annotated sentence IDs from at least one
alternative set survived the same query-only sentence packer and 4,096 UTF-8-byte
budget, not that an answer model used them correctly.

The first actual CPU run took 3.16 process seconds with 161,292 KiB peak RSS on
Linux. It processed all 149 queries for all four arms. Its 149 prediction rows
were byte-identical in a second deterministic execution. This is one experiment
plus a replay, not two independent replications. Four behavioral tests passed;
synthetic test success is not evidence of scientific performance.

## Freeze and provenance

`protocol.json` SHA256 is
`d93d962b849ce225962db8f27f077e0cc979e34ab83db118a6bdac423d89cebe`.
It was written before acquisition. `evidence/original-material-seal.json` binds
the data/projections and executed sources before the first retrieval run. Its
hash is `df3d0aba579063bb60b46a41ad457974da6732a8ed6f1ffb23e4258c2773a89e`.
This local historical development freeze is not an authenticated prospective
pre-registration. `retrieve.py`, `prepare.py`, `score.py` and the tests preserve
the executed source bytes; `acquire.py` and `seal.py` are explicit replay helpers.

The first acquisition successfully hashed the citance response but failed to
parse the upstream-documented `claims[].claim_text`; actual data uses `text`.
The response body had been discarded, so a separately recorded recovery made
one same-URL If-Match read and confirmed identical bytes. Three cumulative GETs
read 11,222,291 bytes. The original failure was not rewritten as success. The
replay helper uses the actual schema and needs only the two original resources.

## Reproduce (Linux, Python 3.12+, standard library only)

Use ordinary **non-optimized Python**: do not pass `-O`/`-OO` or set
`PYTHONOPTIMIZE`. These historical development scripts use Python `assert` for
some hash, seal, shape and census checks; optimization disables those checks.
The recorded hashes/artifacts come from a trusted local freeze. This package is
not a tamper-resistant, adversarially safe fail-closed auditor, and its assertions
or local material seal do not establish a security or authentication boundary.
The already executed core sources and original seal are retained unchanged.

No command downloads a model or invokes an upstream script. Only the explicit
acquisition command uses the network, at most two responses of 8 MiB each.
Run in a fresh local directory so exclusive outputs cannot replace evidence:

```bash
cd qa/stem-bakeoff/scifact_source_family_dev
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py' -v
python3 acquire.py       # explicit official data download; no retries
python3 prepare.py       # source custodian partition/projection, not worker
python3 seal.py          # fresh local material hashes before retrieval
python3 retrieve.py --corpus local-data/corpus.jsonl \
  --queries prepared/worker-queries.jsonl --output run1
python3 score.py run1    # separate post-prediction gold-owning process
python3 retrieve.py --corpus local-data/corpus.jsonl \
  --queries prepared/worker-queries.jsonl --output replay1
cmp run1/predictions.jsonl replay1/predictions.jsonl
```

The worker reads only the corpus and `{id, claim}` query projection; no gold,
cited-document IDs or source-family mapping is passed to it. This is auditable
process/data separation, not a claim of an independent human custodian or OS
security isolation. The original predictions SHA256 is
`321c9343e3fefccd674e1115b7dfd9e1e9df44f37361ddd3261806789c81a47d`.

Do not commit `local-data`, `prepared`, run outputs, gold, abstracts or citation
paragraphs. Published evidence contains only hashes, counts and aggregate metrics.
See `ATTRIBUTION.md` and `evidence/source-manifest.json` for official revision,
licenses, mutable-download-URL limitations, response hashes and content-rights
boundaries. These diagnostics do not constitute medical advice.
