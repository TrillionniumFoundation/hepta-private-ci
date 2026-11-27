# Match readiness and activation to managed execution availability

Base: `04235def3c18aad1ba5044d84ddd17494cc646ec`, the separate draft
filesystem-execution refusal branch. This change is local source preparation;
it has not been adopted into the public base or qualified by a new native run.

The existing execution guard returns `Unsupported`. Previously, a configured
restricted-token mode or an old completed elevated-setup marker could still
produce a `ready` response. Core could skip the elevated setup and persist the
mode, and the TUI could enable a mode after a failed legacy preflight or through
the completed-marker shortcut.

The readiness RPC now uses its existing JSON-RPC error channel for unavailable
managed execution. Disabled and non-Windows responses retain their previous
behavior. The response enum and all schemas remain unchanged. External clients
must handle a method error; this source review does not qualify their behavior.

Core checks the same availability boundary before setup or configuration
persistence. The existing setup acknowledgement and completion notification
remain: an attempted setup reports `success: false` and its error. The TUI
activation sink clears its busy state, reports the failure, and returns before
success telemetry, configuration writes or in-memory mode changes. Neither path
changes token flags, host ACLs, permissions or fallback policy.

New API controls cover disabled readiness, both configured modes, and rejection
of both setup modes with a complete synthetic installation marker. They compare
the complete response/notification and original configuration bytes. A Windows
TUI control exercises both activation events, checks the prior configuration,
mode and permission context, and snapshots the refusal notice. Original tests,
deadlines, read-only warning inspection and execution-attempt guards are retained.

The synthetic setup records belong only to each temporary test home. They do
not provision accounts, decrypt credentials or claim a working installation.
No Windows filesystem isolation positive case or original outside-delete failure
is repaired by this availability consistency change. Tests and snapshots are
prepared source, with execution still pending.
