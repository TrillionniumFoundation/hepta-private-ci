# intuition.policy developer entrypoint

Use these documents together:

- [`TECHNICAL.md`](TECHNICAL.md) — base module contract, calibrated decision semantics, compatibility interfaces and architecture context.
- [`QUALIFICATION_V3.md`](QUALIFICATION_V3.md) — authenticated current-generation qualification, canonical signed profile, learned-scorer ownership contract, frozen-data validation and fast-policy benchmark gate.
- [`IMPLEMENTATION_MAP.json`](IMPLEMENTATION_MAP.json) — source ownership, native symbols, tests and the remaining product/external evidence gates.

For new production composition, `qualification::decide_qualified_v3` is the required source boundary. `decide_calibrated` is historical V1 replay/compatibility and `decide_calibrated_v2` is bounded request-binding compatibility. Neither V1 nor V2 authenticates the current production profile by itself.

Source qualification does not imply product activation, promotion or release. The implementation map intentionally keeps those claim boundaries false until a product caller, independently provisioned trust anchor, target-host evidence and operator acceptance exist.
