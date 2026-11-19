# E25 six previously unused original MultiRC passages — independent recount

**Research-only, DRAFT / DENY_ALL. No Cell/NDU/model selection or FinalUse.**

This line consumes an **actual successful source-head GitHub Actions execution** from E25 #2339 (`38727583089`, source SHA `1ab2615004fc524ca18d47aaa97f6dc59356d533`) instead of the previously stalled/synthetic source gates. Its original training/material owner, real frozen pretrained ModernBERT four-Reader inference, pre-human blind seal and independent source-label score jobs all completed `success` on that exact E25 head. The E25 source experiment is distinct from #2319's mmBERT-small AG News panel and 5-parameter ModernBERT archival Head study.

The four original E25 source-head ZIP IDs and exact SHA-256 are locked in `audit.py`. `actions/download-artifact` retrieves the named artifacts from that one exact successful run and extracts them; the auditor then checks SHA-256 of every consumed original JSON member against the locally verified ZIP bytes. On a local host, it directly byte-hashes and opens the four original ZIPs. It refuses omitted candidates, mismatched source groups/holdout seals, altered labels, mutated probabilities, forged authority and a self-reported success score. It **independently recalculates** each method's original human binary-candidate correctness, two-class Brier, whole-question accuracy (every genuine alternative correct) and full-source-passage success.

Actual source-disjoint results, six **previously unscored passages within the SAME public MultiRC family**: 12 original questions, 51 genuine alternatives. E24 frozen question-softworst `tau=.01`: **2/12 whole questions** and **33/51 candidates**, vs E16 frozen scaled-Brier **1/12, 33/51**, mean-pool query frozen **1/12, 28/51**, no-evidence **1/12, 27/51**. E24/E16 differ on only one whole question; source-cluster inference is underpowered and E24 temperature was tuned post-hoc on old passages. No method completes both questions for any one of the six passages. No independent publisher signature, different dataset family, prospective time window, task-quality superiority qualification or measured complete Encoder/Reader/Head/Verifier service cost.

**Not NDU evidence:** E25 contains original Reader fourfold ensemble Heads and their frozen controls, but it has **no physical NDU action/token/training-investment arm**, ordinary same-objective control or matched NDU costs. The incremental 2/12 vs 1/12 cannot be attributed to NDU. The fixed8-dominates-NDU negative result on a different AG News source remains intact. This audit is a stringent new-source *reader-capacity diagnostic*, not an NDU promotion. Do not merge into main or grant production authority.

Local reproduction (Python standard library):

```sh
E25_ORIGINAL_INPUTS=/path/to/four-original-zip-names-dir python -m unittest discover -s qualification/ndu-e25-real -p test_audit.py -v
python qualification/ndu-e25-real/audit.py --inputs /path/to/four-original-zip-names-dir --output /tmp/e25-recount.json
```

Original ZIP names must be `public.zip`, `owner.zip`, `model.zip`, `score.zip`. CI uses `E25_EXTRACTED_INPUTS=/path/to/four-unzipped-artifacts` and the `--extracted` flag. Historical pretrained weights, raw texts, human gold and model answer bytes are not committed into Git; research source and sanitized non-production results only.
