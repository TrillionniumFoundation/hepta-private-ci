# ADR-0003: Hepta-owned Servo embedder

Status: accepted design; worker crate not yet present in the current tree.

Canonical Servo pin: `84bcc9ac701874fa9819e5cdee06356b961d736c`.

## Decision

Do not expose upstream servoshell/WebDriver as the Hepta authority boundary. Build a minimal Hepta-owned worker against the pinned public Servo embedding API and retain a narrow one-process/one-session/one-WebView state model.

The worker dependency graph must exclude a general WebDriver server and other unnecessary automation/control surfaces. Any Servo patch must be checksum-bound, narrowly justified, independently reviewed and carry a deletion/upstreaming condition.

The JavaScript host currently implements the admission/reconciliation side of this boundary. It does not prove that the Servo worker, rendering loop, target-OS sandbox or network/credential containment exists.

## Acceptance boundary

A Worker source topology, successful build or artifact digest is still insufficient by itself. Runtime qualification requires the exact launched binary, private channel, OS isolation, real WebView behavior, external-effect reconciliation and target-platform fault evidence.
