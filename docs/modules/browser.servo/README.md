# browser.servo module documentation

The normative module guide is `TECHNICAL.md`. The current implementation hardening and Servo-worker decisions are documented in:

- `HARDENING.md`
- `ADR-0001-private-worker-transport.md`
- `ADR-0002-inherited-private-channel.md`
- `ADR-0003-hepta-owned-servo-embedder.md`

`IMPLEMENTATION_MAP.json` remains the machine-readable design-operation to native-source map. The current JavaScript implementation is a hardened driver/effect boundary; it is not a qualified Servo worker or production deployment.
