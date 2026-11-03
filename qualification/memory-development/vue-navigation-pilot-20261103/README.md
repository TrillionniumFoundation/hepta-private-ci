# Navigation pilot: sanitized code and aggregate result

This package contains a **sanitized post-run derivative**, invented toy tests, a protocol template, and aggregate results from one frozen single-source development pilot. The result is **REJECT**. The candidate did not meet the required gain over each control.

It does not contain the original corpus, real questions or gold, per-task outputs or identifiers, selected source paths, source revision, original input/component fingerprints, model weights, or private run records. It is not a byte-identical copy of the original execution artifact. Running the toys checks engineering behavior; it does not reproduce the private pilot result or its timing.

## Run the synthetic checks

Requirements: Linux and Python 3.12, standard library only. The original engineering checks used Python 3.12.14. Built-in floating-point `sum` behavior matters for near-tie ranking; cross-interpreter bitwise equivalence is not claimed. No dependency installation, model service, credentials, or network is needed.

From this directory:

```sh
export PYTHONDONTWRITEBYTECODE=1
python -m unittest discover -s tests -v
WORK=$(mktemp -d)
python freeze.py --output "$WORK/code-freeze.json"
python toy_fixture.py --output "$WORK/toy" --freeze "$WORK/code-freeze.json"
python runner.py --manifest "$WORK/toy/manifest.json" \
  --queries "$WORK/toy/queries.json" \
  --authorization "$WORK/toy/authorization.json" \
  --freeze "$WORK/code-freeze.json" --output "$WORK/run"
```

The generated fixture is wholly invented. Its all-zero revision and example repository are placeholders, not source pins. The five-arm runner should report `execution_status: SUCCESS` and `efficacy_status: NOT_SCORED`. Synthetic scorer and decision-rule checks are in the unit tests. Every output path must be new; prior results are not overwritten. Keep generated outputs outside this package.

`freeze.py` records this derivative's own explicit code/config/template/test inventory. Those newly generated digests are not the original run's seals. The authorization record is an audit attestation, not an access-control boundary or user permission. The package neither obtains source data nor authorizes a real evaluation.

## Files

- `raw_markdown.py`: bounded raw Markdown parser, source locator, adapter and primary packing helper.
- `retrieval.py`: BM25, fixed PRF, query-ranked links, hash-ranked links, and separate top8 diagnostic.
- `scoring.py`: reviewed-span checks, full-pack verification, complete-support scoring and fixed decision rule.
- `runner.py`, `freeze.py`, `toy_fixture.py`, `CONFIG.json`: fresh-process runner and synthetic setup.
- `PROTOCOL.template.json`: a post-run sanitized template retaining the actual numeric screen thresholds. It is not a new preregistration.
- `tests/`: self-contained invented parser, retrieval, scorer, timing-boundary, failure and aggregate-arithmetic checks.
- `RESULTS.json`, `RESULTS.md`: genuine aggregate negative results and measured costs from the original frozen run, not measurements of this export.

## Fixed mechanics

All four primary arms share canonical raw sections and a four-whole-parent, 8,192-UTF-8-byte cap. Payloads are exactly citation, newline, title, newline, original section text, newline. Oversized parents are skipped; text is never truncated. BM25 top8 has eight parents under the same byte cap and is diagnostic only.

BM25 uses lowercase ASCII alphanumeric tokens, k1=1.2 and b=0.75, sorted unique query terms, built-in `sum`, and ascending parent-ID ties. PRF uses two seeds and four collection-IDF-weighted terms of at least three characters, with lexical ties. Candidate links start with two BM25 seeds, rank up to two explicit same-source linked targets using local BM25 over visible labels plus target titles, then fill in base BM25 order. Hash links changes target ranking to SHA256(target ID), then ID. Non-link arms do not scan link fields or build the graph.

The parser retains exact contiguous raw spans around column-zero ATX headings outside fences. Only explicit anchors are matched. Dynamic-looking input is inert; it is not rendered or executed. The locator maps a leading slash under `src/`, resolves relative paths without escaping that root, changes exact `.html` to `.md`, and adds `.md` to an extensionless leaf. It never guesses directory indexes, rendered routes, implicit slugs, alternate casing, external targets or missing manifest entries. These locator rules are unchanged from the frozen code.

Bounds are 32 manifest entries from one source, 131,072 bytes, 8,192 lines and 1,024 sections per document. Invalid or over-limit documents reject wholly. The loader returns bytes before the parser checks their size; this is not a streaming allocation guarantee, filesystem sandbox or network fetcher. See the code and synthetic boundary tests for conservative syntax handling.

## Changes made for this export

1. Removed the real source revision constant. Added a citation-repository parameter with `example/synthetic-docs` as its default. Citation URL shape, parent-identity formula and source-locator algorithm remain the same. Repository changes alter citation bytes and can change byte-cap packing, so this derivative is not an exact original-run replay.
2. Flattened the private directory layout; changed the freeze schema/inventory to include only this package. Rebuilt the original protocol as an explicitly post-run template without selection metadata or custody fingerprints.
3. Replaced an unavailable historical reference-module import with a newly written direct BM25 test oracle. Retained self-contained synthetic parser tests, omitted fixture-file-dependent historical tests, and added replacement synthetic parser and release checks. This is a new derivative test suite, not a claim to redistribute the complete original review evidence.
4. Removed the original canonical representation fingerprint from aggregate results and review timestamps from the cost export. Counts, rates, paired counts, strata, decision, measured durations, CPU/RSS and other aggregate costs are unchanged.
5. Reworded descriptive headers and public version labels. Retrieval/scoring logic and the cold/ACK/warm measurement boundary are retained. No toy duration is a remeasurement of the original corpus.

## Measurement and evidence limits

Original cold time is parent-before-spawn to parent receipt of a durable cold-output event. It includes process startup, source reading/parsing, graph work only for link arms, indexing, queries, packing and output writing. The child waits for parent acknowledgement before three warm repeats. Failures retain status and charged work; timeout is not a successful runtime. One fresh process per arm on a shared host is not a cold OS-cache benchmark or a dedicated-hardware performance estimate.

The original run had operationally separated author/reviewer roles with model exposure. They were within the same account, not human or externally independent reviewers. Public-model familiarity with the documentation cannot be excluded. The task set comprises authored developer scenarios, not observed user query logs. A subsequent arithmetic/custody check did not re-review semantic gold or remeasure hardware. This release does not establish external custody, semantic truth, generated-answer correctness, statistical generalization, or cross-source confirmation.

The public aggregates do not make the withheld task-level result independently recomputable. Tests can verify published arithmetic and mechanics. Full corpus-level reproduction needs separately authorized private inputs and the original frozen artifacts.

## Failure and repair history

A first acquisition attempt ended in a transport error with unknown HTTP status, zero received/stored bytes and no admitted files. The precise cause and remote receipt were not established. A separately authorized bounded recovery retained the same selection and pins without replacement; it restored the standard environment-managed opener, not a different proxy, credential or disabled TLS. Original failure records remain retained outside this package. Acquisition and rights-review totals are not measured by the retrieval runner and are not invented here.

Before real-result inspection, engineering tests exposed and corrected short-write/raw-destination handling, nested-target syntax, missing canonical-adapter evidence binding, incomplete freeze acceptance, floating-point summation near ties, loader errors hidden as document rejection, cold/warm acknowledgement overlap and pipe buffering deadlock, diagnostic-arm veto of the primary gate, and invalid obligation/runtime values. Failed and superseded records were preserved. No performance-driven tuning is claimed. The later authorized retrieval suite and scoring ran once without repair/retry after result exposure.

## Source attribution and permissions

The real pilot used non-image text from [Vue documentation](https://github.com/vuejs/docs), attributed to Yuxi (Evan) You and Vue documentation contributors under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), subject to full-file exception review. Four of 32 planned files were excluded by that review; two planned task anchors were consequently excluded, with no replacements. No source text or images are redistributed here.

The source documentation's license does not license this package's code. This package adds no new code license or copyright grant. Preparation of this local candidate does not authorize publication, merging or deployment.
