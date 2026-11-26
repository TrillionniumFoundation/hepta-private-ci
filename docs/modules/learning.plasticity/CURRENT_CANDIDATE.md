# learning.plasticity current candidate boundary

This file is the candidate overlay for the ordinary Git source tree. The generated
`CURRENT_STATE.json` and `CURRENT_IMPLEMENTATION.md` retain historical map provenance;
they are not exact-head pass receipts and cannot override this boundary or the
workflow-produced readiness manifest.

## Source composition now present

- deterministic parameter candidate and generator-coverage construction;
- explicit zero-signal, policy-disabled and independently attested no-update terminals;
- non-test control.engineering parameter and topology iteration coordinators;
- submission only through the state-held Agentd named producer;
- bounded parameter/topology queues, deadlines, cancellation, aggregate byte/work
  quotas, blocking-pool execution and phase timing;
- create-only parameter/topology terminal receipts;
- no-follow storage opens, exact inode/device binding and parent-directory sync;
- host-declared rollback-domain receipts that reject aliases and equal domains.

`EXACT_MAPPING.json` adds these candidate operations to the durable navigation map.
`verify_learning_plasticity_exact_mapping.py` resolves the combined inventory against
the current checkout and emits commit/blob/test identities outside the source tree.

## Single-candidate qualification

The required workflow has `contents: read`. It never resets to an old parent,
decodes `.authoring` payloads, applies patches, commits, force-pushes or refreshes
tracked documents.

For a pull request, one workflow run and attempt executes:

```text
exact PR source head
  + deterministic two-parent merge(base, source)
  -> independent lane receipts
  -> one readiness manifest
```

The manifest sets `mergeReady=true` only when both required lane receipts bind the
same source, base, workflow SHA, run ID and attempt and every repository gate passes.
Missing, failed, cancelled, skipped or cross-run evidence makes `mergeReady=false`.

After integration, the real main merge SHA runs again as `final-merge`. PR-head or
synthetic-merge evidence is not relabelled as final-merge evidence.

## Claim boundary

The following remain false until separate receipts exist:

```text
productionImplementation
productExecutionProved
targetHostEvidence
rollbackDomainIndependenceProved
independentAcceptance
operatorAcceptance
activation
release
```

Repository code can validate the shape of a rollback-domain receipt but cannot prove
physical placement, power-loss behavior, container-volume snapshot isolation or an
operator exercise. `TARGET_HOST_QUALIFICATION.md` defines those external gates.
