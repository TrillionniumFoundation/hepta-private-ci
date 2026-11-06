# Fence resolver compatibility

The original #5000 blob-size job failed during Fence startup, before checkout or blob-size inspection. It ran the existing v0.10.0 Action on the hosted Ubuntu 24.04 image 20261101.360.1 and reported `unsupported_resolver_layout`. The subsequent missing local action and unavailable post-job mount evidence follow from the failed setup. The retrieved log does not identify the exact rejected resolver predicate, so this record does not claim that the failed host had a particular filesystem layout.

This unit changes one workflow line to the official v0.12.5 complete Action commit `f9751ca5d767dc0199e88733c2b286bd4800a008`. It reproduces the exact workflow postimage already used in repository PR #4649. The source preimage and all other workflow bytes match. Audit mode, permissions, checkout ordering, size threshold, allowlist path, required checker, timeout and cleanup remain unchanged. No command rewrites the runner resolver and no failure is ignored.

Official Fence PR #208 added support for a root-owned direct resolver file while retaining verified read-only resolver mounting. The selected release's declared source commit descends from that merged fix. Its source still rejects unreviewed ownership, unsafe permissions, target changes and invalid mount evidence; the corresponding upstream tests were inspected, not rerun locally. The complete Action's bundle manifest identifies the exact reviewed source and bundled binary digest. The selected Action definition is byte-identical to the original definition.

The donor's original hosted job was independently fetched: Fence v0.12.5 became ready in audit mode, the 512000-byte checker inspected the five donor changes, and post-job Fence evidence verified with a healthy resident. That individual job succeeded; the donor's overall required CI failed elsewhere. Donor success is evidence for the compatible integration, not qualification of this new source head.

The current repository scope selector sends this workflow change through full/native CI. A new complete head must actually pass its own checks before this blocker is closed. The original failed job and its separately requested unchanged retry remain historical evidence.

The compressed logs retain the exact retrieved UTF-8 log text. Their uncompressed and compressed identities, source commits, official source chain, YAML comparisons and scope result are in `validation.json`.

Sources:

- Original failure: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42219701177/job/127898387456
- Repository donor: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4649
- Donor hosted job: https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41378736133/job/125064626070
- Official compatibility fix: https://github.com/openai/fence/pull/208
- Official release: https://github.com/openai/fence/releases/tag/v0.12.5
- Official complete Action: https://github.com/openai/fence/tree/f9751ca5d767dc0199e88733c2b286bd4800a008

## Recurrent failure after the earlier recovery

The original same-source, same-policy retry succeeded at job 127903594124. That result remains recorded. A later independent source, PR #5040, failed again in the original v0.10.0 Fence startup before checkout: run 42229805749, job 127932493561, unsupported_resolver_layout. The exact host resolver predicate was not emitted; this record does not guess it.

This recurrence reopens the previously held official version-maintenance candidate. The workflow preimage still matches the exact #4649 donor. The change updates only the official immutable action pin and version comment; all existing audit-mode inputs, permissions, checkout, comparison range, blob limit, allowlist and gate commands retain their original bytes.

The official v0.12.5 bundle manifest and complete DNS source were independently read again, their Git blobs recalculated, and the source ancestry to official fix #208 checked. The direct regular-file path retains root ownership and safe ancestor validation; the visible read-only mount and live identity checks remain enforced. Upstream test definitions were inspected, not locally executed. The new complete source requires an actual hosted Fence startup and blob policy pass.
