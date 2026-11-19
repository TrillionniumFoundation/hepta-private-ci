# Original d0f Windows private-state qualification

This packet preserves the original pull-request workflow run 43062473076, attempt 1, and job 130668436521. The tested source is d0f6507e08f7f5c5855f5164d07c049a34d1a6d9, tree 658fa040046285116b1fd81b94ff8c96444072ad. The original run and job finished successfully. No workflow rerun or new native execution was performed during this audit.

## Actual results

The full job log contains 34 distinct passing unmutated native case IDs, across six original command summaries: 15, 2, 3, 2, 11 and 1. The corresponding filtered-skip counts are 5, 26, 147, 148, 260 and 270. The final single case is the original signed-credit cross-owner rejection test. Its complete phase log occurs byte-for-byte in the decoded full job log after timestamp/line-ending presentation normalization, and its receipt binds clean source identities before and after the command. Its command keeps retries at zero and no-tests as failure.

The acquisition artifact separately preserves a repeated two-case positive lane and two deliberately mutated counterfactual lanes. Each counterfactual executes two cases: one passes and one fails as expected. These six additional executions are not added to the 34 unique production cases. Both original counterfactual patches are replayed against the exact positive source, and the resulting bytes match their archived postimages. The production file was also read independently from the immutable source commit and matched to the original positive bytes.

The full job additionally reports six Python reader unit tests. They are a separate language and purpose and are not part of the native 34.

## Preserved evidence and replay

The packet contains both original artifact ZIPs, all eleven original members, the complete 332,522-byte job log, full run/jobs/artifact API records, the exact-source production-file readback, and an offline verifier. API artifact digests, ZIP CRCs, every member, phase raw hashes, raw named-case IDs, command summaries, source identity, counterfactual replay and final clean-worktree gate are checked.

Run:

    python3 verify_private_original.py .

AUDIT.json is the result from those original bytes. VERIFIER_IDENTITY_DELTA.patch records the identity-only adaptation of the prior c895 evidence reader; the required 34 names/count boundaries and all verification logic remain intact.

## Limits

This is the exact-head Windows private-state, prompt-runtime and signed-credit qualification. It does not close ordinary/elevated sandbox permissions, all Windows CI, scientific memory benefits, or production-owner custody. The ordinary blocking workflow is recorded separately and has actual failure/FLAKY/cancelled outcomes. No old-head pass is transplanted here.

The collector's initial local materialization script could not import requests before any download. The same already-issued artifact references were then read once with Python's standard-library HTTP client; both complete byte streams matched their original API digests. No signed download URL is included in this packet.
