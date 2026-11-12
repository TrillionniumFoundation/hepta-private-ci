# Checker reply integrity at callback boundaries

Baseline: VERIFY-4 `88deb8a490565fd9b55851ba4581c9516fd1029f`.
The original recovery path checked reply identities before authentication but
then consumed the same object after a callback could rewrite it. A frozen
dataclass alone does not prevent `object.__setattr__`.

The repair validates all CheckerReply fields at consumption and compares the
complete canonical reply before/after both authentication and snapshot callbacks.
A changed reply leaves the original operation pending. An invalid input reply
is unknown and never becomes a consumable history observation. Neither path
redispatches the original checker. Original unmodified evidence can subsequently
reconcile the same pending operation.

## Actual counterexamples

`CHECKER_REPAIR.zip` retains original and repaired source/dependency bytes,
the reproduction driver, complete test logs and fresh-journal observations.

| Scenario | Original | Repaired |
| --- | --- | --- |
| Authentication rewrites fail to pass | Completed | Refused, pending |
| Authentication substitutes evidence digest | Completed | Refused, pending |
| Authentication changes measured cost | Completed | Refused, pending |
| Authentication changes numeric cost to bool | Completed | Refused, pending |
| Snapshot callback rewrites fail to pass | Completed | Refused, pending |
| Reply arrives with bool cost alias | Completed | Unknown, no observation |

Every independent scenario records exactly one checker invocation. The same
12-test suite produced six failing assertions/subtests against the original and
passed all 12 against the repair. The full combined candidate subsequently
passed 242 package tests before final formatting. The two reply-repair files
were unchanged by that formatting; published GitHub Actions remain the source
of platform qualification for each actual published head.

The scheduler digest changes with checker_dispatch.py. Old journals retain their
old frozen identity and must not be silently rebound to this code. This repair
does not isolate against an arbitrary malicious host, establish independent
custody or convert a probabilistic prediction into property evidence.

Archive SHA-256:
`e30d621af9a63cc2055e794da1f024fee7eb2eade485d346d45e89edbdcfeebb`.
