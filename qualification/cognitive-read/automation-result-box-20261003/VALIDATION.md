# Crate-private Automation reconciliation payload

The coordinated TaskFlow repair is adapted to this branch's older, unboxed
AuthorizedEffectRecoveryResult. Only the private Agentd outer Observed variant
is boxed; both constructors allocate that box and the existing wire conversion
consumes its payload. The owner's public API, dispatch request, recovery guards,
observation states, control response and persistence format are unchanged.
The newer TaskFlow branch already has an inner Box and must forward it instead;
its whole commit is deliberately not imported here.

Two direct tests exercise all three provider observations through the actual
wire snapshot converter, preserve all snapshot fields/serialized bytes, and
retain rejection of a missing observation. Existing owner and process tests
remain required. New-source Rust execution awaits hosted qualification; scoped
formatting and whitespace checks pass. No live provider or trust installation
was used. This isolated source stage does not include the separately reviewed
Agentd public Intelligence Rust-payload migration.
