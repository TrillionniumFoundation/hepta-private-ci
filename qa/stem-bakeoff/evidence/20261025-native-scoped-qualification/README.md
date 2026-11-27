# Qualified native source, examples build, helper and prepare evidence

## Completed evidence covered by this package

| Record | Result | Scope |
| --- | --- | --- |
| Rust qualification006 | **651 passed; 13 skipped; exit0** | Six crates, 54.325 s test phase / 96.520 s full command |
| Native example build001 | **exit0**, 2.782 s | Both native_memory_daemon and native_memory_shadow built with locked dependencies |
| Actual filesystem helper001 | **exit0**, 0.015085 s | Built v1 example, empty environment, real fs/canonicalize response |
| Original driver prepare-owner | **exit0**, 0.215011 s | One actual prepare invocation, retained CognitiveStore anchor |
| Historical Python wire tests001 | **4 passed**, exit0 | Separately recorded source head and Python runtime; 0 training/model calls |

All model-call counts in this archive are limited to these completed records and are **zero**. The parent v1 pipeline had proceeded to training when collection occurred; its training, decoder execution and later outcomes are **excluded** and must be accounted for separately. No claim is made that the whole v1 pipeline performed zero model calls.

## Source identity and build pins

- Published/build head: `8a47cdd26574a85cd314fabce65cc395dbe316a8`; tree: `e5fc7789c9bc74919cb6ac0d37894f688e09526d`.
- Qualification006 originally recorded base HEAD f214 with the candidate in its working tree. The complete 9,704-file before/after maps are retained and identical within that run.
- All9,704 tested content hashes match the subsequent build snapshot. Alignment restored17 already-published evidence files, all under qa/stem-bakeoff/evidence; no runtime source was added.
- The original alignment map hashes symlink bytes, while test/build maps follow file symlinks. The sole representation difference is vendor/bubblewrap/LICENSE: link text COPYING hashes to400d38e5..., and the referent contents hash to b7993225.... Both values and semantics are explicitly verified in alignment/hash-semantics-bridge.json. The raw maps are not falsely declared byte-identical.
- Build001 retains its full log, source maps, actual rustc1.95.0 verbose identity and binary SHA/size receipts. Binary executables themselves are not included in this small archive.

| Built binary | Bytes | SHA256 |
| --- | ---: | --- |
| native_memory_daemon | 479624264 | `e3e923ae95118dcb09f866b325b2e108a717f60bdb11e255b4d2213012820470` |
| native_memory_shadow | 76122376 | `0b48a4cdf49bd7f32fce4de35df6ef2998d98276fda88925dd29fedf719e8d7d` |

## Actual helper and preparation boundaries

- The helper request, stdout, empty stderr and receipt are preserved. Its binary digest equals the build receipt. The exact response is `{"status":"ok","payload":{"operation":"fs/canonicalize","response":{"path":"file:///"}}}`.
- This direct helper entrypoint test demonstrates that the example can re-exec its filesystem helper without daemon-only environment. It does not by itself prove sandbox enforcement or AppServer readiness.
- prepare-owner was invoked by the original driver, once, against its existing designated preparation root. Its request, exit/timeout receipt, stdout, stderr, prepare.json and anchor.json are copied as fixed files. The recorded anchor SHA256 matches both prepare.json and stdout.
- No live SQLite database, running-model directory or in-progress parent pipeline log was copied. Preparation is not a trained-model call, and successful preparation is not AppServer readiness.

## Repairs and independent review

- The v1 entrypoint patch and before/after source are retained with independent review. It dispatches existing helper modes before configuration/runtime startup, treats prepare independently, binds private home before normal arg0 initialization, and passes real Arg0DispatchPaths to Agentd. The original fixed training/model/data/control recipe is preserved.
- The withdrawal patch binds source content to the exact forget reason and retains distinct assertions for revoked authority and a real tombstone. Both corrected files match the qualified006 snapshot.
- The completed006 log contains exact PASS lines for the helper regression, post-recovery writer host, remember/recall/correct/forget product flow and owner-bound late-withdrawal fixture. Selected lines are indexed without removing the full log.
- The pretrained shadow probe source review is retained with its original reviewed head and explicit limits. The older4-test wire receipt likewise retains its original source head; it is not relabeled as a new run on the published head.

## Runtime dependency freeze

- The verified installed-package freeze contains28 entries,478 bytes, SHA256 `d7679c0e602ea0deedf39d02d09085c4d44953df8523f1b8fe45b899c4184e59`.
- Root reports obtaining it with uv and an explicit writable cache under /tmp. Two earlier metadata attempts produced empty output files because the venv lacks pip and the default uv cache was read-only; those empty files are retained.
- The failed command argv/exit/stderr receipts were not saved alongside those files. method.json labels the causes as root-reported and does not manufacture missing evidence. These metadata attempts are not model execution.

## Preservation and limits

- All raw logs, receipts, maps, source patches and reviews retain their original bytes; generated indexes and the identity bridge are separately named.
- archive-members.json records every member SHA256 and size. The deterministic tar.xz has only relative regular files, fixed uid/gid/mtime and read-only modes. The external manifest binds its final checksum.
- Earlier failure archives remain unchanged; this successful source qualification supplements them rather than replacing negative evidence.
- This package closes the recorded source/test/build/helper/preparation checks. It does not establish successful pretrained decoding, parameter-memory quality, native AppServer readiness, production Objective/NDU authority, calibrated SignalReceipt admission or the wider memory-system blockers.
