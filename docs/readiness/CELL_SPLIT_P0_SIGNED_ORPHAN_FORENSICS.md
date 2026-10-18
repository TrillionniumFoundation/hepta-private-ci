# Canonical P0 signed orphan Control/CNS forensic readback

**DRAFT / DENY_ALL / read-only / no physical Cell Split.**

This candidate transplants the original source-reviewed P0 diagnostic from
PR #2644 (donor `a16988911b6c63a5350c4a438fc93fdf389f31ce`) onto canonical PR #2684
(frozen parent `fefcd5caa6c4e6e2b0028b7e2dfaec5babbd3c54`).

The authoritative Control WAL source is byte-identical in both branches.
Three CNS runtime/ABI/test files were verified to share their original
pre-change Git blob identities and their complete donor Git blob bytes are
reused. The diagnostic combines:
- An original fsynced and unresolved Control Begin from a private pinned
  WAL, with independently pinned predecessor and successor NDU snapshots;
- A separately signed original CNS committed receipt and a live
  nonce-challenged signed successor route at an exact durable CNS revision;
- Three reads of original Control state and two signed CNS readbacks to
  reject changed state, owner identities, unacknowledged or stale effects;
- An explicit sealed `NonAuthorizingPosture::DENY_ALL` typed result.

No new native writer is introduced. The diagnostic never appends Control C,
consumes Final-use, mints a generation fence, retries unknown native
effects, mutates the route, or authorizes model promotion. Even a successful
forensic result is not a distributed transaction or a production recovery
receipt. The original pending Begin stays unresolved.

The original 3 focused native fixture tests, B4 no-bypass regression,
scope regression, and fail-closed exact-source Architecture command are
included. The original Control WAL native suite is required to run serially
(`--test-threads=1`) to prevent concurrent test-fixture OS lock timing
from masquerading as valid protocol behavior.

Still blocked: authenticated single-owner Control B→native signed
CNS effect→C, independently held Final-use, remote Supervisor generation
fence, third-party monotone anti-rollback witness, physical power-loss
recovery, prospective NDU/negative-transfer and all 16 target-host runs.
