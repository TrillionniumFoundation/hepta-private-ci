# Ordinary-branch consolidation: round 01

This is a partial review checkpoint for the requested consolidation. It does not claim completion of the full audit, a passing native Rust suite, a merge to main, or any remote branch deletion.

## Scope and protection

The captured census contains 7,615 branches: 7,225 ordinary branches, 389 protected HIA branches, and main. The protected set includes branches whose names do not contain HIA but descend from the HIA roots, plus historical protected aliases. Historical protected pins are retained. The newly created chrono/OTEL joint branch is protected by ancestry and excluded.

The candidate before this report covers 2,083 ordinary branch tips; 5,142 remain outside its history. There are zero intersections with the captured protected tips and the two HIA roots or retained anchor. Branch refs must be refreshed before any later write or deletion.

## Changes in this checkpoint

Eleven ordinary histories were merged with normal Git merges. Each original incoming parent is recorded in CHECKPOINT.json and retained as a real merge parent. The unchanged-tree merge, passive evidence merges, and source merges have separate review records. The initial fix propagates handoff-test errors and preserves original Windows diagnostic wrapper evidence without counting duplicate test invocations.

The source changes add bounded host audit diagnostics, a single sampled continuation clock, full NDU owner/receipt binding and overflow checks, byte-bounded UTF-8 settlement reasons, typed framework evaluation error causes, and shared-encoder request/generation provenance checks. A historical C2 result is corrected without changing its HOLD outcome.

Passive evidence is preserved byte for byte through documented compression or chunk storage. The original failed runs and scientific results are not relabeled. Original hashes and reconstruction checks are retained. No blob-size allowance or security-policy exception was added.

## Validation and remaining work

The collector regression suite passed 9 tests, bounded host diagnostics passed 6 tests, and the continuation suite passed 9 tests using real CPU Torch 2.8.0. The original blob gate passed for the 184 changed paths before this report. The repository formatter completed and changed only two NDU test files. These results do not establish native Rust correctness.

The four Agentd handoff tests and original NextUse timing diagnostic remain pending. A ROG build stopped for insufficient disk, and local monolithic test compilation received SIGKILL at both two jobs and one job; test bodies did not run. An isolated ext4 build on a host with more memory is in progress. Deadlines, assertions, overflow checks, and test selection have not been relaxed.

A separate, unfinished normal merge of the Windows integration history is under review. It is not included in this checkpoint. Its dependency audit and native platform validation are also unfinished. No result from that work is used as a passing result here.

Main remains subject to CI required and Architecture required. The baseline's Architecture gate passed and CI gate failed; those historical results cannot certify this candidate. No ordinary branch is eligible for deletion until its exact tip is reachable from the accepted main and it still lies outside the protected HIA set.

## Evidence files

CHECKPOINT.json records local commit/tree/parent identities, validation scope, and evidence hashes. The compressed JSON files contain the full captured ref census and the 1,792 independent frontier heads from the initial analysis. Decode them with Python's gzip module. They are inventories, not a claim that every independent code contribution has completed semantic review.

Publishing through the GitHub connector may produce different commit IDs because author and timestamp metadata are assigned by the connector. Each published tree and ordered parent list must be checked against the local normal-merge sequence before the integration ref is advanced.
