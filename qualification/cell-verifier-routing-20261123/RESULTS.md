# When should the second Cell see the first answer?

On the exposed six-task B2 panel, selecting the second Cell after a fixed P first turn has a ceiling of **5/6** when both available second Cells receive the full first answer and verification feedback. The corresponding ceiling from the recorded upstream T/T and T/F paths is **0/6**. Better routing over these two existing messages alone cannot recover another task in either panel.

A different policy changes the *information passed to the second Cell*. It uses the first verifier’s reason. On `invalid_test_patch`, the other adapter reads the original request from a clean context. For every other reason, the first adapter receives its original answer and feedback for a second attempt. Selection retains the earliest verified success. The policy always allocates two generation slots and two verifier opportunities, including after a successful first turn.

## Results from recorded responses

| Retained success | B2, 6 tasks | Upstream, 6 tasks |
| --- | ---: | ---: |
| Same adapter twice, with full relay | 5 | 0 |
| Other adapter second, with full relay | 5 | 0 |
| Best second adapter for each task given full relay, hindsight bound | 5 | 0 |
| Both adapters read the task independently, replay | 5 | 0 |
| Choose clean request on `invalid_test_patch`, replay | **6** | **0** |
| Second answer alone under the same replay | 3 | 0 |

B2’s improvement comes from one Django task. P’s first `escape_leading_slashes` response was rejected as an invalid patch. C repeated the error when it saw P’s answer, but its original, independently observed clean response passed. On Django’s `is_same_domain`, the first response was a valid patch that failed the business checks. The original P follow-up repaired it. Always resetting loses this repair. The other four B2 successes are retained from the first turn. One, `first_true`, is sensitive to Python’s equality between `True` and `1` under the original controls.

The rule was fixed locally after B2 inspection and before this analysis read the upstream per-node archive. Both panels and their aggregate outcomes were already public to the project and previously evaluated. In the upstream replay, two clean fallbacks were triggered and neither passed. The historically executed upstream answer-edge removal arm retained **1/6**. The two panels also use different fallback adapters. B2 uses an A-trained verified-credit continuation, upstream uses the matched final-only adapter. These observations cannot isolate a panel effect from a change of model.

B2 contains two tasks from each of Django, more-itertools and Pydantic. Upstream contains six tasks from Click, Werkzeug and Requests. Click and Werkzeug share the Pallets organization. There are zero newly acquired tasks, training repetitions or authenticated users in this analysis. The one B2 gain is post hoc, confined to one project; an estimate of future improvement needs prospective independent sources.

## What was computed

`replay.py` reads only the two archives identified below. It verifies each archive hash, each selected node’s request/output/verification digest, answer-to-verifier binding and actual business outcome. For paired first histories it checks model identity, rendered prompt, generated token IDs and answer. For the clean alternate it checks the original request, rendered prompt, generation configuration and verifier source. The result carries the chosen receipt digests for every task.

Across all four B2 fixed arms the replay checks 48 original nodes; across the three comparable upstream fixed arms it checks 36. The route uses 12 logical slots in each panel. The selected historical nodes contain 5,118 input and 529 output tokens for B2, and 5,529 input and 983 output tokens for upstream. These are recombinations of existing calls. Live reset isolation, adapter switching latency, verifier scheduling and energy require execution of the new policy. The experiment issued zero new generation and verifier calls.

The fixed rule in `route_policy.json` can be evaluated on an independently acquired panel. A live comparison should retain the same-model and full-relay controls, common fresh requests, verifier availability and two-slot cap. The observable unit for a benefit is the task on which the route changes a verified outcome. Source clusters and independent training repeats should be kept visible when estimating uncertainty.

## Reproduce

The following commands run from this repository with both input commits available in the local object database.

```sh
git show 8f1f6f1930ef4ed60dd95d6fd3fe2be7502ad23f:qualification/cell-parent-credit-circuit-20261118/RAW_EVIDENCE.tar.xz > /tmp/hepta-b2-routing.tar.xz
git show 7e0687b916dfbc8b87f1e3d3709856ed44dafbc2:qualification/cell-upstream-circuit-20261118/RAW_EVIDENCE.tar.xz > /tmp/hepta-upstream-routing.tar.xz
python3 qualification/cell-verifier-routing-20261123/replay.py --b2 /tmp/hepta-b2-routing.tar.xz --upstream /tmp/hepta-upstream-routing.tar.xz > /tmp/hepta-route-replay.json
cmp /tmp/hepta-route-replay.json qualification/cell-verifier-routing-20261123/REPLAY.json
```

[Original B2 experiment and cost accounting](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8f1f6f1930ef4ed60dd95d6fd3fe2be7502ad23f/qualification/cell-parent-credit-circuit-20261118/RESULTS.md) · [Original upstream experiment](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6704)
