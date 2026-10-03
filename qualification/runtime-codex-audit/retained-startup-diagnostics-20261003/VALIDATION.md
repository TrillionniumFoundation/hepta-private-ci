# Retain causal startup diagnostics within the existing output bound

Exact runtime `246aa1bf9cb4c990a723d412d4e5b548ccb8f6f7` Agentd job
111157418897 again reached 14 daemon passes, two failures and one timeout.
The cognitive product case now gets through its physical projection assertions
and reaches daemon restart at `cognitive_product_e2e.rs:401`; two-agent isolation
also fails at its restart at `supervised_two_agents.rs:111`. Their child errors
are still hidden by the helper's last-4096-byte stderr output, which contains
backtrace frames instead of the original cause. The supervisord case times out.

Only the test harness diagnostic formatter changes. It retains a bounded head
and tail with an explicit omission marker, preserving at most 4096 decoded bytes
per stream and consuming at most 8194 stream bytes. Invalid UTF-8 cannot expand
the output cap, and valid code points are not split. Small streams remain intact.
No production logging, process lifecycle, retries, readiness, timeout or security
policy changes. Historical output already discarded by the supervisor's own
bounded queue cannot be reconstructed by this formatter.

Six std-only Rust tests compile the exact helper with `rustc --edition 2024
--test`; all pass without building the workspace or restoring a shared target.
Four of the first five behavior tests fail against the extracted original tail
algorithm. The existing real-child integration test additionally requires the
original error prefix and final marker, unchanged exit17/failed lifecycle and
prompt termination. It and the six pure tests are included in the existing
hosted daemon suite. Actual new-source child/process execution is pending;
29 Python workflow/selector/oracle/candidate checks passed locally.

## Independent prior-stage execution result

The separate exact recovery selections at246aa1 passed1 owner current-cut case
and1 real Agentd product-writer case, plus57 prior selected memory tests and
standalone strict memory-library lint. Artifact11268642062 (run37107014778)
ZIP SHA-256 `4578fb1e13e9932f0725f5e1b7f18f4cfd0e433b3545ca1c8db63c2082743436`,
all18 command-record/log hashes, unchanged tested identity and reconstructed
archived Git tree were verified. The original233 inference/59Python/2crash/1soak
selections also passed. Lane B, unrelated map drift/ancestry, five paused AuthBus
lint errors and current-main merge construction still fail. The protected
acceptor rejects the source bundle at04-lane-b. These exact recovery passes do
not establish passing daemon restart or overall product/independent acceptance.

All paused AuthBus/state/workspace-lock paths and registrar/publication remain
unchanged. No trust provisioning, live effects, activation or release.

Published diagnostic source `df5a0a0bf13f1abfbd02f4a5e87a0392e3c9d5d2`, tree `670c39ca8588c8d2347df62cf32c1005f71350ee`, is bound by three directly affected observations: runtime.supervisor, runtime.agentd and kernel.operations. Every historical identity, claim flag and closure path is unchanged; the other two selected observations remain valid and all other maps are byte-identical. Clean-checkout validation is repeated after committing this metadata.
