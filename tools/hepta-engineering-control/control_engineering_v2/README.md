# control_engineering_v2

`control_engineering_v2` is the bounded Lane G source implementation for
`control.engineering`.

Read these files before composition:

- `IMPLEMENTATION.md` for the trust, state, failure, recovery and capability
  model;
- `COMPONENTS.json` for the exact machine-verifiable component set;
- `TRACEABILITY.json` for design-operation to native-symbol and test bindings.

The public package supports work-envelope issuance, fenced path leases,
dependency-aware scheduling, exact Git evidence verification, bounded candidate
sandboxing, independent-review requests and consent-bound dormant assimilation
proposals. It does not support self-review, self-acceptance, self-selection,
self-merge, activation, promotion, release, peer enrollment or credential
propagation.

Run from the parent directory:

```sh
python3 lane_g_validate.py
python3 -m unittest -v \
  test_hepta_engineering_control.py \
  test_integration_identity.py \
  test_control_engineering_v2.py
```
