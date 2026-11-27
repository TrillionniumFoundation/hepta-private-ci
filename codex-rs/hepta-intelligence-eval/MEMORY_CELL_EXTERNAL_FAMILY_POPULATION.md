# MemoryCell — precommit external native source-family population

**Research-only source admission for PR #1452.** The completed Qwen development study at exact generating commit `c24fad24b65984a6255a8854c6714c141911ff79` already measured 40 calibration and 72 nine-arm answers. Independent read-only replay succeeded; the whole workflow remained red because the separate PR-wide format job failed. On those eight *authored and already exposed* evaluation questions, the correction-aware organizer gave **0/8 incremental correct answers** and **0/8 additional fully cited program-declared source chains** relative to the simpler full-path entity/time control; it only saved 573 prompt tokens. This is a **NO-GO** for promoting graph/parametric memory from that census. Do not train longer to reverse an already-observed result.

## New data gate rather than reusing the eight tasks

`external_family_population.py` stages **published external LoCoMo and LongMemEval inputs**, not generated events. It checks the already-registered byte SHA-256 values before constructing any population. `native.load` preserves original source text and dates, quarantines malformed input, and connects repeated LongMemEval session roots to a common source-family proxy. The new population precommitter projects only `documents`, `questions`, and `families` — **not native answer/target objects** — into an opaque deterministic source-family split. Each dataset must expose at least ten non-overlapping root-family groups, and a document root crossing train/selection/evaluation (or crossing corpora) fails closed.

The split is the hashed 60% training / 20% selection / remainder evaluation assignment of **source-family proxies**. Within each family, questions are selected by a fixed SHA order with a maximum of eight per family, round-robin across datasets, with budgets of 128/64/64 questions per split. This ordering is independent of answer content; changing labels does not change the public population SHA. The artifact includes question identities, text, time, original source IDs and source-byte census hashes, but not gold answers, support-annotation IDs, or unanswerability labels. Original source text remains at the source dataset pinned digest and must be fetched or revalidated at generation time.

The driver fsyncs `public/population.json` **before invoking the target supplier**, and then writes `targets/targets.json` to a separate artifact. Its `sealed-manifest.json` records both exact SHA-256 digests and the complete question census; an incomplete or nonmatching target set is a hard error. The separate public artifact is the only one that may be supplied to a future frozen-reader generator, while target bytes are kept out of that job and accessed by a different scorer *after* all raw model outputs are immutable.

The scope is **a candidate external published benchmark population**, not a prospective source observation, a human-verified independent family, or evidence of production authorization. Source-family names/root hashes are leakage **proxies**; dataset publication does not prove family independence, semantic entailment, absence of pretraining contamination, or observation freshness. In particular, this source-only step performs **zero** pretrained model calls and cannot by itself promote any head, Cell, or organizer.

## Reproducible source-only execution

The opt-in workflow `.github/workflows/hepta-memory-external-family-population.yml` downloads only the two published corpora, never pretrained model weights. It uses immutable upstream revisions and both exact source SHA-256 checks, runs the Python regression tests before staging and then publishes **three distinct artifacts**: public inputs, targets, and the separate seal. It does not automatically download target artifacts into any reader run or activate the serving path. A failure to preserve the corpus or minimum source-family census **rejects** the preregistration rather than selecting a convenient subset post hoc.

From an environment with both already-pinned benchmark files:

```bash
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_external_family_population.py' -v
PYTHONPATH=scripts/memory_cell python3 scripts/memory_cell/external_family_population.py \
  /path/pinned/locomo.json /path/pinned/longmemeval.json /tmp/fresh-population \
  --source-commit EXACT_40_HEX_SOURCE_SHA
```

**Next actual reader stage, contingent on successful preregistration:** freeze the same reader identity, prompt policy, question and evidence/token budget; run calibrated strong hybrid RAG and a simple entity/time/relationship filter on the published evaluation families; journal answers before opening the target artifact; measure task success **and** full citation chain, token/cpu/wall cost, failure denominator, cluster-level uncertainty and source-family overlap. Explicitly quarantine unresolvable native histories. No graph or learned candidate is qualified unless it outperforms the **strongest valid simple control** on previously unseen source groups and an independently reviewed population; retrospective benchmark outcomes are not actual future production windows.

Production remains **NOT QUALIFIED**: independent semantic citation adjudication, valid real future windows, source custody/consent, lifecycle ingest/retention/revocation/recovery costs, rollback and current PR-wide CI acceptance remain outstanding.

## Recorded external family-capacity failure, not a relaxed experiment

The pinned source-only workflow at `623cb20ed4baaa6147488bd80ac127c7b337366c`
completed its synthetic source-cut regressions but **rejected the actual
published population** with `fewer than ten family-disjoint published
groups`. The code must not fix this by relabelling different questions
on a shared native source family as statistically independent families.

`source_only_family_capacity()` now computes actual per-dataset original
native family-proxy counts and the 60/20/remainder split capacities. It
does not consult `Target` objects, model outputs or gold source judgments.
`preflight_and_prepare()` saves a deterministic
`<population-output>-capacity.json` *before* the hard failure, containing
original source hashes, group counts, shortfall to the fixed **ten-family
threshold**, explicit independent-review exclusions, and
`production_accepted=false`. A blocked population leaves no public
or private target directory. The existing ten-family guard, root-overlap
checks, immutable SHA pins and downstream split budgets are unchanged.

The GitHub Actions job will still correctly **fail** when the public native
sources lack enough independent proxy groups, but now uploads a separate
negative capacity artifact even on failure. This is useful source-level
evidence of why additional **genuinely independent data** must be gathered,
not a reason to tune on exposed evaluation questions, waive sample-size
requirements, simulate source groups or claim prospective task gains.
