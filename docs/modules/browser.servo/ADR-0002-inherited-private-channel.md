# ADR-0002: inherited private browser-worker channel

Status: accepted design; platform implementations pending.

Canonical Servo pin: `84bcc9ac701874fa9819e5cdee06356b961d736c`.

## Decision

The browser host creates the connected control endpoint before child launch and passes only that endpoint plus one-use startup material to the expected child.

- Unix: inherited connected Unix stream or socketpair.
- Windows: supervisor-created one-client named pipe with an explicit user/process ACL.
- No TCP/UDP/HTTP/WebSocket listener.
- No raw WebDriver/CDP command surface.
- No startup secret in process arguments or ambient environment.

The channel is generation-bound and closes on wrong startup capability, profile/session mismatch, owner-epoch drift, sequence replay or protocol violation. Transport reconnection never authorizes a second dispatch of an operation whose first effect is indeterminate.

## Follow-up gates

The worker artifact digest, source/build receipt, OS sandbox, resource ceilings, no-listener/no-egress observations and real WebView revision fencing remain mandatory before runtime qualification.
