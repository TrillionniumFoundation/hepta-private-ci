# Strict test repairs, source gates and retained CI results

This package preserves the actual inputs, commands, source images, logs and outcomes for the 55 test and helper repairs. It also retains the two Windows probe corrections and the hosted CI observations used to review them. All earlier failures remain intact.

## Exact source and passing checks

The strict repair base is 4a5630661b1fee17582b452520c32fb5805831aa. The tested overlay tree is 701d4b8b99c555d2de90bbf94b727722e80c23cf. The source plan contains 55 paths and has SHA256 fef3249e553752b7d7588d9a1830566a54de138f07e3a63b675344b1a9dee03f. Each selected original and proposed source file has its real source path, byte length and hashes in the manifest.

The original format command passed. The original scoped fix command for Agentd and Memory passed with both strict unwrap and expect lints denied. All 13,819 selected native inputs stayed unchanged. The earlier failed compile and the three narrow type corrections are preserved separately.

The original caller CLI passed: 1,645 boundaries, 819 protected files and 7,602 Rust source files were checked, with no authority granted. The original B4 suite passed all 1,344 tests on the same overlay. All 14,777 source guard inputs stayed unchanged. The first B4 invocation failed with 408 errors caused by unavailable temporary storage, including secondary missing-file errors; its complete output remains. The second invocation changed only TMPDIR to a task-owned location. No test, predicate, timeout or assertion was removed.

## Full package failure and exact helper replay

The original full Agentd and Memory run remains failed: 1,947 tests ran, with 1,933 passes, eight failures, six timeouts and 193 original skips. The five clock failure regressions and six related router and private database cases passed. This package does not turn that full run into a pass.

Seven failures lacked real helper metadata. A clean snapshot with the same 13,819 inputs was used to build the actual codex and hepta-joint-propose helpers under the original 1,800 second preparation budget. Both helper verification phases passed. The seven exact original binary and test pairs then passed, with four threads, zero retries, the original 60 second per-test limit and 8 MiB stack limit. The final test execution took 10.334 seconds and explicitly skipped 1,620 other tests.

The outer audit process still exited with code 1 because its first census counted skipped events as executed tests. That original receipt and census are preserved. The separate census-correction-v2.json reconciles the seven exact pairs against the original nextest summary and the successful child command without rerunning anything. One evidence deadline failure and six timeouts from the full package run remain unresolved.

## Actual Windows evidence and narrow corrections

The hosted observations belong to bb6b57c100659d08778ecab34a8ce863725b2dda. The AppContainer probe created two real child processes, then failed reading token information class 46 before resuming them or executing the isolation matrix. Successful cleanup and the original unrestricted counterexamples are retained. These observations do not qualify the replacement isolation mechanism.

The API correction uses an exact DWORD result for scalar token information and preserves failures for unsupported classes and incorrect returned lengths. Nine controlled API tests passed on Linux; they are not native Windows tests. The final workflow correction uses one exact normalized lock fingerprint for the reviewed Neuron lock, Git blob 200595497ef61dde63767045dc4e8fdabbee80c7, with a fingerprint derived from audited source tree 1094c6a81d4e647767e670ef861ee75e9f1030a4. The active checks retain all 37 source pins and the exact normalized lock comparison. Sixteen actual source-snapshot positive and mutation cases matched their expected results. The prior 15-case version, all original failures, and the final one-line lock change are retained. No fallback fingerprint was added.

Four elevated Windows functional positives remain blocked by the unqualified admission mechanism. The Windows peer identity failures remain fail-closed. A separate CLI session timeout and the original download failure are recorded independently. This package changes none of those positive assertions or production guards.

## Hosted worker and check observation

The original worker job failed while downloading a Cargo registry dependency and produced no qualified worker or trajectories. Its original log and artifact remain. The root-authorized rerun of the same workflow completed its actual build and campaign. Its artifact ZIP has SHA256 042d5be48c25e9411d124415a5592de81bdac6d54ddf8fd87aa9d05895079c94 and contains 543 verified members. All 30 planned synthetic runs completed, ten pairs were matched, and the source identity and clean status were retained.

The campaign explicitly keeps scientific qualification at HOLD and production adoption at NoUpdate. It uses synthetic seeds, retains the Python owner during native worker restarts, and does not claim full owner cold recovery or real-task confirmation.

The complete saved check observation has 216 unique check IDs: 181 successes, 14 failures, 14 skips, six running and one neutral. Pagination was not atomic; raw initial and reconciled responses are retained. The failure inventory separates independent assertions, the shared admission and peer identity boundaries, dependency download errors, and aggregate failures. A requested Native Windows rerun was rejected because its containing workflow was still running; it did not start.

## Recovery and scope limits

Each originals.partNNN.gz file is a real independent gzip stream. Read manifest.json.gz, verify each carrier's byte length and SHA256, decompress the carriers in their listed order and concatenate the decoded bytes. Verify the resulting gzip archive against archiveBytes and archiveSha256, decompress it, and verify the tar stream against tarBytes and tarSha256. Read only the listed regular tar members and verify every original length and SHA256. Every original was restored and compared directly with its recorded sourcePath before this package was delivered.

The worker ZIP inside the archive is the untouched GitHub artifact; its member manifest and direct campaign summaries are also preserved. Native executables, environments, caches, Git indexes and full checkout copies are not included. The original helper manifests retain executable hashes.

These are scoped receipts for their exact source inputs. They do not qualify the later combined source commit, the full repository, pending Windows execution or pending hosted checks. This auditor performed no remote ref changes, workflow cancellations or reruns.
