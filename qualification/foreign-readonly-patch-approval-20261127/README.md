# Foreign read-only patch approval classification

The Linux Core Wine fixture selects a Windows executor and a Windows
`PathUri` cwd. Host-native permission matching rejects that foreign cwd.
The existing fallback then supplied an unrestricted filesystem policy to
patch safety classification, even when the selected environment declared
no write authority. For the fixture's read-only profile and OnRequest
approval policy, that classification can return AutoApprove and Skip
instead of asking for patch approval.

The fallback policy is only an approval-classification input. It is not
stored in ApplyPatchRequest. The orchestrator and runtime independently
use the original selected environment profile and workspace roots for
execution. The old fallback therefore does not itself demonstrate an
unsandboxed write or an executor enforcement bypass.

## Narrow change

Pass the original permission profile to the existing fallback. Preserve
its filesystem policy only when the cwd is not host-native, the policy
is Restricted, and none of its entries declares write access. Existing
safety logic then asks under OnRequest and rejects under Never. Read-only,
deny-only and empty restricted policies share that classification.

Policies with any declared write entry retain their previous executor
first behavior, including foreign workspace permissions. Explicit full
access, disabled and external enforcement profiles are unchanged. This
does not add general foreign-path permission matching or decide whether
a particular declared writable root covers a particular patch target.
The executor still receives its original profile. Windows Unsupported
handling, sandbox selection, explicit approval and retry paths are intact.
The successful host-native permission-matching path is unchanged.

## Controls and evidence

Three authored unit controls parse a real add-file patch and call the
actual fallback and preparation functions. Their foreign cwd is a Windows
URI on Linux/macOS and a POSIX URI on Windows. They cover read-only,
deny-only and empty policies under OnRequest and Never, and the unchanged
workspace, explicit root write, literal write, disabled and external
profiles under both policies. A separate host-native workspace path in
the third control calls effective_patch_permissions successfully and
retains bounded auto-approval. Existing foreign executor integration
tests and the original CodeMode approval test are byte-for-byte unchanged.

The retained GNU and musl attempts each fail the CodeMode approval case
three times. Actual actions were local and uncached. Their generic event
timeout does not identify which of TurnStarted, patch approval, or final
TurnComplete was missing. The source conditions explain why initial
approval can be skipped; they do not retrospectively prove the failed
wait phase. All original timeouts, attempts and success assertions remain.

No native control was executed while preparing this candidate. Source
review and formatting do not establish a successful Wine run. The next
normal qualification run must exercise the preserved integration test
and the new classification controls.
