# App-server publication ordering candidates

These changes address two observed app-server failures from source
`97ab00451799667faebac2c455a1e3176ebc90cb`. Format checks have passed; independent
source review is recorded separately. These changes have not yet been compiled
or executed at this source cut.

## Catalog publication observer

The production catalog writer uses `codex_utils_path::write_atomically`: it
creates a temporary file in the cache directory, writes it, then publishes the
known `.json` path by rename. The test helper previously enumerated and read
every directory entry. A temporary name could disappear between enumeration
and read, producing the observed `ENOENT`; an incomplete temporary file was
also outside the published catalog contract.

The helper now reads published `.json` entries. Errors reading or parsing those
entries still propagate. A new regression creates a real `NamedTempFile` beside
an existing catalog, checks that the temporary payload is excluded, persists it
over the published path, and checks that the replacement becomes visible.
Malformed published JSON must still fail. The startup test's original timeout,
poll interval, request counts, and final catalog assertions are unchanged.

## Loaded-child resume response

Restoring a parent-owned child through Core emits a thread-created notification.
The app-server processes that notification asynchronously. A resume response can
reach the existing listener before its watch record has been marked loaded,
even though Core has restored the child. The observed cold response reported
`NotLoaded`; the subsequent warm response reported `Idle` with the same complete
authority tuple.

The response handler now verifies that the Core manager still contains the
exact `Arc<CodexThread>` used by the listener and that its actual status is not
`Shutdown` or `NotFound`. Missing, replaced, and observed closed runtimes use
the existing closing error. Only then does the listener register the loaded
watch record before composing the response. Existing running, permission,
user-input, and error facts remain intact.

This request has passed the calling path's checks. The handler still retains its
later pending-unload, page construction, subscription, and cursor error exits;
registration does not imply that every response validation has succeeded.

The first candidate registered immediately after owner restoration. It was
withdrawn: the app-server list semaphore does not prevent Core residency
eviction, so a later `NotRunning` result could leave a new watch record without
a newly attached listener. Registration now occurs within the already attached
listener's resume command.

Normal shutdown updates Core's `AgentStatus` before enqueueing
`ShutdownComplete`. The listener awaits each resume command and handles that
event in the same loop. An observed shutdown is rejected before registration;
a normal shutdown published after the check is processed later and clears the
watch state. This ordering is not an atomic Core residency lease and does not
claim to repair every abnormal thread-death or replacement path.

The owner-controlled restore path, configuration override checks, paging,
usage replay, subscription checks, original complete identity assertions, and
all existing time limits are unchanged. Warm resumes use the same verified
listener registration path; repeated registration keeps existing status facts
and does not emit a duplicate unchanged-status notification.

Four deterministic lifecycle regressions reuse `core_test_support::test_codex`,
the real Core manager and thread, the actual app-server listener, and its
existing resume command. They cover an initially unregistered loaded runtime
returning `Idle` and later observing real shutdown, observed shutdown rejection,
missing manager entry rejection, and a live `Arc` mismatch rejection. The last
control uses distinct real threads; it is not a same-ID eviction/reload
experiment. The current-thread runtime queues the command before yielding to
the listener, whose existing biased command branch precedes queued events.
No production hook, additional dependency, sleep, retry, or new timeout is
introduced; execution remains subject to the existing test-runner limits.

## Evidence and remaining qualification

The GNU and musl jobs retained byte-identical failed logs and matching remote
action digests, execution start times, and wall times for these failures. Their
Bazel invocation IDs differ, and both report `cache_hit=false`. These are shared
remote-result observations, not two independent platform reproductions and not
evidence of an ordinary cache hit.

Required follow-up is the original app-server qualification on the new source,
including the catalog publication regression, startup refresh test, child cold
and warm resume assertions, and normal resume/shutdown coverage. No new pass is
claimed by this document. Original failed artifacts remain retained.
