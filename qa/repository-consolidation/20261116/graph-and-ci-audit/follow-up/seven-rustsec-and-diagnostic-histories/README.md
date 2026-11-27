# Seven reviewed parent histories and terminal CI evidence

The audited candidate is `cf29f0c335b8884b5598ae136b0cfc861e2587c0`, with tree `89857f3bad99ac3974549092ee6292b022a7178b`. Seven ordinary original parents are retained after the preceding evidence commit `0056393b71b415b07a8016c23fedc4313fdd35f3`. Canonical server metadata and exact Git commit bytes are retained for every new merge.

## Source and conflict decisions

The four first histories cover three RustSec changes and the original Selector start-clock ordering. The resolved source adds the original paired-lock test, retains the historical RustSec receipt, and adds the exact original advisory-rejection regression to the existing stronger guard tests. The current ctutils 0.4.8 locks, production guard and complete caller manifest pair remain unchanged. The current Selector already starts its clock before its first journal read; its current private implementation, signatures, readbacks and completion fence are preserved.

The three later histories preserve a temporary Bazel print diagnostic, a resolver workflow tied to an old fixed candidate, and a tracer-dependent lock inheritance experiment. Their entire original sources and deltas are retained. They introduce no active source or CI change. The ordinary merge previews have two actual conflicts, both resolved explicitly with the current exact files; the clean old-workflow addition is explicitly retired from active CI.

The current lock guard releases its lock in the owning process even when another description remains open. Its PID check and all current lock regressions stay intact. The old external-tracer experiment is not registered as a current ordinary test, and no real traced-child execution is claimed.

The original pre-merge reviews label their per-path conflict status as not computed. Those original reviews remain unchanged. The later canonical addendum records the actual previews, return codes and conflict paths.

## Executed validation and scope

The original RustSec test command passed all seven tests, the original paired-lock command passed its one test, and the original policy, formatting, spelling and receipt-formatting commands passed. All 13,855 frozen source inputs remained unchanged. These three Python and historical-record paths did not cause another native Rust or B4 run; the earlier source validation and its exact scope remain in the preceding evidence bundles.

The candidate graph covers 1,900 of the 7,230 ordinary branch heads observed in the 07:22 UTC snapshot, leaving 5,330 pending. At this freeze, the integration ref still points to `eeefbc864e6a254e9085d542c1e6c3647e1c881d` and main to `732e934ba496d90fbe042b8d41d479ef901643e5`. No branch deletion or main update is represented here.

The full 07:22 UTC snapshot contains 7,465 heads. All 234 protected HIA and Cell branch names, including 50 newly observed siblings, are excluded; all 243 current, historical and marker pins are outside the candidate ancestry. Immutable commit metadata proves the 50 siblings extend the already protected s96 chain. The externally advanced HIA example-validation branch retains its previous protected parent. Only metadata was inspected; no protected source or ref was changed. The original twenty ordinary-name exceptions retain their audited classification.

## Original hosted CI findings

All 220 checks for the previously published head ended naturally: 179 succeeded, 11 failed, 15 were cancelled and 15 were skipped. Rust Analyze succeeded, while the independent CodeQL check failed. The retained complete analyses contain 194 Rust results and four Python results.

All 21 visible annotations match actual source-analysis results: eleven cleartext-logging and ten hard-coded-cryptographic-value findings. Their rule scores are not conclusions about exploitability. The full SARIF traces, annotations and exact source objects are retained; no alert was dismissed or suppressed. Full result triage remains separate work.

Four Windows original regressions encountered the production `ElevatedWindowsSandboxIsolationUnavailable` error. The backend refuses before permission resolution, ACL changes or child launch because its replacement filesystem isolation is not qualified. The original tests and this unconditional production refusal remain unchanged. The job also exceeded its original 65-minute limit; that cancellation is distinct from the four earlier test failures. This bundle grants no native Windows qualification.

The actual PR-base blob-size gate is still pending complete object retrieval at this freeze. The older incremental gate is not represented as the full PR-base result. The original checker, allowlist and 512,000-byte threshold remain unchanged.

## Lossless original recovery

This package retains 262 original files as 184 unique SHA-256 objects. The archive is split into 32 independently compressed carriers; every carrier remains below the existing file-size threshold.

1. Verify each compressed carrier with `carrier-index.json`.
2. Decompress each carrier and verify its raw size and SHA-256.
3. Concatenate the raw data in offset order and verify the complete tar.
4. Read the embedded original manifest and restore each original from its content-addressed object, verifying its size and SHA-256.

All original streams were actually recovered and compared byte for byte after archive creation. Every original file was checked again for changes. Git indexes, caches and unrelated mutable workspaces are excluded.

The original manifest SHA-256 is `69c5fadbcd7c21c29b12ad181802897f8d38b17d31f821ff18ef23ce1ae8c5b7`.
