# intuition.policy V3 frozen qualification corpus

This directory contains repository-controlled inputs used by the `codex-hepta-intuition` frozen-data qualification test.

- `frozen_model_v1.json` is a serialized deterministic learned-scorer artifact with an explicit feature schema and fixed integer parameters.
- `frozen_validation_v1.json` is the frozen in-domain/OOD validation corpus used to calculate calibration ECE and OOD false-acceptance rate.

The test does not inject predeclared ECE/FAR numbers. It parses these files, runs the model over the frozen rows, calculates metrics, derives canonical calibration/OOD/model/profile digests, signs the resulting policy qualification and exact candidate completeness payload with a deterministic CI-only Ed25519 key, and executes `decide_qualified_v3`.

The deterministic key is test material only. It is not a production trust anchor and grants no dispatch, promotion, release or effect authority.

A production qualification run must replace both artifacts with deployment-controlled immutable artifacts, bind their exact digests in deployment configuration, provision the verifier key independently, and retain the target-host qualification report through the normal evidence and operator-acceptance paths.
