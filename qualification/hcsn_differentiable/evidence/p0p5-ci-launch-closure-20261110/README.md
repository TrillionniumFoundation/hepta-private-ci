# Exact CI identities and C2 launch verification appendix

This appendix retains completed checks after the
[resource closure](../p0p5-resource-closure-20261110/README.md) and the
[C2 launch snapshot](../p0p5-c2-launch-20261110/README.md). It does not rewrite
either snapshot, grant numerical admission or declare the ongoing training complete.

## Exact hosted science result

The [original artifact](science-original/artifact-13802347858.zip) is GitHub
artifact13802347858, run42899977177 attempt1: 91,935 bytes, SHA-256
`df70358ffc892bfc535fd6d209fbc81b6c70bc20c0f7d295aec6d1df71c03d22`.
The original ZIP was downloaded once, then checked byte-for-byte and by every
member SHA and CRC. The [collection capsule](science-original/collection-original.zip)
retains frozen collection source, raw transport receipts and verification.

The [actual identity](science-original/identity.json) records source head
`652263b31ebebc4e85b5b2986cb144f0127cbad2`, tested merge
`ffa6eeaa90520ccf234cb6c79828e7d859614fe5`, and identical source/tested tree
`aa5cc6bc55b0dc1cb68adf62886fb9646962de03`. The original
[outcome](science-original/outcome.json) passes declared CPU fixtures. Its
[evidence result](science-original/VERIFICATION.json) binds six manifests,
1,053 files, 51 ZIPs and 287 relative links with zero errors. The 92 software
fixtures and these evidence checks establish neither whole-domain numerical
qualification nor repository-wide CI success.

The [local working-tree result](earlier-tree/worktree-integrity/RESULT.json)
agrees. The separate [committed-blob proof](earlier-tree/committed-blobs/RESULT.json)
checks 1,068 distinct regular Git blobs at local commit
`a33490f926debd60ce21f73b2ea64c1b90b8338a`, whose whole tree matches that remote
source. This proves committed availability, not just files left in a worktree.
Those historical checks do not include this later appendix or the C2 snapshot.

## Narrow spelling failure and later CI observation

The retained [older decoded job logs](ci/older-blocking-decoded-logs.zip)
belong to source `cd3b7ac49294174a98e02636247615534c19bd89` as identified by the
original observation receipts. These are the exact UTF-8 bytes returned by the
connector, not the compressed HTTP log-download payload. The spelling job
flagged five short strings inside one immutable Base64 transport receipt.

Only that exact encoded receipt path was added to the existing workflow skip
list. No original evidence bytes, word allow-list or scientific threshold was
changed. The [same-version red/green check](codespell-fix/RESULT.json) retains
both outcomes and costs using codespell2.4.3. The failed offline tool resolution
and subsequent isolated tool setup also remain. The
[source commit](codespell-fix/SOURCE-COMMIT.json) and
[whole-tree publication records](publication/current-resources-api-progress.json)
bind this narrow fix to remote head
`fdbc954bb259a709275771fe151b4f0c8d245b48`, tree
`626a3ee0ba89432a5203fc00687f8e21781a472b`, in
[draft PR5850](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5850).

The later [read-only CI observation archive](ci/observations-original.zip)
reports scientific run42902660902 and canary42902660830 successful at that
head. Architecture run42902660993 was in progress; blocking run42902661147
was queued. No passing hosted spelling job or all-green CI is inferred from a
queued workflow. The older blocking workflow failed, including an existing
README readiness-discovery contract failure; further unrelated failure causes
are not inferred from job names alone.

The [save-wrapper failure](ci/observation-save-failure.json) preserves a local
argument-length error before process creation. The already obtained API result
was saved in chunks. No API read or CI execution was repeated for that repair.

## C2 snapshot checks and limits

The [C2 manifest verification](c2-launch-checks/integrity/RESULT.json) checks
145 members, 11 directly stored ZIPs and 35 relative links with zero errors.
The snapshot's own archive index separately verifies two split archives by
reassembling their original byte parts, yielding 13 original archives in that
index. The [builder receipt](c2-launch-checks/packaging/EXECUTION.json),
[spelling result](c2-launch-checks/codespell/EXECUTION.json),
[formatter result](c2-launch-checks/formatter/RESULT.json) and
[local commit](c2-launch-checks/LOCAL-COMMIT.json) retain the exact scope.
Formatting changed none of its146 frozen files.

The C2 first-step snapshot records six actual continuations and corresponding
producer witnesses. It does not claim a terminal optimizer/checkpoint audit,
full probability-array verification, adequate training or scientific benefit.
The independent terminal auditor is separate preparation, and the original
terminal numerical audit is still a separate bounded execution.

## Cost and immutable source rules

[COSTS.json](COSTS.json) points to measured intervals and their exact original
receipts. Hosted fixture times are nested within the hosted job; native artifact
collection times are separate. Whole hosted CPU, energy and billing are unknown.
Partial script prefixes and failed-wrapper unknowns are not silently converted
to complete process totals or zero. No model, optimizer, oracle or CI job was
rerun to create this appendix.

Use [MANIFEST.json](MANIFEST.json) with the established module entry
`python -B -m qualification.hcsn_differentiable.evidence_chain`; choose a new
result path. [COPY-RECEIPT.json](COPY-RECEIPT.json) records the exact copied
inputs and curation samples. Scientific and whole-training numerical admission
remain HOLD; P5 remains gated on a demonstrated comparative benefit.
