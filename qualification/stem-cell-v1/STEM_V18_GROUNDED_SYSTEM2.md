# V18: source-grounded NDU utility is not raw answer accuracy

**DRAFT · RESEARCH ONLY · SHADOW_ONLY · DENY_ALL · HOLD_NO_GO.**
Stacked on V17 PR #2416. The exact grounded V14.1 scorer and its regression
suite are selectively imported from the V14 head `50ad357e3476cdf3cdd4f583279538fe518bc34e`
(two byte-identical Git blobs), without merging unrelated Stem/Cell runtime branches.
No existing Rust production model/Neuron/NDU/Control/CNS/CAS/FinalUse path is changed.

## Reproduced measurement gap

V14.1 distinguishes externally judged `correct` from **grounded correct**:
`correct AND citations_entailed AND cited_evidence_ids nonempty AND not abstained`.
V16, however, compared NDU utility and root calibration using raw correctness.
This can credit an answer that happens to be right without any supported
citation, and label the resulting measured-cost tradeoff as an NDU gain.
Neither correct-looking text nor two matching digest strings authenticates a
Reader, the source content, or the external semantic evaluator.

V18 **does not overwrite raw metrics**. It adds separately named source-grounded
outcome and linear net-utility summaries. A synthetic regression shows one
correct NDU terminal with no supported citation loses its positive task reward
while still paying its registered actual CPU/token cost.

## The three immutable stages

1. **Before any model invocation or label:** V14 plan + V15 study + V16 seal
   specify exact objective/model/source scope. A NEW source-roster JSON lists
   each case's admitted `{evidence_id: sha256(actual_source_bytes)}` catalog,
   each registered model-request node, and the exact evidence IDs that node
   will receive. All V15 node requests must match their original input SHA;
   V18 root evidence must equal the V14 sufficient arm in the same order.
   `freeze` validates the strict roster and outputs a source-first digest-bound
   non-authorizing seal. The source catalog contains no label/gold answer,
   derived task correctness or private passage text.
2. **External real inference, outside this scorer:** retain original unredacted
   model inputs, prompt bytes, model-owner/load/execution receipts and resource
   counters under appropriate scope, without publishing them into the Git tree.
   A separate CITATION INVENTORY must be created and sealed **before** outcomes
   are opened. It binds every `(case, policy)` to the exact V15 original
   terminal request SHA, actual answer SHA, cited source IDs and abstention.
   The identical frozen Reader request MUST have identical citation/abstention
   data across policies; V15 STOP must match V14 original Reader citations.
   Every cited ID must have been delivered to that terminal node and belong
   to the frozen case-local source roster.
3. **Only after complete predictions are sealed:** the existing V14/V15/V16
   independent-judgment interfaces are verified. V18 computes
   `raw_correct`, `grounded_correct`, `unsupported_raw_correct` and two separate
   complete observed-cost net utility measurements. Claiming citation
   entailment with no cited source or with abstention fails closed. All net
   utility changes are paired by case and grouped by claimed source family.
   V18 verifies grounded V15 STOP totals equal the exact V14.1 grounded score.
   Missing, duplicated, extra or altered original records/labels/sources reject.

### Source roster schema (illustrative names; NOT genuine original evidence)

```json
{
  "schema": "hepta.stem.v18.grounded-ndu-utility.v1.source-roster",
  "source_only": true,
  "frozen_before_predictions": true,
  "production_authorized": false,
  "v14_plan_sha256": "<SHA-256 of canonical JSON plan>",
  "v15_study_sha256": "<SHA-256 of canonical JSON study>",
  "cases": [{
    "case_id": "case-1",
    "sources": {"evidence-1": "<SHA-256 of original passage bytes>"},
    "nodes": [{
      "node_id": "root",
      "request_sha256": "<SHA-256 of exact full model request>",
      "delivered_evidence_ids": ["evidence-1"]
    }]
  }]
}
```

This is a *shape example*, not a valid cryptographic fixture (placeholders
must be real lowercase SHA-256 digests and the V15 tree must be complete).
See `test_v18_grounded_utility.py` for executable synthetic schemas.

### Reproduction from separately authenticated PRIVATE artifacts

```bash
export PYTHONPATH=qualification/stem-cell-v1
python3 qualification/stem-cell-v1/v18_grounded_utility.py freeze \
    --v14-plan PRIVATE/v14-plan.json \
    --v15-study PRIVATE/v15-study.json \
    --source-roster PRIVATE/node-evidence-precommit.json \
    > PRIVATE/v18-prelabel.json

# External model host produces a complete physical V14/V15 original-result
# journal, and a separate reviewer opens labels only after answer sealing.
python3 qualification/stem-cell-v1/v18_grounded_utility.py audit \
    --v14-plan PRIVATE/v14-plan.json \
    --v14-predictions PRIVATE/v14-predictions.json \
    --v14-adjudication PRIVATE/v14-adjudication.json \
    --v15-study PRIVATE/v15-study.json \
    --v15-policy PRIVATE/v15-policy.json \
    --v15-execution PRIVATE/v15-execution.json \
    --v15-adjudication PRIVATE/v15-adjudication.json \
    --v16-prelabel PRIVATE/v16-prelabel.json \
    --source-roster PRIVATE/node-evidence-precommit.json \
    --v18-prelabel PRIVATE/v18-prelabel.json \
    --citations PRIVATE/model-output-citation-inventory.json
```

## Scientific limitations and stop conditions

- This source-only program **does not generate or attest model outputs**, review
  original source bytes, guarantee that the catalog's bytes belong to the
  named publisher, authenticate provenance or execute neural inference.
  `independent_citation_evaluator_authenticated` and
  `original_reader_execution_authenticated` remain **false** in every report.
- An externally supplied `citations_entailed=true` is only a *claimed* semantic
  judgment. For genuine ground truth it requires independently witnessed
  source-text entailment, sufficiency and postseal evaluator attribution.
- Only the registered **additive** task-reward/CPU/token cost special case is
  compared; this is not a general stochastic FBSDE, optimal NDU policy, or
  counterfactual proof about unexecuted policy branches.
- Stable task families, 3 genuine future windows, adequate independent source
  support, validated forecast calibration, complete lifecycle cost, actual
  pretrained/strong-reference Reader and native model-host execution remain
  science blockers. V6 continued-learning retention remains unresolved.
- **No model selection, Cell Split, FinalUse, deployment, signature authority
  or production permission** can be created from these results, even if the
  `grounded_net_micro_delta` happens to be positive.

Local isolated Python 3.13 testing uses a **development-only V14 compatibility
module**, not the canonical V14 file. V15/V16/V18 have 148 tests in normal and
`python -O`; the GitHub read-only workflow executes the **actual imported V14.1
source and test suite** plus V15/V16/V18. A hosted success only establishes
source contract behavior, never real pretrained model effects.
