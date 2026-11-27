# Resource evidence closure and cost-index supplement

This appendix preserves verification and publication records created after the
[resource/replay snapshot](../p0p5-resource-replay-20261110/README.md) was frozen.
It does not modify that snapshot or change numerical or scientific admission.

## Independent review and published Git objects

The [independent review](independent-index/REVIEW.md) binds all 228 snapshot
members, eight ZIPs, 21 original cost records and 34 document links. No resource
algorithm, model or numerical oracle was rerun. The
[working integrity result](verification/integrity-v2/RESULT.json) agrees.

The [committed-tree result](verification/committed-v2/RESULT.json) verifies
1,022 distinct regular blobs across five manifests and the explicitly bound
entrypoint dependencies. It checks local commit
`7c334a4de49aa711ca5aca5fee4a3443a026ec46`, tree
`da62f605dfa9771c439d0f91edf3deff5aed7818`. The
[API readback](publication/hcsn-resource-evidence-api-progress-v1.json) confirms
the identical whole tree at remote commit
`14e8427f46d6517d8d57649b8ac0b888b1c991e8`.
[Draft PR 5848](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5848)
contains the 229-file mechanical archival stage. This verifies those source
trees, not this later appendix, a future CURRENT edit, or overall CI success.

The first API attempt disconnected during a content-addressed tree request;
whether that tree object was created was not observed. The retained
[reconciliation](publication/hcsn-resource-evidence-api-attempt-v1-failure.json)
shows no completed commit stage and the branch still at its original base.
A distinct invocation used smaller tree batches and completed whole-tree and
branch readback. No model, oracle or original training job was rerun.

## Exact reproduction entry and retained wrapper failures

From the repository root, use the established module entry:

```bash
python -B -m qualification.hcsn_differentiable.evidence_chain \
  --manifest qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/MANIFEST.json \
  --markdown qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/README.md \
  --output /tmp/hcsn-resource-integrity-new.json
```

Choose a new output path; the checker preserves existing results. The initial
direct-file invocation failed during Python imports because package
`operator.py` shadowed the standard-library module. Its
[original stderr](verification/integrity-v1-failed-entry/stderr) and cost are
retained. The subsequent module invocation used unchanged verifier/evidence
bytes and passed. This is an entry-command correction, not an acceptance-rule
change. A separate Git-proof wrapper preflight mistakenly selected `-B` as a
source filename before launching its child; the
[preflight failure](verification/committed-v1-preflight-failure/PREFLIGHT-FAILURE.json)
is retained, and the corrected invocation checks the actual verifier script.

## Hosted fixture cost supplement

The [member-level supplement](independent-index/HOSTED-FIXTURE-COST-ADDENDUM.json)
indexes existing measurements inside original science artifact 13797877354,
run 42890048946 attempt 1. Exact member sizes and hashes bind each value:

| Artifact member | Original timer | Scope |
| --- | ---: | --- |
| qualification.json | 8.136141368 s wall; 8.124293353 s process CPU | Qualification interval after imports |
| error-budget.json | 6.990235205 s wall | Historical error-budget fixtures |
| qvi-oracle.json | .044480695 s wall | Finite QVI fixture report interval |
| qvi-tests.log | .119 s | Unittest internal timer, three tests |
| memory-controls-tests.log | .003 s | Unittest internal timer, three tests |

These are nested hosted-job measurements. They are separate from the already
charged artifact-download/collection process; they are not a complete job CPU,
calendar, energy or billing total. No CI run was repeated to obtain them.
[COSTS.json](COSTS.json) also retains the independent review, both invocation
failures, successful integrity/Git checks, formatter and unknown API transport
costs. [COPY-RECEIPT.json](COPY-RECEIPT.json) records local curation samples.

The original six HCSN fits remain budget-censored, all original retained
training traces remain at update zero, and whole-training numerical admission
and scientific benefit remain HOLD. Current numerical-audit and C2-preparation
work are outside this completed appendix.
