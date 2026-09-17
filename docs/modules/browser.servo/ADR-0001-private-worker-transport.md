# ADR-0001: private Servo worker transport

Status: accepted design; implementation and target-host qualification pending.

Canonical Servo pin: `84bcc9ac701874fa9819e5cdee06356b961d736c`.

## Decision

A production `browser.servo` host uses one supervisor-owned Servo worker process per admitted browser session for the initial implementation. The control boundary is private and inherited; it is not a TCP, HTTP, WebSocket, WebDriver or publicly discoverable Unix-socket service.

Every command binds protocol version, profile/session identity, process generation, authority epoch, page/document generation, operation identity and canonical payload digest. Unknown mandatory message types, oversized frames, sequence reuse, generation drift and authentication failure close or fence the channel.

The public browser vocabulary remains typed and bounded. Raw WebDriver passthrough, arbitrary JavaScript evaluation, raw cookie/storage/profile export and unrestricted preference mutation are outside the admitted C1 surface.

External network access is denied until a separately qualified egress policy is installed. A successful JavaScript driver test does not establish that OS property.

## Required qualification

The real worker must prove no control listener, bounded private transport, parent-death cleanup, generation fencing, no blind replay after uncertain effects, isolated profile roots and target-host network/credential containment.
