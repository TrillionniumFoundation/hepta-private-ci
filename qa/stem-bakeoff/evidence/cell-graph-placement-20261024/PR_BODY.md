## Question and actual result

This PR freezes and executes one fixed six-head graph through the existing native process owner, then publishes the retained evidence and a separate correction to completed-job recovery parsing. The question is numerical equivalence and observed placement cost, with all original warmup heads and inputs fixed before the measurements.

**All 18 graphs / 30 primary workers completed and passed the frozen numerical and decision-label checks. The primary multi-host comparison did not show a latency benefit:** C minus B averaged **+1,225 ms**, with a median paired difference of **+3,500.5 ms** and C slower in four of six blocks. All six pairs remain in the report.

| Arm | Fixed placement | Own configured ceilings | Median owner wall |
| --- | --- | --- | ---: |
| A | One main worker, all six heads | 200% CPU, 2 GiB | 55,669 ms |
| B | Two concurrent main workers, fixed 3+3 shards | Each 100%, 1 GiB | 51,598.5 ms |
| C | Same shards concurrently on main and pocket4 | Each 100%, 1 GiB | 51,216 ms |

Six blocks use all A/B/C permutations; C rotates shard-to-host assignment. All NumPy thread counts are one. Separate arm medians do not replace the paired comparison. These are equal sums of configured ceilings, not reserved/equal effective CPU capacity. The hosts, Python/NumPy versions and BLAS environments differ.

The graph uses all six initial warmup heads (linear/gated × seeds 7/17/29), 480 fixed projected rows and a canonical-order equal-weight reducer. A/B have exact numerical equality under the frozen reporter's `np.array_equal` convention. C's maximum absolute error is `3.3306690738754696e-16`, within the predeclared `atol=rtol=1e-12`; all per-head and mean argmax labels match.

## Measured scope and retained original failure

The enclosing owner interval measures cold dispatch, API observations/read pagination and a separately dispatched reducer. A's pure six-head calculation takes about **1.70–2.12 ms**, while its owner path takes **48.3–67.2 seconds**. This is not persistent-service latency, isolated network latency or an agent-task comparison. Worker/reducer phases are nested; RSS maxima are not simultaneous unique RAM. Native-service/owner CPU and some later costs remain unknown.

Original recovery `b0-A-s0` failed: the adapter incorrectly demanded a fresh launch acknowledgement for a legitimate `reused:true, launch:null` response. Original B/C recovery cases were not attempted. Their **failed / absent / absent** classification remains unchanged.

The original controller session was lost while its raw ledger was being sealed. **Only 4/34 chunks and 45/383 complete original raw records survived; the whole-ledger hash and complete original cost audit are unavailable.** The 18 graph owner/collection/reduction artifacts survived independently. Missing suffix, sealing, outer/helper and service costs are not reconstructed or filled with zero.

## Separate recovery correction and actual validation

Recovery-v2 accepts the legitimate reused receipt only when the original request bytes, idempotency key, host, job, digest and fingerprint bind exactly. It uses the unchanged original recovery owner/budgets and a separate append-only per-call journal. It does not rerun a primary or overwrite old state/evidence.

All three separately registered original-job lookups completed and returned byte-identical full old stdout/stderr:

| Case | New owner wall | Native calls / read pages |
| --- | ---: | ---: |
| A | 45,672 ms | 11 / 8 |
| B | 33,989 ms | 7 / 4 |
| C | 29,685 ms | 7 / 4 |

An independent byte/identity audit verified all 25 calls and 59 checkpoint files. All three case archives have exact acknowledged custody; an archive-union check verifies their disjoint deltas cover the final journal. B's earlier two transfer timeouts and later successful chunked upload are retained. This tests completed-job idempotency reuse, not injected crash, power loss or long-term migration recovery.

## Validation and published evidence

The peer-reviewed explicit partial audit actually ran on the retained primary artifacts: all 18 independent tensor/scalar checks, prefix integrity and original recovery integrity passed. It reproduced the unchanged original reporter exactly and kept `complete_original_cost_audit_pass:false`.

- Original report: `6df19c646c3b610011b138a3f0cc870bc4523d23d5ae1bc2b52f78778dc39102`.
- Actual partial primary audit: `33824ede8355be4e27786209956329da5e3ce8e8dcba4ab1d5ac0c0a159a6b16`.
- Separate final recovery-v2 audit: `c18b3f5b4c2e7978bfccfebb3d1d41835872a85e99c5592762939a153baed6d5`.
- Original protocol, owner, worker, reducer, reporter and original adapter bytes remain unchanged.
- Source/fixture gates, independent reviews, failed candidates, the original partial evidence, and the separate new recovery evidence are retained in the publication archives and per-file manifests.

Evidence and readable findings are under `qa/stem-bakeoff/evidence/cell-graph-placement-20261024/`. The earlier pre-execution input/source freeze remains in [93f64e47](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/93f64e47f99f0ac8587af81eeb361d20b645e562/qa/stem-bakeoff/evidence/20261024-fixed-graph-native-preflight).

This finite fixed-graph experiment establishes qualified numerical placement equivalence and exposes costs/failure modes of the actual execution path. It does not establish beneficial cell splitting, learned edges, new task competence, whole-system net benefit, native-agent superiority to Codex or AGI. No deployed runtime/service was changed or restarted.
