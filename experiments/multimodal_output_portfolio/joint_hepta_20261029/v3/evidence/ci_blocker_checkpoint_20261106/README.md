# NDU CI blocker evidence checkpoint

This package preserves 129 evidence files, totaling 22,325,273 original bytes.
The deterministic archive is 9,546,496 bytes, split into 22 original ordered
segments of at most 450,000 bytes. Each segment now travels inside its own
independent gzip container, at most 450,158 bytes including the container.
The original index, segment hashes, combined archive hash and all 129 evidence
file identities are unchanged. TRANSPORT.json records the exact outer containers.
The existing 512,000-byte repository blob policy is unchanged.

The combined archive SHA-256 is
`ae9647dc661b979b2412467c7a9a977fd0f76558ba117b83995f49d6c79c455a`.
The index SHA-256 is
`2c5910ea845b0b54362370ea325791d6ce799f8f974c0c22807bb5cefe1ad6c1`.

## Restore and inspect

From this package directory, run the following with a new destination whose
parent already exists:

```sh
python3 restore_evidence.py /absolute/path/to/new-evidence-directory
```

The program verifies the pinned index and transport record, each outer container,
each decompressed segment, the combined archive and every extracted file. It refuses existing destinations, unexpected or duplicate
members, links, noncanonical paths, and mismatched bytes. Material is restored
as inert data; no archived script or native command runs automatically.
`ROUNDTRIP_VALIDATION.json` records a complete actual restore, verification of
all 129 files and all five original artifact ZIP digests, and negative controls
for an existing destination, a corrupted part, and a changed index.

## Evidence map

After restoration, all paths are beneath `round3_ci/`.

| Path | Contents and boundary |
| --- | --- |
| `CI_LINE_CHECKPOINT.json` | Source-bound chronology, successful steps, remaining failures, and retrieval limitations at the checkpoint. |
| `evidence_original_logs/` | Six decoded original #4921 job logs, the #5013 Linux clippy log, the integrated-port producer failure, and their untrimmed UTF-8 identities. |
| `cargo-deny-host-diagnostic.zip` | Original same-source host diagnostic artifact. It is explicitly not the unavailable original Docker job log. |
| `pin_utils/runs/42215527276/` | First failed native proposal: unchanged ZIP, original job log, and API snapshot. |
| `pin_utils/runs/42216053462/` | Toolchain-corrected but still failed proposal, preserved separately with its unchanged ZIP and log. |
| `pin_utils/runs/42219101717/` | Successful proposal: unchanged original ZIP, log, API snapshot, and independent artifact validation. The ZIP contains all 15 command logs, including the complete original cargo-deny output. |
| `pin_utils/parent_inventory.json` | Complete verified inventory of 14,291 original leaves, including Git modes and blobs, bound to the fixed proposal parent tree. |
| `pin_utils/rules_rs*` and source proofs | Fixed official source archive, registry descriptor, retained external fact provenance, and strict source/graph proof. |
| `pin_utils/integration_5000_before/` | Exact three current preimages used to replay the minimal native product patch while preserving the supervisor dependency edge. |
| `units/05_pin_utils_proposal/` through `units/07_pin_utils_module_facts/` | All three exact proposal source versions, with their separate manifests and patches. |
| `08_pin_utils_product.manifest.json` | Complete 287-file product inventory, upstream archive/member provenance, modes, and native artifact binding. Product sources are reconstructible from the native artifact rather than duplicated here. |
| `fence_diagnosis/` | Original startup failure, the one accepted same-source/same-policy successful retry, and exact provenance. The optional version-maintenance candidate was held and not applied. |
| `port_diagnosis/run42222000674/artifact.zip` | Original integrated-port failure artifact, before any Cargo or Bazel generation. |
| `units/10_port_dependency_amendment/` | Frozen review candidate and its exact local checks. This checkpoint does not substitute for its later complete-head hosted qualification. |
| `product5013_API_SNAPSHOT.json` | Product run/job status and the independently verified prospective merge tree matching the published product tree. |

The first four published repair units retain their manifests, patches, and
qualification receipts. Original sealed protocol bytes are preserved in their
reviewed migration patch; the research measurements were not rewritten.

## What these results establish

The successful pin-utils proposal performed 15 real native commands, including
repeated lock generation and the original cargo-deny policy. The published
product #5013 also passed the original blocking cargo-deny job, contract gate,
and GNU MODULE-lock check. The independent rules_rs rrprd hub retains its two
original registry fact strings; removing pin-utils from the product workspace
does not mean it disappeared from all Bazel tooling.

The old integrated-port source record rejected exactly the three newly reviewed
manifest/lock identities. The frozen additive candidate preserves that old
record and strengthens source/consumer binding for the new vendor sources.
Local source checks passed; the retained wider cleanup test has three socket
subcases that could not run in this executor. Existing hosted checks remain
mandatory, and several native jobs on the earlier product head failed or were
cancelled. This package does not claim that all blockers or the final full CI
have passed.

The original Docker cargo-deny log and the product cargo-deny raw log could not
be retrieved through the decoded-log connector. Their boundaries are explicit:
the former is represented by its separately identified host diagnostic artifact;
the latter's successful status is preserved from GitHub job metadata. The full
successful proposal deny log is retained byte-for-byte in its original ZIP.

Executor installers, model weights, build caches, the 131 MB independent old
fixture executable archive, signed download URLs, and duplicate reconstructed
vendor trees are excluded. The archive is a repository evidence checkpoint,
not an environment image.

## Binary transport repair

PR #5040's actual codespell job 127932493398 treated one bare compressed-stream middle segment as text and reported 34 random-byte findings. The same original command and codespell 2.4.3 reproduce that failure locally. A segment is now represented as an independently valid gzip file; no spell-check option, allowlist or source exclusion changes. A normal prose typo still fails the original check.

The original INDEX.json and ROUNDTRIP_VALIDATION.json remain unchanged historical records. TRANSPORT_VALIDATION.json records the new complete restore and failure controls. The updated reader pins TRANSPORT.json separately, accepts exactly one bounded gzip member per original segment, rejects extra data or members, and then applies the original complete archive/member validation before publishing a destination. The original raw segments are reconstructed byte for byte; no scientific measurement or source evidence was rewritten.
