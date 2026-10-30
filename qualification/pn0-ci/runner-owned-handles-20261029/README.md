# PN0 managed runner handle ownership follow-up

This source change continues the existing PN0 production-chain work. It supplies
no filesystem admission, token, model or installation authority. Human-authorized
local root remains the sole integrator, committer and normal pusher of the two
original docs branches. ROG's actual base HEAD remains
`d3284e385e2b6037dd86752ddd246b616144a87c`; this candidate is uncommitted WIP.

The published source input is `bf36d10a54db1d9453409a432cb4641c9fbe38e8`,
tree `803e1e9b12efa4dd236ecd99333a717b5d52b033`. Its actual PR preview is
`c4f58e535d69a8748484df722743e279cbb1dea5`, ordered parents c38e772 then bf36,
with that same tree. The changed runner file has identical preimages on bf36
and d328; a context match does not qualify the integrated root tuple.

## Actual producer and consumer

The existing `spawn_runner_transport` creates two native server pipes. Previously
the first remained a raw handle when the second fallible creation ran. Failure
of that second call leaked the first. Each successful result is now uniquely
adopted into `OwnedHandle` immediately. Existing error cleanup closes in then out,
and success consumes the same owners with `File::from` into `RunnerTransport`.
No handle is adopted twice or duplicated for this transfer.

The existing connection worker duplicates its own actual thread handle so the
parent can cancel that operation. Previously a failed channel send or an early
`?` return could bypass its manual close. The duplicate is now uniquely adopted
before sending; the channel moves that owner, and failed or abandoned sends
release it. The parent only borrows that same handle for wait and cancellation.
All return paths release the acquired duplicate through the original scope.

The actual consumer remains the existing elevated runner transport. No new
public helper or prepared authority is introduced. Original token/ACL and
`CreateProcessWithLogonW` arguments, process cleanup, credentials, pipe security,
fifteen-second deadlines, five-millisecond polling, join/detach decisions and
test bodies remain unchanged. The filesystem guard still refuses admission.

## Actual checks and retained failures

The attached raw outputs and terminal records distinguish compilation from
execution. The command was the original project-default invocation:

`just clippy --locked -p codex-windows-sandbox --lib --target x86_64-pc-windows-gnu`

The repository expands this through `cargo clippy --tests`; its actual output
includes library and command-runner test conditional compilation. No test was
executed. No `-D warnings` success is claimed for this command.

The first attempt exited101 after 22.451403658 seconds because `aws-lc-sys` could
not find the real cross C compiler. Its complete 42,785-byte failure is retained.
Six official APT-index hash-matched compiler packages were then downloaded and
their data extracted into the task's workspace. No system installation or package
maintainer script ran. A real Windows-header COFF compilation probe succeeded;
that object was not executed. Package bytes and the extracted compiler cache are
not included in this evidence directory; their sizes and hashes are recorded.

With only the real compiler added to the task's PATH, the identical command
exited0 after 86.880132146 seconds. All source hashes were unchanged. Its complete
28,567-byte output preserves unused prepared-mechanism, type-complexity and CMD
diagnostic warnings. No lint waiver, feature, dependency, lock, assertion or
workflow was changed. This is not a clean strict-lint CI result.
Compilation used the recorded d328 WIP dependency graph; it does not qualify
bf36's complete graph, V8, native ABI/release or a later integrated source tuple.

Final `just fmt` exited0 after 0.259820914 seconds, with every recorded source
byte unchanged. No tests were rerun after formatting. No earlier model, worker,
SDK, supervisor, PN1 or native execution allocation was reopened. The two actual
Clippy command durations sum to 109.331535804 seconds; this is not whole-process
resource or hard-quota accounting.

The current bf36 four-lane native run40789310118/a1 was independently reread,
including four official ZIPs, 220 members, all 8,115,051 bytes of complete job
logs and the original result chains. Every lane still has original20=18PASS2FAIL
for broad-identity-delete and legacy-delete-boundary. Query6/6 and terminal1/3
are separate controls. Four nested FAILED lines are two original cases with two
attempts each. Those are bf36 original failures, not new candidate execution.

## Remaining dependencies and original acceptance

The worker can still outlive its caller while holding a raw pipe alias. Original
cancel/detach behavior is unchanged; this source does not prove helper termination,
eliminate every stale-handle risk, or establish successful OS reclamation. Process
PI, Job, termination reconciliation and Unknown custody remain OPEN. RAII drop
does not itself prove native cleanup success.

The ambient-read-preserving full token/read producer and actual complete runner
owner consumption are still missing. Full token, bounded read fixtures and DTOs
cannot replace the original ambient-read/deletion contract. Keep the production
guard closed, without restoring Everyone/Logon restriction identities or enabling
an unqualified full token.

Original actual child exit1 is still unexplained. Failed image query31 is UNKNOWN;
parent builder arguments are not child argv or image evidence. This patch neither
changes the private CMD helper nor claims to repair its original failures.

Local root must integrate against fresh refs, retain active CI, bind the actual
source/preview/main qualification and perform all original native checks on its
new tuple. Ordinary three-round model installation, genesis, I09/I10 custody,
next-task readback, release, PN1 and independent WAN gates retain their existing
order and bounds. `task_complete=false`, `merge_ready=false`, **NO_GO**.
