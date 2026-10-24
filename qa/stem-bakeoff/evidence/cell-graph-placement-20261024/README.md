# Fixed six-head graph: actual placement results and incomplete controller evidence

## Outcome

The original unchanged reporter accepts numerical parity for all 18 scheduled
graphs and 30 workers. A and B reproduce the block-0 A probability values
exactly under the reporter's `np.array_equal` comparison. Its field named
`bitwise_equal` uses that comparison; this field alone does not prove arbitrary
floating-point byte representations identical. C's largest absolute difference
is `3.3306690738754696e-16`, below the
predeclared `atol=rtol=1e-12`. Every per-head and final-mean decision label is
identical. The logical computation therefore survived these actual placements.

The primary paired comparison does **not** show a multi-host latency benefit
on this execution path. C minus B is slower in four of six blocks; its mean
difference is **+1,225 ms** and median paired difference **+3,500.5 ms**. Six
blocks are descriptive evidence. There is no population confidence interval,
tail-latency claim, or whole-system net-benefit estimate.

The result is for the six original warmup heads and 480 fixed projected inputs.
No heads were selected using later task outcomes. The graph is a shared input,
six unchanged heads, and a fixed equal-weight mean. It is not a learned-edge,
cell-split, migration-learning, agent-task, or general-intelligence experiment.

## Frozen placements and all paired measurements

| Arm | Actual placement | Own configured ceilings | Graph wall median |
| --- | --- | --- | ---: |
| A | One main process, all six heads | 200% CPU; 2 GiB | 55,669 ms |
| B | Two concurrent main processes, fixed three-head shards | Each 100% CPU; 1 GiB | 51,598.5 ms |
| C | Same two shards concurrently on main and pocket4, with frozen host/shard rotation | Each 100% CPU; 1 GiB | 51,216 ms |

All NumPy thread counts were one. The sum of the configured local CPU ceilings
was equal. These are ceilings, not reserved or equal effective CPU capacity.
The hosts have different physical hardware and Python/NumPy/BLAS environments;
ancestor limits, scheduling and background contention are not isolated by this
design. The C−B comparison is not a pure measurement of physical network delay.

| Block | C−B ms (primary) | C−A ms | B−A ms |
| --- | ---: | ---: | ---: |
| 0 | +22,370 | +16,561 | −5,809 |
| 1 | +3,229 | −9,230 | −12,459 |
| 2 | +3,772 | −7,181 | −10,953 |
| 3 | −2,988 | −967 | +2,021 |
| 4 | −24,177 | −18,062 | +6,115 |
| 5 | +5,144 | +2,382 | −2,762 |
| Mean | **+1,225** | −2,749.5 | −3,974.5 |
| Median paired difference | **+3,500.5** | −4,074 | −4,285.5 |

Negative differences mean the candidate was faster. Separate arm medians are
not substitutes for the predeclared within-block comparison. All six paired
values remain; the unusually positive and negative blocks are not discarded.

## The measured operation includes the controller/API path

The pure head computation is much smaller than the enclosing graph interval.
For A, six-head inference takes 1.70–2.12 ms per worker, with a median of
1.98 ms. The worker's measured process interval before its final trailer is
128–390 ms. In contrast, A's enclosing owner interval is 48.3–67.2 seconds;
its worker collection path is 28.6–39.1 seconds and its reducer-service path
18.0–28.5 seconds. These intervals include the cold process dispatch, repeated
original Runtime API observations/read pages, controller-side encoding and
validation, and a separately dispatched reducer.

This is the latency of that actual cold control/API path. It is not the latency
of a persistent cell service or the mathematical matrix operations alone. The
worker/reducer phases are nested inside the owner interval and must not be
added to it. Worker and wrapper CPU measurements also have distinct boundaries;
wrapper child CPU overlaps reducer CPU. Process RSS high-water marks cannot be
summed into simultaneous or unique physical RAM. Native-service and external
JavaScript-owner CPU/RSS remain unmeasured.

The source report retains the actual CPU/RSS values and exclusions. Missing
post-owner or service costs are unknown, not zero. This experiment supports no
comparison between a native agent and Codex as task-solving systems.

## Original recovery failure and subsequent separate correction

The original first recovery, `b0-A-s0`, failed in the adapter parser. Its actual
Runtime response was `reused:true`, `launch:null`, `retried_launch:false`, with
the same original job/digest/fingerprint and completed cached status. The
adapter incorrectly required a fresh `launch.ok` acknowledgement even for reuse,
then retained an unresolved pending entry. The original `b0-B-s0` and
`b0-C-s0` recoveries were not attempted. These three original classifications
remain **failed, absent/unattempted, absent/unattempted**.

The independent recovery-v2 package changes only this receipt interpretation
and its separate validation/persistence boundary. It imports original job and
output identities, uses the unchanged recovery owner and original call/time
bounds, and writes exclusive checkpoints before and after every actual call.
Its results belong to a new evidence namespace. The three actual v2 cases all
completed and reproduced the entire original stdout and stderr byte sequences.
The independent read-only audit verifies 25 native call intent/result pairs,
59 file checkpoints, original start-argument bytes, job/digest/fingerprint/key
bindings, contiguous 16 KiB pages, the complete output hashes and original
owner call/time limits. It reports no issues. The earlier through-B audit is
also retained; that capture correctly did not qualify all three cases.

| Separate v2 case | Original host and job | New owner wall | Native calls / read pages | Original stdout bytes |
| --- | --- | ---: | ---: | ---: |
| `b0-A-s0` | main / `1a16d8e52e6-1b6abb-4960` | 45,672 ms | 11 / 8 | 126,914 |
| `b0-B-s0` | main / `1a16d8fc267-1b6abb-4966` | 33,989 ms | 7 / 4 | 64,812 |
| `b0-C-s0` | pocket4 / `1a16d91229c-1b6abb-496c` | 29,685 ms | 7 / 4 | 64,802 |

These completed-job lookups have `reused:true`, `launch:null` and
`retried_launch:false`; no new graph inference is claimed or required. The
unchanged old worker's CPU is not charged again. Per-call local journal
checkpoint time is inside these owner intervals. The separately recorded
outside-owner spans before the final outer-file acknowledgement are 47,801,
35,682 and 31,412 ms. Those enclosing spans overlap the owner intervals and
cannot be added to them. Final acknowledgement, archive/transport and native
service CPU/RSS have separate or unknown boundaries. These measurements are
not a controlled speed comparison with the original failing parser.

The independent recovery audit imports the pinned original recovery snapshot;
the separate partial primary audit additionally checks that the actual original
A file still has its exact failed-record SHA and that original B/C files remain
absent. The v2 passes do not replace **failed / absent / absent** in that
original namespace.

This is completed-job idempotency lookup/read validation. It is not a crash,
machine-loss, power-loss, migration, or long-term graph-recovery test.

### Separate archive publication and retained failures

The three v2 case archives have acknowledged writes of 570,932, 340,706 and
358,659 bytes. They are journal deltas: all three together preserve the 25
native call intent/result pairs and 59 final checkpoint files. A read-only
archive-union check verified their manifests, member hashes and actual remote
write acknowledgements. A used a create-only binary write. B first had a binary-write
timeout and then a process-start timeout while attempting a different transfer;
the intermediate file observations reported absence. These original timeout
receipts remain. A timeout is an unknown effect outcome, not proof of a failed
write. B's later seven-chunk upload and commit acknowledged its exact archive
size/SHA. C's eight-chunk upload and commit did the same.

The first B copy invocation alone measured 123,281 ms outside recovery. The
recorded C transfer measured 42,405 ms, excluding archive construction and its
final receipt persistence. C publication overlapped a later native-code build;
all measured graph/recovery work had settled before that build. Neither cost
can be folded into a fabricated complete original graph total. The full set of
archive, timeout, reconciliation and upload receipts must accompany these
artifacts.

## What survived the controller-store loss

The 18 original owner files, all original graph collections/reductions, and
the failed first recovery were written before the controller session was lost.
Only four of the 34 raw-ledger chunks were persisted: 2,097,152 bytes out of the
declared 17,781,056. Forty-five complete original JSON call records were
recovered from this prefix; the snapshot declared 383 records. The extraction
checks original chunk receipts, byte ranges and internal request/response SHA
values, stops at the first incomplete object, and never synthesizes the suffix.

The full-ledger SHA is not verified. Original missing raw-call suffixes,
post-owner/helper/outer spans and later sealing-call evidence are unavailable.
Thus the original numerical graph result and its recorded enclosing intervals
can be checked from the persisted graph artifacts, while a full original
native-call and total-cost audit remains unavailable. A passing prefix-integrity
check must not be described as a passing full-ledger audit.

The original full-evidence auditor remains unchanged. The new
`audit_cell_graph_partial_v2.py` uses an explicit partial mode: it reruns the
pinned original reporter; independently reconstructs each six-head stack and
equal-weight mean from retained worker stdout; checks the archived tensors,
hashes, frozen tolerance and decision labels; and recomputes the six paired
contrasts. It separately validates the retained prefix and always labels the
original full-native/whole-cost audit unavailable.

That peer-reviewed script was actually executed read-only against the retained
remote artifacts as job `1a16ddf5c60-1b6abb-4a6a`. The original Runtime reports
exit 0, complete output and no truncation. It passed all 18 independent tensor
and scalar checks, the retained-prefix integrity check, and the original
failed/absent/absent recovery integrity check. The complete original cost-audit
flag remains **false**. Its result SHA is
`33824ede8355be4e27786209956329da5e3ce8e8dcba4ab1d5ac0c0a159a6b16`.
It ran after the graph/recovery measurements and while a separate native-code
build was active; this read-only verification is not another latency sample.
Source tests/review, the actual native execution receipt and the actual audit
result are separate evidence files.

## Immutable evidence identifiers

| Evidence | SHA256 |
| --- | --- |
| Original frozen dispatch | `595d40d93a9ba394c21c39fd41c5c8b60ab5ceddfcdb8bdd9f5102ce193fa4ae` |
| Original unchanged reporter result (85,620 bytes) | `6df19c646c3b610011b138a3f0cc870bc4523d23d5ae1bc2b52f78778dc39102` |
| Original failed-recovery capture | `36c3d163aa25c8c3182eaedc19e356399b3aea5308a4d2b73eff9210744a61cd` |
| Original failed `b0-A-s0.json` record | `758f4ffa3dbeede3a6cf9bb59694b56a8382c845d71d6e5b3733ff217b536c32` |
| Actual retained prefix bytes | `c0e41a7adf1c83943f61e146d49b43ff70ffb57800b82cb45f906275a1cfbcfc` |
| Complete-prefix extraction document | `bc9d9bf887c5f68fd34815f3ef7e71403bd888c06ff622f4c8c117f63d5cd913` |
| Separately frozen recovery-v2 protocol | `7e73a090d4942afc88aa188b8735388e7585ca54a987c79fc1d1b9b69ee66e50` |
| Actual recovery-v2 original-reference bundle | `366bc1fc39a93361f761fadbd22c60070ec0d3a8f63ab7f5e67b155ff61d9b6e` |
| Independent final actual recovery audit | `c18b3f5b4c2e7978bfccfebb3d1d41835872a85e99c5592762939a153baed6d5` |
| Actual independent partial primary/prefix audit | `33824ede8355be4e27786209956329da5e3ce8e8dcba4ab1d5ac0c0a159a6b16` |
| Preserved earlier through-B audit | `ade5a23d03fbad881ba18bdf46e7dc01e3c811f1ec3f3a4a858e985710d01834` |
| Recovery-v2 A archive | `e5029a8ae54e5c8096d8b810cb208ea5289b8d0cfa044c44931682cf1e17f1ce` |
| Recovery-v2 B archive | `93ca89e25dcda67917c6c4893b166d40f74d77a99195e9ab7626c8eacd18ff51` |
| Recovery-v2 C archive | `169b45a7da7f7eff9e3d51158708e761a40a9dc55263b27be73a67332c34a52a` |
| Actual recovery archive-union custody check | `66e37f7db07520b8145fe08c03e1dd797e4b4bc7c94074fae92284ed79491ee1` |

The manifest's declared full-ledger SHA
`a8cd6fc298c63d525e8794c00d6e738800898c968b30b8ad52e589ad87807589`
is an unverified whole-file claim because 30 original chunks are missing.
It must not be listed as a successfully verified artifact.
