# V17 — same-terminal Reader and policy-branch consistency audit

**RESEARCH ONLY / DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**
Stacked strictly on V16 PR #2407. This patch modifies source-only V15/V16
research validators and synthetic fixtures; it changes no selected weights,
production Rust, Control/CNS, artifact owner, inference/FinalUse authority or main.

## Reproduced P0 measurement defect

The V15 fixture assigned an answer SHA from `(case_id, arm)` rather than the
actual terminal Reader state. Consequently for `q2`, both `stop` and
`ndu_shadow` stopped on exactly the same source/model/request but could report
**different answers**, and `fixed_one` and `greedy_one` could do the same on
another identical terminal. V15 checked each row's state/input hash but did
**not check output equivalence across arms**. Different independently claimed
correctness on the same terminal would manufacture NDU task benefit. V16 only
checked that V15 `stop` matched V14 candidate/sufficient, not other arms.

## V17 fail-closed invariants

1. Under this **frozen deterministic-output qualification profile**, repeated
   `(case_id, terminal_request_sha256)` must yield exactly the same
   `answer_sha256` and identical `citations_entailed_claimed`, regardless of
   selected policy arm. Different generation/decoding settings must be
   represented in a new, independently approved request identity/profile; a
   model digest or request hash alone **does not prove** determinism or physical
   inference execution. Stochastic sampling without source-bound seeds is
   explicitly unsupported for this comparison.
2. The same `(case_id, node_id, action_id)` across policies must yield the same
   *observed successor* in this fixed deterministic environment profile.
   A stochastic environment needs its random stream, event observation and
   counterfactual comparability explicitly versioned first; this does not
   magically equate different stochastic episodes.
3. After complete postseal adjudication, identical
   `(case_id, terminal_request_sha256, answer_sha256)` must carry identical
   correctness and citation-entailment judgments. Source hashes alone do not
   establish independent human evaluation.
4. V15 now discloses paired **changed terminal request counts**, **changed
   answer counts**, and **quality changes on unchanged terminal inputs**.
   Changing answer or correctness without changing the terminal Reader request
   is not a System 2 gain. V16 rechecks the zero unchanged-terminal quality
   difference before computing clustered cost comparisons.

These checks reject self-contradictory external records; they do not authenticate
an external model host, external judge, context validity, actual resources,
NDU forecasts or a production capability. A stale or fabricated result with
consistent hashes remains unverified.

## Repeatable execution and exact claim boundary

At repo root:

```bash
export PYTHONPATH=qualification/stem-cell-v1
python3 -m py_compile qualification/stem-cell-v1/{v15_system2_split_shadow,test_v15_system2_split_shadow,v16_reader_system2_bridge,test_v16_reader_system2_bridge}.py
python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v15_system2_split_shadow.py' -v
python3 -m unittest discover -s qualification/stem-cell-v1 -p 'test_v16_reader_system2_bridge.py' -v
python3 -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_v15_system2_split_shadow.py' -v
python3 -O -m unittest discover -s qualification/stem-cell-v1 -p 'test_v16_reader_system2_bridge.py' -v
```

Isolated local Python 3.13 checks completed **76 V15 tests + 48 V16 tests =
124 ordinary and 124 optimized**, with synthetic cases and a **local-only V14
compatibility module**. The local V14 compatibility module is not included in
the patch. The dedicated hosted read-only workflow must test actual repository
V14/V15/V16 together; exact-HEAD CI results are not inherited or preclaimed.

**No original V14 pretrained Reader requests, new prospective task labels,
independently authenticated source groups, matched physical NDU gains,
multimodal generation, Cell Split activation or 10T/100T equivalence were
produced by this repair.** V14 Reader sufficiency remains the P0 empirical
predecessor; the V6 retention failure is not waived. Production remains denied.
