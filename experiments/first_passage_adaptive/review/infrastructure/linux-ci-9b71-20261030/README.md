# Linux and Architecture failure coverage — candidate 9b71

This is a read-only audit of newly retrieved original GitHub Actions job logs. It does not rerun CI, compile a crate, or reopen a scientific confirmation.

The candidate is `9b71cf4e65194593d5e0fb2a507026d21527a740`. The GNU and musl blocking jobs actually checked out GitHub merge commit `9ad4d5a380642040aa215c0b1c4c9385ae4464d0`, merging that candidate into `71b4305c6619ed9faff98062f0ff7f932f4abfd0`. The Architecture source-head job tested the candidate itself.

## Inventory and coverage

| Evidence | Final result | Coverage in the current review snapshot |
| --- | --- | --- |
| GNU job 123485500277 | 16 failed runtime targets, 34 target/case pairs | Every category has an assigned repair scope. |
| musl job 123485500391 | 15 failed runtime targets, 33 target/case pairs | Every category has an assigned repair scope. |
| Both Linux builds | 50 downstream targets fail to build | Three independent compiler diagnostics: Matrix API, String error conversion, and CLI query depth. Bazel prints only five downstream labels. |
| Architecture source-head 123481634911 | Authority/browser step fails to compile | Only the same kernel-evidence String error conversion is observed. |
| Architecture required 123492981691 | Failure | Aggregate failure; it adds no separate runtime diagnosis. |

`FAILURE_COVERAGE.json` maps every final failed runtime target, its concrete cases and original line numbers to the current source repair. It also records the exact reviewed source hashes. These are coverage statements, not new CI passes.

Two states remain explicit in this snapshot. Canonical stable and experimental schema generation is in progress; intermediate generated files are not accepted as final. The five-agent supervisor timeout has a relevant absolute runfiles-path repair, but the original log omits the child failure cause, so that cause remains unproven until a new run supplies evidence.

The core environment-selection failure ended as **FLAKY** and is excluded. The qualification lease test passed on musl and is counted only for GNU. Repeated tails and retry occurrences are deduplicated. Actions, test targets, individual cases and repeated shard attempts are not treated as the same count.

The Architecture adoption/rollback, process-restart, derived-view and unchanged-source steps were skipped after compilation failed. They are not reported as successful or as additional observed failures.

## Reproduce the inventory without running tests

From this directory:

```sh
python3 parse_ci_logs.py original/job_123485500277.log.gz original/job_123485500391.log.gz --output INVENTORY.recomputed.json
```

The parser handles fully cached and partially cached summary rows, reconciles final target totals against Bazel's aggregate, associates both streamed logs and retained tails, and excludes final successful or flaky targets. The as-recorded `INVENTORY.json` was independently regenerated from the retained gzip files and compared byte for byte.

`original/` contains four gzip-compressed decoded UTF-8 job logs and their byte/hash records. All compressed files are below 256000 bytes. `WORKFLOW_METADATA.json` retains the run identities, job conclusions and Architecture step conclusions. `MANIFEST.json` records every delivered file. The raw decoded logs also remain in scratch; no historical log was reconstructed from memory.

`AUXILIARY_READ_REVIEWS.json` records the separate PTY fixture and authorized-read temporary-root source reviews requested during this audit. They do not establish a native Mac runtime pass.

Primary job sources: [GNU](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40883692430/job/123485500277), [musl](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40883692430/job/123485500391), [Architecture source-head](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40883692437/job/123481634911), and [Architecture required](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40883692437/job/123492981691).
