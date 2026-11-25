# External local sufficient-statistic hook

Each physical host supplies its own UTF-8 JSON artifact. No training samples or local feature matrices need to pass through the controller. The controller may distribute a common frozen model and unlabeled coordinate calibration before local data generation.

The exact schema is:

```json
{
  "record_kind": "pft_local_sufficient_statistics",
  "schema_version": 1,
  "node": "ai395",
  "dimension": 21,
  "seed": 271901,
  "parent": [0.0],
  "coordinates_sha256": "SHARED_COORDINATE_HASH",
  "objective": {"ridge": 0.01, "loss": "half_sum_squared_residual"},
  "feature_provider_sha256": "SHARED_PROVIDER_SOURCE_HASH",
  "shared_capsule_sha256": "SHARED_FROZEN_MODEL_HASH",
  "batches": [
    {"batch": 0, "count": 32, "data_hash": "LOCAL_DATA_HASH", "gram": [[0.0]], "moment": [0.0]}
  ],
  "timings": {"data_feature_seconds": 0.0, "gb_seconds": 0.0},
  "evidence": {}
}
```

The abbreviated arrays above must be expanded to the declared dimension. There must be exactly four local batches numbered 0–3. The node is the exact string `ai395` or `pocket4`. The integer seed and dimension must match the protocol invocation. All parent and statistical values must be finite. Ridge must be a positive, finite numeric value, excluding booleans. The declared objective regularizes every action coordinate, including an intercept if present.

For every batch, `gram = X.T @ X` and `moment = X.T @ (y - X @ parent)`. The final candidate is `parent + action`, not `action` alone. Coordinate identifiers must bind the feature order and any centering/scaling. Both hosts must use identical calibration parameters; independently standardized local features cannot be added as if they had the same coordinates.

The protocol verifies declared parent, coordinate, provider, capsule, objective, source, and round identities. It does not attest the truth of an external provider's provenance claims. Separate provider receipts must bind the actual executable source, frozen capsule, local dataset hashes, and runtime to each artifact. The free-form `evidence` object is retained, including any train/calibration provenance and exclusions.

The initiating host runs `ssh_runner.py --config PRIVATE_CONFIG.json`. A new round requires an unused result directory or round prefix. Configuration keys are:

| Key | Meaning |
| --- | --- |
| `local_model`, `peer_model` | Absolute paths to the unchanged pinned `multihost.py` helper |
| `peer_code_root` | Absolute peer directory containing the same three frozen protocol files |
| `peer_python`, `proxy_python` | Explicit existing executable paths |
| `local_result_root`, `peer_result_root` | Task-specific result directories on the respective hosts |
| `round_prefix` | New experiment identity, distinct from previous experiments |
| `cases` | List of `[dimension, seed]` pairs |
| `local_external`, `peer_external` | Local artifact path patterns; `{size}` and `{seed}` are substituted |
| `local_source`, `peer_address` | Privately configured authorized endpoint addresses checked against the actual selected socket |
| `required_transport` | `usb4` for the qualified existing direct link |

The SSH peer alias remains the existing configured `pocket4`; the process runs on `ai395`. Authentication uses its existing identity and strict host-key policy. No credentials or raw addresses belong in the public archive. A frame is limited to 16 MiB. Dimensions 21, 41, 81, and 161 fit the intended SmallHCSN readout study; this is a transport capacity statement, not evidence of model quality.

Precomputed `data_feature_seconds` and `gb_seconds` are carried from the local provider. They are not inside the protocol runner's elapsed interval. Report provider wall time, protocol wall time, and post-seal evaluation wall time separately, with overlapping work on the two physical hosts marked explicitly. A new real-model study must seal all candidate/result hashes before generating its held-out tests.
