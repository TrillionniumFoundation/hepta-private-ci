# MemoryCell — independently replayed publisher-support Reader completion (13 October 2026)

**Research-only / NO-GO for learned Cell and production.** This checks actual
previously generated Qwen model answers, not new inference, publisher-label-blind
retrieval, an authenticated human evidence-sufficiency judgement, or new
independent future task families.

## Pinned real execution and protected score

- **GitHub Actions:** [run #38353622487](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38353622487) (`preflight`, `reader`, `score` all successful).
- **Generating source:** `2db775a9b423f5d53c2ec1cf69d4e67da02e35bd`.
- **Original publisher-support IDs, 16 cases:** artifact `11792575178`, ZIP SHA-256 `66bc69310096b0226e90a8503df9d8d29645766066bbcf6acda7fd32241fb2b0`.
- **16 original pretrained answers and full source delivery receipts:** artifact `11792880133`, ZIP SHA-256 `14dc63bfb0e25b8b15f7b48ba8e1afd4cef4d13f8617d08d28a533baa7a202a0`.
- **Separate original score job:** artifact `11792297662`, ZIP SHA-256 `cb753cd17db2b06027393175097d5a74b3fdfba459698f14d243d6ec14642698`.
- **Frozen Qwen inventory:** `f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225`; **zero trained parameters**.

The postrun verifier checks outer SHA pins, complete available member manifests,
source/plan and generation SHA bindings, 16/16 actual successful answers, the
original ordered delivered source IDs and excerpts, original reader identity,
non-postprocessing, score job lineage and the original 16 planned question IDs.
It does not open or duplicate publisher reference answer text, authenticate a
human reviewer, or change original model answers.

## What the real measurements show

| Diagnostic condition | Mean answer token-F1 | Original model calls |
| --- | ---: | ---: |
| Frozen lexical k4 | 0.172083 | 16, previously generated |
| Frozen lexical k8 | 0.111482 | 16, previously generated |
| Publisher-annotated support IDs | 0.264376 | **16 newly generated** |

These conditions use one frozen Qwen reader but the publisher-support selection
is **privileged**: it uses published support annotations that an ordinary online
retriever would not have. The relative gain over lexical k4 is **+0.092294**
F1, not proof that an admissible learned memory selector improved or that those
source annotations are independently sufficient.

- On the **five answerable questions where k4 missed publisher support**, F1
  increased from **0.024050** to **0.360525** (+0.336475).
- On the **eight answerable questions where k4 already retrieved publisher
  support**, F1 **decreased** from **0.204134** to **0.178424** (−0.025710).
- Three original explicitly unanswerable tasks had a score of **0.333333**
  under both k4 and privileged support. The new reader answered only **1/3**
  with an *exact* canonical evidence-insufficient refusal; the other two
  contained refusal plus additional unreviewed text.
- Three *answerable* tasks also mixed refusal wording with additional text.
  Thus **five of 16** actual responses contained mixed-refusal formatting;
  a string-prefix refusal alone is not certified safe abstention or entailment.
- The new privileged condition used **3,427 full prompt input tokens**, **675
  generated tokens**, and **201.529 cumulative measured inference seconds**;
  fourteen answers contained a syntactically valid, delivered `[E#]` citation.
  None of these is independent semantic citation precision or an operational
  lifecycle cost.

## Exact replay and decision

Run the self-contained source-only checker with the three downloaded originals:

```bash
python3 scripts/memory_cell/locomo_publisher_completion_receipt.py \
  locomo-publisher-ids-20261013.zip \
  locomo-publisher-raw-20261013.zip \
  locomo-publisher-diagnostic-20261013.zip \
  --output completion.json
HEPTA_LOCOMO_PUBLISHER_POSTRUN_ARCHIVES=PATH_TO_THREE_ZIPS \
  python3 -m unittest discover -s scripts/memory_cell \
  -p test_locomo_publisher_completion_receipt.py -v
```

`locomo-publisher-completion-38353622487.json` contains only aggregate
source-pinned measurements, no original reference answers, source text, private
reviews or modified model responses. The nine tests cover archive tampering,
unsafe file names, duplicate JSON, malformed refusal and the complete real
16-answer audit when all three external originals are provided.

**Disposition remains NO-GO.** The 16 LoCoMo questions form only two published
conversation-family proxies. The original model still has low answer F1 even
when supplied publisher-annotated supporting passages. Next research should
first test independent source sufficiency, simple reader-format/refusal
interventions, source-use/citation semantics and a prospective family-disjoint
validation population under fixed model/tool/cost budgets. It should **not**
interpret a privileged publisher-support intervention as a trainable MemoryCell
advantage, a 99% citation claim or permission for production deployment.
