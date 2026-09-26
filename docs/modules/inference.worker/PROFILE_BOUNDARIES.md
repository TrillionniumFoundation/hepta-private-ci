# inference.worker profile boundaries

This module has three public capability classes. They are intentionally not interchangeable.

| Profile | Public state | Default product surface | Execution-evidence ceiling |
|---|---|---:|---|
| `HostedAppServerWorker` | production-candidate source | yes | May supply repository composition evidence after exact final-use authorization and terminal observation; it is not deployment, real-provider or release approval. |
| `LocalModelWorker` | experimental / non-production | no; requires `experimental-local-model` | Cannot supply product execution evidence until signed resource grants, attested real weights/device use, aggregate resource control, durable recovery and target-hardware qualification are complete. |
| `LegacyReceiptBoundary` | validation-only | yes | Validates an already-observed request/lease/reservation tuple. It never proves that a provider, model, weight set or device ran. |

`codex_hepta_infer_worker_host::profiles` is the source-level closed-world declaration. `CURRENT_STATUS.json` is a tracked template; the qualification workflow generates an exact-candidate status receipt bound to the tested commit, tree and source blobs. A tracked template must never be cited as a passing run.

## Product caller rule

A product caller may compose only the hosted App Server profile. It must not enable `experimental-local-model`, import `model_worker`, inject a fake `ModelDriver`, or translate a legacy validation receipt into provider-execution evidence. Test and qualification harnesses may enable the experimental feature only when their evidence is explicitly labelled non-production.

## Promotion rule

Changing any profile maturity requires all of the following in one candidate:

1. source and contract changes;
2. closed-world profile and implementation-map updates;
3. exact-head and deterministic merge-candidate receipts on Linux and macOS;
4. target-host evidence for every claimed physical resource or provider boundary;
5. independent acceptance outside the component that generated the evidence.

Until those gates exist, source presence and unit tests do not promote a profile.
