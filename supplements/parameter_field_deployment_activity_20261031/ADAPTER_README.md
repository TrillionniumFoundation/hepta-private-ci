# Portable admission and measured deployment review

This extension adds a real workflow and adapter to the four-file prospective
registration at `0ef83d0cbb0c50d147df93badc348c99555e357a`. Those four files remain
unchanged. `ADMISSION_PLAN.json` registers the additional operational semantics;
the original README and plan remain historical registration snapshots.

The only scientific-use entrypoint is:

```sh
/opt/runtime/venv/bin/python -B /work/addon/supplements/parameter_field_deployment_activity_20261031/adapter.py \
  --binding /work/binding/BINDING.json \
  --expected-binding-sha256 ACTUAL_EXTERNALLY_FIXED_SHA256 \
  --output /work/deployment_activity
```

The binding must refer to an already successful, fully closed original Actions
run. The current diagnostic Actions run must be distinct. There is no resume,
scientific retry, partial-population mode, gate override, or unchecked tensor
loader. An incomplete primary run cannot be admitted by this workflow.

## Freeze and activate without a self-reference

1. Commit this extension, its workflow, tests and admission plan before reading
   any actual deployment values. This is the additive registered code commit.
2. After the original run closes, prepare a binding JSON from actual provider
   metadata and sealed completion bytes. Commit it below this directory's
   `bindings/`. Its `addon.registered_commit` refers to step 1, so the binding
   does not need to contain its own commit hash.
3. In a subsequent commit, add or update `bindings/ACTIVATE.json` with the
   binding commit, path and externally held SHA256. A push runs the actual replay
   only when this activation file changed. Other code or documentation pushes
   run boundary fixtures and explicitly record `NOT_ACTIVATED`.
4. Alternatively, dispatch the workflow with all three binding inputs. A
   dispatch with no inputs uses the committed activation file if one exists.

The activation format is:

```json
{
  "schema": "hepta.parameter-field.deployment-activation.1",
  "binding_commit": "ACTUAL_FULL_COMMIT_CONTAINING_THE_BINDING",
  "binding_path": "supplements/parameter_field_deployment_activity_20261031/bindings/RUN.json",
  "binding_sha256": "ACTUAL_EXTERNALLY_FIXED_SHA256"
}
```

The adapter verifies all registered additive bytes against their actual Git
blobs and current pristine checkout, including the workflow. It also verifies
the original four files against the earlier prospective commit. The activation
and binding commits may descend from the code commit while its executable bytes
remain unchanged. An altered executable or extra untracked/ignored source file
causes refusal.

## Binding schema and actual input population

The binding object has exactly `schema`, `provider`, `producer_job`, `pins` and
`addon`. Its schema is `hepta.parameter-field.deployment-replay-binding.1`.

`provider` has schema `hepta.parameter-field.deployment-provider-request.1`,
the fixed repository `TrillionniumFoundation/hepta-private-ci`, integer
`run_id` and `run_attempt`, the full original `head_sha`, and `artifacts`.
Each artifact is exactly `{id, name, bytes, sha256, role}` with actual provider
values. The twenty roles are the seventeen original labels prefixed with
`barrier:`, followed by `terminal_metadata`, `final_scientific` and
`final_operations`. The latter two are the existing complete production
workflow deliveries, not substitutes for any of the seventeen barriers.

`producer_job` is the original configuration's actual Actions job identifier.
`addon` is `{registered_commit, files}`, where `files` maps repository-relative
paths to `{bytes, sha256}`. Include every Python file in this namespace, both
prospective/admission plans and `.github/workflows/parameter-field-deployment-activity.yml`.
Including the complete namespace is preferred. Binding JSON files themselves
are data inputs and are not part of the earlier executable source closure.

`pins` contains exactly these seven absolute `{path, bytes, sha256}` descriptors:

| Key | Original canonical path |
|---|---|
| `pipeline_config` | `/work/execution07/ops/registrations/initial/PIPELINE_CONFIG.json` |
| `primary_complete` | `/work/execution07/ops/COMPLETE.json` |
| `manifest` | `/work/execution07/raw/evidence_v2/verification07/MANIFEST.json` |
| `verified` | `/work/execution07/raw/evidence_v2/verification07/VERIFIED.json` |
| `terminal_closure` | `/work/execution07/ops/TERMINAL_CLOSURE.json` |
| `postseal_complete` | `/work/execution07/postseal/COMPLETE.json` |
| `lifecycle_complete` | `/work/execution07/pipeline_measurement/COMPLETE.json` |

All identities must come from the actual completed run and immutable provider
artifacts. Expected hashes are not learned from unverified scientific payloads.
The remaining finalizer, aggregate, initial/followup/endpoint registrations and
source pins are followed from these sealed bindings through the original gates.

## Admission order and portability

The workflow creates a finite eight-GiB container and restores the original
public Python build, package versions and exact Torch wheel. The adapter owns a
new runtime probe and refuses a different runtime or CPU build digest before
requesting scientific archives. It then independently retrieves and hashes all
nine original public assets without decoding them.

The fresh input process retains its actual diagnostic Actions producer and its
own measured cost. Its new `RESTORATION.json` is preserved without changing any
bytes under `assets_replay/CURRENT_RESTORATION.json`. The adapter then reconstructs
the original run's sealed registration copy at the canonical asset metadata
path. Both receipts independently verify the same nine actual input files and
public manifest; their producers and costs are never equated. The new receipt
states that the historical input archive was not downloaded or extracted here.
The original operational gate checks the original metadata against the original
producer, while `assets_replay/REPLAY.json` records the explicit historical replay
and the permanent location of the fresh preparation evidence.

`provider.py` verifies the actual completed successful run attempt, repository,
head, twenty unique artifact IDs, provider sizes/digests, expiry and creation
within the selected attempt. It streams the actual ZIP bytes and verifies every
digest. It follows only registered HTTPS redirect hosts and removes the API
token on every redirect. It performs no automatic transfer retry.

The final scientific and operational deliveries are reconstructed at the
original canonical paths, with original metadata bytes unchanged. The original
source is a separate pristine checkout at the producing commit. The addon
checkout is separate, and Python import resolution always places the original
source first; imported original modules must also have the expected file path.

The original operational function is used through an explicitly registered
portable adaptation. `types.FunctionType` creates a separate function using
the original code object and a copy of its globals; only `verify_ack` is
replaced. Original module globals, their objects, the function code, canonical
roots, metadata classes and cost checks are checked unchanged before/after.
This is a new operational adaptation, not a claim of identical inode semantics.

The portable verifier checks all eighteen actual downloaded ZIP populations,
manifests, members and hashes, ACK chain and producer identity, embedded previous
ACK bytes, and thirty-six original closed transport waits with their CPU
attribution. Original SDK provenance is compared with a fresh integrity-pinned
SDK replica. Original inode triples must be structurally valid and distinct;
they remain historical evidence. The newly downloaded archive inode is recorded
separately. No original inode number or hardlink layout is fabricated.

The original scientific gate then verifies the complete fourteen-job study,
thirty final scientific seals, aggregate prerequisites, original source and
protocol identities, literal manifest and finalizer ancestry. The original
postseal output closure, its actual owned wait4, and the final original lifecycle
owner closure are independently verified. The new reconstructed RAW/CAS bytes
are complete. Only after every gate passes can traces or tensors be decoded.

C trace rows are joined to `COMPLETE.paths` by checkpoint identity. Every shared
field must agree; the two first-divergence fields are then taken from the
completion inventory. The original checkpoint decoder uses CPU
`weights_only=True` and verifies its full state digest. No model is created and
no rollout is added. The already registered reducer supplies the scientific
interpretation limits, including unknown deployment counterfactual regret.

## Costs, failures and delivery

The current replay has its own actual Actions identity and a 90-minute internal
operational deadline. The workflow allows 120 minutes. Original scientific
deadlines and numerical gates are unchanged. Fresh runtime, public-input and
provider children have actual owned `wait4` receipts. A separate outer owned
child includes those phases, all decompression/hash/reconstruction work,
admission, safe tensor decoding, reductions and child output serialization.
Nested measurements are attribution and are never added to this inclusive cost.

Original-run wait4 records are checked as historical evidence and are never
added to new replay CPU. Launcher work, container/runtime/SDK installation and
the final workflow upload are separate scopes; unknown CPU remains unknown.
The final workflow artifact retains outputs, external bindings, actual new
measurements, provider receipts and failure logs for the requested ninety days.
It does not duplicate all downloaded scientific ZIPs, and does not claim that
this later delivery was measured inside the already closed replay child.

Any gate or execution error preserves partial new evidence and refuses later
scientific decoding. Negative or unknown original scientific and cost findings
are retained. A successful replay establishes descriptive activity only; it
does not assign benefit, adoption, a certificate or new independent samples.

Boundary fixtures run as:

```sh
python -B -m unittest \
  supplements.parameter_field_deployment_activity_20261031.test_activity \
  supplements.parameter_field_deployment_activity_20261031.test_provider \
  supplements.parameter_field_deployment_activity_20261031.test_portable \
  supplements.parameter_field_deployment_activity_20261031.test_binding \
  supplements.parameter_field_deployment_activity_20261031.test_asset_replay -v
```

These are synthetic engineering tests. A workflow without an activated real
binding does not establish actual artifact admission or a scientific result.
