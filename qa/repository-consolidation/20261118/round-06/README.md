# Native owner repairs and bounded dependency migration

This stage starts at candidate `b373b72709c2c5bea0d4e751f922cf98af966f8c`.
It composes independently reviewed, source-bound native repairs and the real
RMCP 3.9.0 and external-agent dependency migrations. It does not attach an unresolved branch as a
parent. Candidate coverage remains 2,059 of the 7,239 ordinary branch names in
the pinned census. The remaining 5,180 names still require integration.
`main` has not moved, no branch has been deleted, and protected HIA/Cell
histories are outside this stage.

## Native retained-state and fixture repairs

The retained observation cache previously used a shared try-lock for readers
and refresh validation. Normal concurrent reads could therefore report an
unavailable cache and permanently fence a worker. The repair retains immutable
snapshots in `ArcSwapOption` and serializes publishers separately. It samples
the prior clock watermark before reading the clock, so concurrent samples
that finish in reverse order do not resemble an actual clock rollback. An
odd/even revocation generation detects a complete update crossing a read.

The existing 500 ms lifetime, clock ceiling, boot/epoch/lease binding,
revision monotonicity, revocation checks and permanent fencing remain. Three
deterministic concurrency cases supplement all four original cache tests.

The native qualification also exposed invalid test grants and an expiry
endpoint error. Fixtures now issue their original grants within the unchanged
300,000 ms production ceiling. The original work window is 240 seconds and
the independently signed training window is 180 seconds, retaining a real
signature-expiry-before-work-expiry interval. No issued authorization is
renewed. The checkpoint fixture waits to the first invalid millisecond after
the inclusive expiry second, retaining its original pause bound.

The final behavior source is commit
`bd7e4c6e643c52e104ef6b7c6e334206557a2968`. Maintenance commit
`527b17514817c3b154cd47bec011f4876eea6597` contains only three equivalent
`is_multiple_of` lint rewrites. The full final source patch and exact source
bindings are retained here. The combined Cargo lock adds the native
`arc-swap` edge together with the dependency migration.

## Complete RMCP source and time compatibility

The workspace uses a complete, provenance-bound RMCP 3.9.0 source distribution
under `codex-rs/third_party/rmcp-3.9.0-time`. It retains the upstream license,
source, examples used by the tests and the original test suite. Five ordered
patch carriers preserve the time migration, safer local fixtures, repository
formatting, two comment spelling corrections and JavaScript fixture formatting. Every retained upstream
source postimage has a recorded digest.

The date implementation uses `time::OffsetDateTime` and preserves UTC offset
formatting, grouped fractional precision, extended signed years, and flooring
of negative Unix milliseconds. Raw `lastModified` strings remain unchanged.
The typed annotation constructors now accept `OffsetDateTime`; the repository
has no callers using their former typed argument. Timeout diagnostics retain
zero, fractional and maximum-duration behavior. Native, JavaScript and Python
interop tests ran against the actual source.

The resolver fixtures preserve the production policy chain while supplying a
test client with explicit loopback DNS and no proxy. They assert that the
negative resource metadata request really reaches its local fixture and that
the proxy trap receives no request. The original rejected attempt is not
reused as evidence of success. The completed runs used a network namespace
with only loopback, no external route, a normal user, no effective capabilities
and `NoNewPrivs` enabled; dependencies were prefetched before offline execution.

The two final spelling edits change only comments. Complete Rust executable
token equality was checked before updating the provenance and adding the
fourth patch carrier. The fifth carrier formats four JavaScript fixtures;
their complete normalized Babel syntax trees remain identical, with source
coordinates removed and equivalent noncomputed property names normalized. The original qualification package remains byte exact.

## External-agent import compatibility

The external-agent package now uses the same workspace `time` dependency. Its
import parser retains the former strict separator choices, Unicode minus in
offsets, leap-second integer mapping and pre-epoch flooring. A differential
oracle includes the actual source module and compared 282,254 inputs with
Chrono 0.4.45; every result matched. Three added regression tests include thirty
accepted and rejected examples. Only this package's Cargo dependency edge
changes, with no locked package version or checksum changes.

The first complete isolated execution passed 170 of 171 cases. Its existing
official marketplace inference test attempted to clone a live upstream source.
The repaired fixture first asserts the exact inferred official request, then
substitutes a temporary local marketplace as the download source. It still
executes the real marketplace addition and all original result assertions. The
production entry point calls the same implementation with the original adder.
The second run passed all 171 cases, with no ignored cases or retries, and an
exact test-list/JUnit match. Both original attempts are retained. Scoped
`just fix`, `just fmt` and canonical Bazel lock generation completed afterward;
the canonical Bazel lock remained unchanged.

## Actual source-bound validation

| Scope | Result | Qualification limit |
| --- | --- | --- |
| Cache regression suite | 7 passed | Native cache source |
| Original six-package ordinary suite | 2,682 passed, 184 original ignored | Complete original workflow package selection |
| Original Root suite | 68 passed, no skipped JUnit cases | Complete original 68-parent list, real UID/bind/pidfd/SCM_RIGHTS fixtures |
| RMCP date and resolver suite | 23 passed | Six date and seventeen resolver cases |
| RMCP complete native suite | 1,601 passed, four original live Keycloak cases ignored | 94 binaries, zero retries, exact test-list/JUnit correspondence |
| External-agent complete native suite | 171 passed, no ignored cases or retries | Complete package library selection in the isolated network namespace |
| RMCP consumer compilation | Passed | Actual RMCP client and Matrix SDK consumers |
| Source maintenance and lock generation | Passed | Scoped `just fix`, `just fmt`, locked metadata and canonical Bazel lock |

The native six-package inventory has no removed cases compared with the prior
2,672-case run. Ten added cases comprise the three cache regressions and seven
already-integrated fixture/temporal cases. The exact case delta is included.
The Root execution used the operator account's existing authority; it did not
change host security policy. The native source inventory and helper digests
were bound before and after execution. Large compiled helper binaries are
represented by their exact digests and build/verification records.

The original diagnostic native run had two real failures, one in each of its
ordinary and Root suites. Both original logs and JUnit reports remain in the
bundle. They are distinct from the final successful execution. Behavioral
tests preceded maintenance; the final compile-only check followed maintenance.
These scoped results do not establish that the complete subsequent integrated
tree or any untested platform has passed its required hosted gates.

## Existing workflow formatting repair

The parent candidate's hosted Prettier job reported one workflow file,
`.github/workflows/hepta-memory-ai-matrix-shadow.yml`. Prettier 3.5.3 reformatted
that file and its complete parsed YAML value is identical. No job, dependency,
permission, condition or check was changed. The workflow-specific formatting check is recorded separately from the
broader local scan, which also encounters preserved historical evidence.

## Original evidence custody

`evidence-manifest.json` binds every original archive, tar stream, file, mode
and carrier by byte length and SHA-256. Each carrier is independently gzip
encoded and smaller than the existing blob limit. Concatenating its decoded
payloads recovers the exact original archive. The three bundles retain 237 original files. The manifest retains original
failed attempts and full fresh JUnit/raw logs alongside terminal job witnesses.

The restore helper verifies all bytes and membership before writing. With no
output argument it only verifies; with an output argument it creates a new
directory outside the repository. It refuses path traversal, duplicate members,
symbolic links, nonregular members and excessive expansion.

```sh
python qa/repository-consolidation/20261118/round-06/restore_evidence.py --bundle rmcp-native
python qa/repository-consolidation/20261118/round-06/restore_evidence.py --bundle native-ci
python qa/repository-consolidation/20261118/round-06/restore_evidence.py --bundle external-agent
```

The full Codespell 2.4.3 scan passed with the unchanged workflow arguments.
The existing blob-size gate also passed, with no allowlist change.

Required hosted checks must pass on the final candidate before merging into
`main`. Ordinary branches may be removed only after their freshly observed
heads are reachable from that merged `main`. Protected HIA/Cell branches remain
excluded from both operations.
