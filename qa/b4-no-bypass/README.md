# Privileged caller source checks

`CALLERS.toml` declares the privileged boundary inventory and the exact product
source files permitted to call each boundary. `KERNEL_AUTHORITY_BOUNDARIES.json`
independently classifies the original contract types and their callers. Changes
to either inventory require reviewing the actual caller's authority and recovery
checks; the lists must never be populated merely from a failing test's output.

The original protected Root assembly includes these reviewed paths:

- `production_protected_host.rs` requires the authenticated Current owner,
  writer binding and exact recovery cut before binding its protected checkpoint
  and constructing the original writer.
- `production_root_composition.rs` supplies the original Root proof and
  recovered consumer frontiers to that constructor.
- `authority_host_runtime.rs` opens the protected lease registry and performs
  explicit trusted initialization/registration. Initialization still reports
  `production_ready: false`.
- `deployment_issuer_root.rs`, `deployment_writer.rs`, and
  `authority_host_issuer.rs` verify the retained lease revision/binding and enter
  the original live dispatch fence. The deployment writer uses its witness
  helper; ordinary observations cannot substitute a registration or new grant.
- `production_authority.rs` opens a consumer with the configured issuer keys;
  `root_authority_session.rs` applies the original revocation head to consumers.

Common caller markers are supplemented by per-owner protected-file markers.
The fleet's existing identity/witness requirements remain explicit. Constructor
families and the existing named lease receivers are scanned alongside qualified
calls, so the additional reviewed paths do not leave those forms unobserved.

External test helpers must keep privileged constructors under their own
`#[cfg(test)]` item when they are scanned independently of the parent module.
`objective_sender_test_support.rs` remains a test-only fixture. Removing that
guard, or changing it to a production-capable alternative such as
`cfg(any(test, unix))`, must expose the call and fail the closed set.

Run from the repository root:

```sh
python3 -B scripts/verify_hepta_callers.py self-test
python3 -B scripts/verify_hepta_callers.py verify
python3 -B -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'
python3 -B -O -m unittest discover -s qa/b4-no-bypass -p 'test_*.py'
```

Keep failures for unexpected callers, missing checks and production-capable cfg
alternatives. Never add a broad test-helper filename exemption or a production
caller entry for a fixture. The scanner and independent checks are lexical
source evidence, with bounded type/receiver analysis, rather than full Rust
name resolution or a complete runtime call graph. Passing them does not establish
deployment authority, live revocation availability, native execution, durable
recovery, or permission to replay an unknown effect. Those remain separate gates.
