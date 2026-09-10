# Hepta engineering control

This source root provides deterministic, bounded work-envelope scheduling and
integration eligibility. It deliberately has no merge, deployment, runtime,
promotion or release capability.

The source-complete Lane G implementation is `control_engineering_v2`. Its
machine-verifiable component closure, design-to-native traceability and detailed
implementation semantics are in that package's `COMPONENTS.json`,
`TRACEABILITY.json` and `IMPLEMENTATION.md`. The original
`hepta_engineering_control.py` remains the compatibility reference for existing
callers; new durable composition uses the V2 package explicitly.

Verification from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  test_hepta_engineering_control.py \
  test_integration_identity.py \
  test_control_engineering_v2.py
python3 lane_g_validate.py
```

Successful verification proves only the bounded repository-owned source slice.
Independent semantic acceptance, target enrollment, production activation,
canonical selection, promotion and release remain separately governed.
