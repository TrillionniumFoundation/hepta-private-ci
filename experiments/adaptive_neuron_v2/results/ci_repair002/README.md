# CI repair002: complete prior-job inventory and candidate gates

The preserved workflows ran at `0d113abe0ead3b23a682c052583f4dd1381b9656`.
Repair mappings below are bound to local source snapshot `9da183aa9c97335c673003b9c5a9b8650df7e50a`.
**The candidate native matrix is not qualified, and the blockers are not all closed.**
A committed source change, an earlier successful job, or a Linux-only check is not a passing result for the candidate on another platform.

## Complete prior workflow counts

| Workflow | Jobs | Success | Failure | Cancelled | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Architecture convergence](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40677378085) | 3 | 1 | 2 | 0 | 0 |
| [V8 source build](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40677378157) | 15 | 1 | 2 | 12 | 0 |
| [Blocking CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40677378223) | 38 | 16 | 6 | 12 | 4 |
| Total | 56 | 18 | 10 | 24 | 4 |

`prior/jobs-head-0d113abe.json` preserves all 56 job names, IDs, authoritative job URLs, statuses, conclusions, timestamps and unsuccessful steps. `INVENTORY.json` maps those jobs to repair groups. Required aggregate failures are retained in the 56-job count; they are not separate diagnosed code faults. The previously green rust-ci result does not make the overall CI required check green.

There are 19 complete raw job logs, plus the official cargo-deny artifact. This is not 56 complete raw logs: in particular, 11 of the cancelled V8 job logs were not inspected. The original counts and failure index remain byte-for-byte under `prior/`. All 101 distinct named failures found in those logs map exactly once in `BLOCKERS.json`; attempts before retries remain distinguishable from final job conclusions.

## Committed repairs and remaining qualification

| Group | Repair commits | State / next gate |
| --- | --- | --- |
| Supervisor public lifecycle compile contract | `65cf0aa`, `e5e52c9` | Architecture source-head plus native restart_budget_recovery on candidate. |
| Durable automatic restart event sequence | `e5e52c9` | Native Windows restart_budget; local six-package attempts ran zero tests. |
| Queue fixture integration-crate visibility | `dcae334` | Native Windows queue_hook_fixtures and release build. |
| Queue hook, cancellation and crash-window fixtures | `dcae334` | Native Windows all queue_service cases; no reduced durability or ownership assertion. |
| V8 Windows cross-volume GN source build | `0540ba4` | Both x86_64 and aarch64 Windows ptrcomp-sandbox builds on candidate. |
| Concurrent V8 PartitionAlloc initialization | `b68715a` | Native code-mode-host and code-mode-runtime tests, especially Windows concurrency. |
| Core terminal ownership and snapshot readiness | `221c19c` | Native core-unit-tests on candidate, including both named cases. |
| Windows durable directory handles and private fixture directories | `9e4c682` | Native Windows affected targets, real owner lifecycle and durable reopen behavior. Local six-package compilation did not reach any tests. |
| Memory recovery canonical paths, flushes and migration fixture | `9e4c682` | Native Windows writable recovery, predecessor/epoch rejection and memory migration tests. |
| Lease lifecycle durable store availability | `9e4c682` | Native Windows complete lease lifecycle/reconciliation tests. |
| Historical automation migration order | `9e4c682` | Automation v1 forward migration test on candidate. |
| Canonical workspace binding during federated revalidation | `9e4c682` | Native ext/hepta-memory revocation and actual-send tests. |
| Short verified temporary roots and portable control fixture paths | `9e4c682` | Native Windows control/ranker and all four external-agent-migration cases. |
| Portable absolute path fixture for codex adapter | `9e4c682` | Native Windows thread-read recovery tests retain stable message/input and drift rejections. |
| Portable SSHSIG fixtures and explicit unsupported-platform contract | `9e4c682`, `e56bdeb` | Linux 24/24 passed; Windows fail-closed/durable branches remain unqualified. |
| Windows legacy deletion escape and broker qualification | `9da183a` | **Open native security gate:** real broker ordinary and broad Everyone/low-integrity deletion cases; no fallback or source-only closure. |
| Native sandbox helper runfiles and executable packaging | `2f6b3f6` | Native Windows helper_manifest and exec-server local/remote sandbox filesystem targets. |
| Darwin immutable release publication order | `169a01c` | Native macOS Intel/ARM release tests, incomplete publication rejection and duplicate preservation. |
| Fenced holdout CAS lock release with duplicate descriptors | `fb4cf4b` | Native macOS fenced-holdout tests plus duplicate-descriptor regression. Fork inheritance is a source-based explanation, not a traced runtime result. |
| Blocking accepted socket in HTTP redirect fixture | `9e4c682` | Native macOS route-aware redirect test; no timeout relaxation. |
| Wine PTY helper lifetime and complete output drain | `348d7ab` | Native musl/Wine full 13-test target including remaining lifecycle guards. This source fix does not prove every timeout cause. |
| Opaque app-server-protocol target failure | No inferred repair | **Unresolved inner detail:** full candidate protocol log and schema check required. |
| Opaque app-server and exec test shard failures | No inferred repair | **Unresolved inner detail:** Windows app-server/exec complete test artifacts required. |
| Cargo-deny 22 error diagnostics and regenerated dependency closure | `836731b` | Local all-features deny 0 errors and focused 5/5; candidate consumers/matrix pending. |
| New Linux synchronous-keyring transaction qualification | `3f3f454`, `836731b` | New Linux keyring transaction tests/consumers require candidate runtime evidence. |
| Cancelled/skipped matrix and complete failure evidence | `7ab62b5`, `331796a` | 24 cancelled +4 skipped remain unqualified; full candidate completion required. |

`BLOCKERS.json` contains the exact job URLs, observed failures, code changes, mapped test names and representative original log excerpts for all 26 groups. Source repairs deliberately retain ownership, durable flush, timeout and failure assertions.

### Windows deletion boundary remains a native gate

The prior Windows run observed actual outside deletion by both a capability-token fixture and a real legacy `cmd.exe` process, including a protected `.git` directory. The repair rejects legacy managed filesystem launches before environment/ACL/token/child setup. The low-level capability-only token now rejects an already filtered base and requires explicit object access grants; its traversal privilege is explicitly documented. These changes do not prove the elevated broker safe.

The broker acceptance suite must pass `broker_cannot_delete_low_integrity_outside_paths_with_broad_everyone_grants` as well as the ordinary writable-root test. The adversarial owned outside sibling grants Everyone `DELETE`/`FILE_DELETE_CHILD`, carries a read-back low mandatory label on parent/file/directory, and requires a child integrity SID of at least 4096. A refusal caused merely by a low-to-medium integrity mismatch must not be counted as policy confinement. The identity-inclusive broker still needs its own exact-candidate native result.

### Omitted output and cancellations remain unresolved

Windows job 122780464767 skipped 1,126,789 bytes of app-server-protocol output because it exceeded the old 1 MiB UI limit. Job122780464727 recorded failed app-server shard 3 and exec-all shard 1 attempts without the inner test footer before cancellation. No guessed test-level fix is assigned to these targets. The repaired wrapper preserves complete `test.log`/`test.xml` and the first failure beyond the console tail so the next run can resolve them.

The approximate 60-minute main-job and 30-minute V8 durations match the old workflow limits; timeout is an inference, not a retrieved cancellation-reason field. Both matrices used `fail-fast:false`. Check-run annotations were unavailable through the connector route; no branch-protection or administrative inference is made.

## Local qualification evidence

| Recorded run | Result | Tests ran | Wall s | Descendant CPU s |
| --- | --- | ---: | ---: | ---: |
| `operator-test001` | passed_linux_only | 24 | 17.092393 | 29.883396 |
| `ci-wrapper-qualification001` | passed_wrapper_only | 12 | 1.663919 | 1.565669 |
| `native-repair-tests001` | build_failed_environment | 0 | 74.104389 | 159.095969 |
| `native-repair-tests002` | build_failed_storage | 0 | 172.331320 | 456.918356 |

The two six-package native attempts both failed during compilation/linking: **zero tests ran**. Attempt001 could not discover OpenSSL because the `pkg-config` executable was absent. Attempt002 supplied the installed OpenSSL paths, then hit linker SIGBUS and `No space left on device`; its bound source hashes remained unchanged. Those outcomes are neither test passes nor evidence that the repaired native behavior failed at runtime. The original FAILED receipts, raw stdout/stderr and source bindings are preserved.

The operator run built a fresh isolated target at the recorded Rust 1.96/source identities, then passed 24 tests with 0 skips. The wrapper log records 12 passing tests but its original START receipt lacks a commit/hash binding; the receipt is preserved without backdating such a binding. No additional compilation or test rerun was performed for this inventory.

Local CI/engineering wall/CPU totals and their limits appear in `LOCAL_EVIDENCE.json`. They are **separate from the scientific SNN/owner/Organ Credit resource ledger**. Nested build costs must not be added to their enclosing launch. Hosted CI billing, authoring time and dependency-repair engineering time are not included in those four-stage totals; no Joule or complete-project-cost claim is made.

## Verify preserved raw evidence

Each hosted log and the original cargo-deny ZIP are losslessly gzip/base64 encoded into numbered chunks of at most 256 KiB. `RAW_LOGS.json` records every chunk hash and the compressed and original byte identities. Local small logs remain in original byte form under `local/`; no trimming, newline conversion or ANSI removal was applied.

```python
from pathlib import Path
import base64, gzip, hashlib, json
root = Path("experiments/adaptive_neuron_v2/results/ci_repair002")
manifest = json.loads((root / "RAW_LOGS.json").read_text())
for name, item in manifest["files"].items():
    chunks = [(root / part["path"]).read_bytes() for part in item["parts"]]
    for part, chunk in zip(item["parts"], chunks):
        assert len(chunk) == part["bytes"]
        assert hashlib.sha256(chunk).hexdigest() == part["sha256"]
    packed = base64.b64decode(b"".join(chunks), validate=True)
    assert hashlib.sha256(packed).hexdigest() == item["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert len(raw) == item["bytes"]
    assert hashlib.sha256(raw).hexdigest() == item["sha256"]
```

The raw round-trip and all existing byte/SHA receipts were verified when this inventory was created. Add candidate CI results as a new record bound to its actual published head; retain this historical inventory and failed attempts.
