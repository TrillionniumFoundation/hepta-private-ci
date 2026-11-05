# Joint component qualification — 2026-11-05

**Release status: HOLD.** This record retains reviewable component changes and their actual refusals. It does not authorize production activation or mark any of the eight joint acceptance gates complete.

## Current fixed Chain candidate

The current candidate is Chain C3 `b5ef97b29c2e8b738525a2e3326dd60784c46e72`, tree `020880f22725e93cabb65c6e7eda3cbbd3c2405a`, on draft [PR #722](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/722). Its verified ordered merge is `df39fe4db01e20ae6494a2cb4570434c50a84cfc`, with parents `dd6e1c3cbeacbdc532b0679297835b3a0aac78f0` then C3, and the same tree. C3 changes only three existing CI files relative to C2: bounded content-keyed parsing, five mutation controls, and the exact nine-name W1 kernel guard. The original 300-second applicability limit and W1 commands/resources/budgets remain unchanged.

The complete C2 base passed the original project audit and full raw source guard before the C3 commit. Seventeen selected parser controls and eight synthetic-log guard controls passed; the latter are not native Rust executions. See [C3 component provenance](chain-C3-components/root-review.json) and [fixed source/queued-run identity](chain-C3-components/fixed-candidate.json). All 17 actual C3 pull-request workflow runs were queued at 17:14:35 UTC. A dynamic PR aggregate receives no gate credit. C3 must earn its own original native and hosted results; the C2 measurements below retain historical scope.

## Preserved C2 candidate and source evidence

The historical frozen candidate is Chain C2 `03521b2f32346a49cccde8ff72e8c7b886b31222`, tree `e0235248ecae2a67717c8b9ff2e3f25774ba63d7`, on draft [PR #720](https://github.com/TrillionniumFoundation/Trillionnium-Chain/pull/720). Its verified ordered merge is `ebe23e4bd9eeb704479e588e873edc2c61bf7e76`, with parents `dd6e1c3cbeacbdc532b0679297835b3a0aac78f0` then C2. The merge tree equals the C2 tree.

C1 `9ecdbebc897d35f07b998d084b015db8474be84b` changed five already registered files without updating their required corpus pins. The original checker refusal is retained: `HOLD_NO_GO: changed source: scripts/ci/check_ci_contract.py`. C2 changes exactly those five pin values and adds evidence. The root review and the separate W1 review both verified the actual Git blobs; no runtime rule or public-service budget was changed by this correction.

C2 was materialized as a complete checkout and checked before and after its original source controls: 10,357 tracked entries, 985,264,447 tracked bytes, zero missing objects and zero hidden index flags. The original PQ source guard and 37 source controls, the claim guard and 22 claim controls, and the source inventory passed. All 38 original stdout/stderr files were exported and independently checked against their recorded hashes, including 21 actual empty files. A separate locked/offline metadata check resolved 26 workspace members and 175 packages with unchanged Cargo.lock. These source/metadata commands did not compile or execute a native test; the subsequent native attempts are recorded below. The C1 refusal remains a recorded failure, separate from C2's source-control result.

The original C2 baseline run is [42051619772](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/42051619772). At the recorded observation on 2026-11-05 15:24:50 UTC, all 18 jobs were queued, had no assigned runner and had no executed steps. A later root observation at 16:13:08 UTC still found all 16 fixed-PR workflow runs queued. Dynamic PR aggregate status and moving-branch runs are excluded from that count. Later status must be read from the run itself. The historical C1 baseline [42036027611](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/42036027611) was cancelled after its moving development branch advanced.

## Actual C2 native rejection-cost run

The original native preparation passed. On the complete C2 source, 92 rejection-report controls, 100 CI contract controls and all three selected Rust controls passed; the original strict Clippy and workspace format checks also passed. The broader checks phase remains **failed** because the applicability command reached its original 300-second limit. Seven cases completed and the next case had started; no assertion failure or sampled active stack was recorded. Two independent source reviews identified repeated whole-file parsing as a concrete cost source, without claiming it was the exclusive cause of that timeout.

The original four-kernel collector and original reader both passed. The run retained 96 actual proof flows, 1,152 timed verifications, 96 independent scalar winner replays and the invoked ELF. The build took 30.659 seconds within 900; the native measurement command took 8.099 seconds within 180. The original cleanup budget was unchanged. Source identity before and after remains C2. Root independently verified all 87 exported files and every member of the complete archive: 70 actual command stdout/stderr files, including 37 actual empty files, plus manifests, machine records and executable. The retained ELF is 707,216 bytes, SHA-256 `39a2d4f3e2cc62b799a8871846d3303537b67badc67f662dd5dadd9601e7b959`.

The measurements are local x64 monotonic wall time on the recorded Intel Xeon E5-2673 v3 host. The following ranges are the medians of eight separate class/target cells for the production FullLimb verifier. Each cell has twelve samples; the nearest-rank p95 is therefore its observed maximum, not a tail bound.

| Input | Range of per-cell medians | Largest per-cell nearest-rank p95 |
| --- | ---: | ---: |
| Legal proof | 1.666793–1.697455 ms | 2.197303 ms |
| Transcript mutation | 1.500383–1.521604 ms | 2.479376 ms |
| Last product-cell mutation | 1.670701–1.707710 ms | 2.958098 ms |

The independent review and root recalculation agree on all 96 class/target/kernel/variant cells, including exact medians, p95, sums and matched total-cost ratios. All four kernels receive the same proof in each arm. Legal production is a separate measurement: this collector uses only one `PreparedTask` producer, with 1,434 actual nonce attempts, including 1,338 unsuccessful attempts and 96 winners. Four verifier implementations are not four legal producer algorithms. Setup is fresh per accepted proof; the run does not establish amortization over multiple accepted proofs or globally cheapest legal work. Mutation-only construction cost assumes an already acquired valid proof; the first-construction denominator includes that acquisition.

[Full receipt archive and extraction instructions](chain-native-C2/README.md), [independent finite-cost review](chain-native-C2/C2-independent-cost-review.json), and [root raw-data recalculation](chain-native-C2/root-cost-recalculation.json) retain all these distinctions. These results do not execute the original hosted public-service gate or establish work hardness, worst-case rejection cost, cross-architecture performance or independent WAN liveness.

## V12 source and ordinary handoff

The following paragraph records the C2-bound draft. Its subsequent C3 retarget is in progress and will retain all 53 selected members, because none of the three C3 changes is a member of that closure. It must be revalidated on the final complete Hepta candidate.

The unpublished V12 draft was retargeted to C2 before integration. Its manifest SHA-256 is `2410c65955383aaffa977840770c8209b8f62db0805ccc7585091d37cd5f99e7`. All 53 selected source/configuration members were verified: 52 are unchanged C1 blobs, and the changed corpus configuration is C2 blob `c8486ca9cce475d429b2a3b4bc43ce9ffec57ddc`. The 13 native-loader inputs are Python/configuration inputs, not Rust modules. All 55 historical registry assignments and the V11 manifest remain unchanged.

Actual local controls on the C2 draft passed:

- 135 source and handoff controls, including the original 116 and the new 19; 32.693 seconds.
- 32 original diverse-data controls; 0.941 seconds.

The strict helper delegates with `os.execv` to the fixed Chain's existing `cell-host-v2` native handoff, using the original explicit flag/value set and resource limits. It verifies source, owner configuration and snapshot pins. It does not fabricate current operator grants, material roots, runtime snapshots, installed-image qualifications or model outputs. The tests intercept delegation; they do not qualify cold model installation or live inference.

The two selected CI lanes retain their original resources and step order. Four other jobs are unchanged. The source-control floor becomes 135, the W1 report-control floor becomes 92, and the 12 supervisor cancellation controls are separately collected. The first C2 static review also caught a stale workflow in the selected Python fixture; its refusal is retained. Copying the candidate workflow corrected that audit fixture without changing executed Python/configuration bytes.

## Recovery-frontier component

The recovery patch validates SQL projections against canonical payloads, binds ACK and uncertainty observations to their actual authoritative intent, rejects orphans and repeated sequences, and covers duplicates at the 256-row page boundary and `i64::MAX`. It preserves the digest domain and the one-million-row bound.

Actual native history is retained:

| Source | Observation | Qualification scope |
| --- | --- | --- |
| Test-only `13c8a987927f4d6bf3db1e57dc6e7bb692800b74` | Five intended RED assertion failures | Demonstrates the baseline defects for these controls |
| Component `a877333eff1577179fce8b1ceb6edf4322440e03` | Five new controls and all 17 original owner controls passed | Isolated recovery component |
| Same component, full evidence library | 159 passed, one timed out, one original skip | Full library gate failed |
| Exact unmodified `1556a4df6e279055fd8196f81a4ca2fe0f19384a` | The same qualification-bound test timed out at 60.006 seconds | Confirms a pre-existing failure; does not waive it |

The timed-out test is `qualification_tests::claim_query_rejects_more_than_512_references`. The original per-test limit remained 60 seconds; the 600-second wrapper did not time out in these two library/baseline observations. The original failed RED fixture attempt is also retained; it had three intended assertions and two DDL fixture failures before the fixture was corrected.

Raw log hashes and clean source identity before/after the listed tests were independently checked. The GREEN test executable was not captured while those historical tests ran. A later rebuilt executable must not be attached retroactively. Lint and final format steps after the failed full-library gate had not executed in that historical attempt.

## Qualification append cost component

The separate two-file change avoids constructing an evidence-set digest when the claim type does not consume it. It retains the original SQL, ordering, `LIMIT 8193`, over-8192 refusal, decoding of every historical row, and lineage/replay validation order. A rejected earlier design would have skipped historical decoding; that design was not adopted. The new corruption control changes an old projection, observes rejection, restores it and retries the same signed sequence successfully.

The actual formatted component is `4dce06a9945fc54482f546c9dfb7cbb7a4716ccc`, tree `ace984bea899295f7e8fa6666fc78cfd49ad2a92`. Its complete checkout had 11,825 tracked files and no hidden index flags. The original 512-reference test passed in **54.595 seconds**, and the new historical-corruption/replay control passed in **0.488 seconds**. The original wrapper passed in 147.033453 seconds including compilation, with two passes and no failures. Its original 600-second command budget and 60-second per-test limit were unchanged. The original 512-reference test function itself is unchanged.

The extra execution-image observer captured no ELF, so the outer pipeline correctly failed despite the two Rust test passes. The [actual receipt and raw log](qualification-perf/native/attempt-1/two-controls.json), [outer failure](qualification-perf/native/attempt-1/two-controls-status.json), and [independent content/hash review](qualification-perf/root-review.json) retain this distinction. The two-file patch SHA-256 is `903269d4d4741e051437dcc6eaeaf5e6a455a4a88fab10f4b0606e415ca8e0b7`.

Full-library, scoped lint, final format and correctly attributed execution images still require execution on the final joint source. The cumulative historical decode remains quadratic; one 512-reference pass, with limited headroom below 60 seconds, does not qualify an affordable long-term growth budget or establish a speedup ratio against a timeout-censored baseline.

## Ordinary automation PQ migration

The automation host migration requires schema 4 and ML-DSA-65, binds the complete provider configuration and current authority scope, authenticates the current signed feed before creating local authority state, and rechecks current generation/PQ authority at the provider boundary after awaited work. It preserves the active-effect fence and consumed-nonce semantics. Recovery may use a bounded, current-signed exact historical policy reference for the same provider; dispatch remains current-generation only.

Historical component `495e36f8cb71fdae7290710dd339e2ee34d4feec` passed all ten provider-effect controls, including its one new PQ contract control. Those are ten distinct passes, not eleven. The first new Agentd selection then exhausted its original 600-second wrapper while compiling, with zero tests executed. A later original dispatcher command failed compilation with five diagnostics in test code, again with zero executed tests. Both unsuccessful attempts remain in [automation-pq-native](automation-pq-native/); later source fixes do not inherit the earlier provider passes.

The first observer retained a provider test image but did not perform all later process-ancestry and post-open identity checks. A corrected collector subsequently passed three real desktop controls; this does not retrospectively improve the historical capture. Final qualification must bind the actual image during execution on the final source. The real Agentd process control is prepared separately to exercise durable provider application with no ACK, an owned supervisor kill, current-generation restart and lookup-only recovery of the same operation. Its fixture roots and loopback services do not establish independent custody, a live Chain node or WAN qualification.

## Current Hepta preparation checkpoint

The source preparation branch is at `e373bf7df8b2d6a7360090ba392f0d07275063c8`, tree `b02a95375a5f6299abc8b167e216a0e2534acc52`, before the C3 V12 retarget. This integrates the recovery, bounded qualification-cost, ordinary automation PQ, real Agentd process test and 69-name workflow changes. It is not yet a frozen H1 qualification. The final five-file delta contains original formatter output plus two public-import corrections; no dependency or lock file changed.

The full preparation checkout verified 11839 tracked files, raw Git blobs and unchanged shared configurations. Actual preparation failures include an incomplete promisor fetch, missing original formatter, and a 180-second installer timeout. The isolated original `uv==0.11.3` prerequisite was then installed and matched the official wheel SHA-256; the original 300-second formatter limit was retained. These environment and formatting steps executed no native tests. [Raw preparation history](hepta-preparation-history/root-review.json) and [format/import review](hepta-format-and-imports/root-review.json) preserve their exact scope.

The native coordinator and capture machinery are retained under [frozen-execution-machinery](hepta-preparation-history/frozen-execution-machinery/manifest.json). The actual job has a 5400-second outer bound, covering all source guards, commands, captures and extra controls. Original per-command deadlines remain unchanged. Local Linux AppArmor namespace policy differs from the hosted workflow prerequisite and is recorded without changing the desktop global setting. No full hosted-matrix pass is inferred from a local execution.

## Authorization boundary still open

The separate [ordinary tool and provider audit](ordinary-tool-pq-boundary.md) traces the actual default Agentd embedding through the App Server and governance installation. That path selects Shadow; its bootstrap `NotEvaluated` decision is allowed in both modes. The generic tool API carries Allow/Block, and the model-provider attempt lease does not establish a current FinalUse PQ lease.

Changing the enum to Enforce would not repair this missing owner relationship. Existing user approvals, sandbox constraints, network policy and provider controls remain in force. This is a finite source finding, not a claim that every tool bypasses its other controls, and not a complete inventory of all effects. The ordinary automation HTTP/PoN migration is a separate component and cannot close the generic tool/provider finding by itself.

The [separate interface assessment](ordinary-pq-owner-interface-assessment.md) examines 21 fixed-source files. The existing ephemeral-input guard is consumed immediately before its HTTP attempt, but its contract and implementation concern federated-input currentness and explicitly do not confer provider authority. It cannot be relabelled as PQ authorization for WebSockets or other requests. A proper bridge needs an opaque, one-use owner capability, propagation through ordinary admission and physical attempts, and current PQ owner injection in the ordinary host composition. This bridge has not been implemented by the automation patch.

## Remaining joint conditions

| Gate | Current boundary |
| --- | --- |
| Fixed joint candidate | Final complete Hepta source, configuration, dependencies, actual execution images and ordinary process behavior must be verified together with frozen C3. Component passes cannot be inherited by a new commit. |
| W1 and public liveness | The original bounded x64 rejection collector and reader passed on C2; its applicability checks phase failed at 300 seconds. C3 must rerun the original checks, four-kernel collector, legal-strategy-v3 experiment and hosted service gate. |
| Current PQ for effects | Ordinary automation controls and the generic tool/provider owner bridge require separate evidence. Current operator root custody and all critical sinks are not qualified by local signed fixtures. |
| Recovery and unknown effects | Whole-store restore, physical process crash windows, current authority and independently retained frontiers must be validated together with the stable provider operation. Controlled store reopen is not physical host restore. |
| Complete model adoption | Current-source authentic model/owner/snapshot inputs have not been obtained and verified in this run. Earlier transfers or small synthetic closures do not qualify this candidate. |
| Learning quality | The historical attempt [41951536925](https://github.com/TrillionniumFoundation/Trillionnium-Chain/actions/runs/41951536925) spent its one authorized trial and accepted zero of twelve phases. No trial reset, model update or qualified no-update receipt is issued here. |
| Storage and growth | Paid retention, renewal, repair, GC and ledger/log growth have not passed one joint affordable budget. The unused-digest optimization passes its two component controls, while repeated historical decoding still grows quadratically. |
| Independent long run | Multiple independent administrators, real WAN and failure domains, fixed load and acceptance criteria require actual deployment evidence. Agents, loopback tests and one administrator's machines do not supply it. |

This evidence directory records component provenance and limitations. Every later joint execution must name its own exact source commit/tree, dependency/configuration identities, run attempt and observed execution images. Keep the frozen candidate unchanged while its original gates are pending; publish subsequent receipts separately.
