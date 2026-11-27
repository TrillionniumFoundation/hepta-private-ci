# Windows network request validation

This candidate is based on `0a64b1b2be83d2b6724899cb66c1e63b94ede6ac`.
It restores the existing error priority for an invalid managed-network request
without enabling any Windows managed filesystem backend.

## Observed failure and change

The original Windows test
`restricted_token_rejects_managed_network_before_spawn` expected the existing
managed-network configuration error. The new filesystem availability check ran
first and returned `Unsupported`. Both paths refused execution, but the request
validation contract changed.

A private validator now reads only the supplied sandbox-level enum, proxy flag,
and optional restricting-SID presence. It preserves the two original errors and
their priority. An explicit elevated request passes this validation as before.
The public dispatcher calls this validator before the unchanged availability
check. The existing selector reuses the same validator; its permission, path,
and environment resolution remains after the availability check in the public
execution path. No ACL, token, account, helper, or process operation moves ahead
of that check.

## Controls and unchanged boundaries

All original tests and assertions are retained. The four existing refusal tests
still contain their original 40 asserted entry-point calls. Those calls supply
no managed-network proxy or restricting SID. They retain the same unavailable
backend expectation; they are four tests, not 40 independent native cases.

One new test invokes the public dispatcher with both network fields set, with
only the restricting SID set, and with both fields on an explicitly elevated
request. It checks the original error priority or typed `Unsupported` result as
appropriate. After each call, the existing fixture checks its namespace,
outside-file contents, child marker, uncreated configuration home, and complete
retained security descriptors. These controls have been authored but not run.

This is an error-classification fix. The original exec-server process-write,
cloud-managed CLI, desktop, token, and ACL-setup functionality failures remain
open. In particular, the exec-server failure occurs at process start before
stdin write; switching it to an unmanaged process would discard its isolation
assertion. No fallback, token flag, ACL permission, timeout, retry, skip, or
poisoned-lock recovery is added. The five secondary poisoned-lock failures stay
recorded as consequences of the earlier ACL-test panic, not independent proof
of five backend defects.

Validation for this candidate is limited to source review and the recorded
formatter, spelling, and diff checks. No new Rust compilation, Windows native
test, CI run, or remote publication was performed.
