# Retained lifecycle-v1 warm Adopt failure

This is a separate failure-evidence append. The original 32-file E6/NoUpdate16 package remains unchanged.

The only attempted lifecycle parent failed. Both planned cold parents had **zero attempts**, because the frozen protocol stops on the first failure. This appendix does not transfer a later candidate's result or the separate #6858 daemon CI result to this execution.

## Executed identity and result

- Source: `84721f3da92ffaac3e7c7e2e39de2df985834370`.
- Tree: `ec318c4d77695a67f11a2a9ec174e3c8f19823df`.
- Driver SHA256: `1496bea8180126b6e905b04ec2ba1e92f23f10a2fa529010ec194357b73ebeea`.
- Review manifest SHA256: `9fa4a9db58269942cf8c0fabb10a1d1518549fcc52e21f3fdad615bac3aeff5a`.
- Canonical parent: `neuron_generation_current::initial_root_tests::ordinary::post_a_process::ordinary_main_adopts_after_independent_b_and_executes_original_c`.
- Canonical JUnit: one case, zero passed, one failure, zero errors, zero skips; command exit 100.
- Failure text: `original Q24 publication binding: actual local decision or original NoUpdate cut required`.

| Observation | Result |
|---|---|
| Warm Adopt parent | One attempt; failed |
| Whole cold Adopt parent | Zero attempts; not started |
| Whole cold NoUpdate parent | Zero attempts; not started |
| Automatic retry | Disabled |
| Canonical case time | 65.719 seconds |
| Original executor elapsed | 66.47933763219044 seconds |
| Outer command elapsed | 66.54169046785682 seconds |
| Whole owner elapsed | 88.03090610075742 seconds |

These elapsed times describe nested scopes and must not be added. Prior JUnit and the duplicate fresh-observed copy are retained as evidence but excluded from the one-case count.

## What the actual checkpoint records

The retained checkpoint structurally decodes as five receipts: Experience, Dataset, Training, Evaluation(Qualified), and Proposal(UpdateCandidates). It contains no LocalDecision, artifact Selection, or NextUse receipt.

The Training receipt has the fields `steps=2`, `milliseconds=2`, and `artifact_bytes=172`. It has no `optimizer_steps`, `parameter_updates`, or `examples_seen` fields. These are recorded receipt fields; they do not independently measure physical optimizer work. A fixture expectation of four parameter updates is not an observed update count.

The decoder follows the pinned Rust codec's field order and consumes the entire retained snapshot. Its complete source, report, input checkpoint, codec source, and original readback containers are preserved in the supplement. This was structural decoding; independent Rust receipt-chain verification was not rerun. The report is not a new authorization or a new native test.

The production publication guard refused an incomplete local decision. The failed execution does not establish successful fixture adoption, original C execution, cold recovery, fresh D, real external student-weight adoption, model gain, FinalUse, settlement eligibility, or deployment.

## Cleanup and retained executable

The original source, tracked bytes, and compiler-input checks remained unchanged. The original driver did not restore the test executable's mode: its recorded sealing/cleanup prerequisites were incomplete. The old executable remains at mode `0555`, with SHA256 `f6e4b2622ffde258c611729286a28cb87b0f792b06838ea383a2466b69f86781`; the 1,207,941,528-byte executable is not embedded in this package.

Drop/kill cleanup is not evidence of successful orderly daemon/Root retirement. Neither cold parent was attempted. The original failed target must remain preserved; this appendix grants no authority to modify it.

## Original archive and supplement

`MANIFEST.json` binds every part, important original members, the supplement, source identities, counts, and limitations.

The six `37_lifecycle_failure.tar.gz.partNNN` files are consecutive **binary** pieces of the exact original 2,047,579-byte archive. Concatenation restores its original outer bytes, not a newly packed equivalent. The archive has 65 regular members: 64 original files plus its original readback manifest. All 64 original member byte counts and SHA256 values were checked against that manifest.

Restore from this directory:

```sh
cat 37_lifecycle_failure.tar.gz.part00[0-5] > 37_lifecycle_failure.tar.gz
sha256sum 37_lifecycle_failure.tar.gz
tar -tzf 37_lifecycle_failure.tar.gz
```

Expected archive SHA256:

```text
3bb02ef7c446777e23101d556f1aa138d697ab8ccb34971de4d3489a5b06cdfb
```

`SUPPLEMENT.tar.gz` is a new container of 16 retained file byte streams. It contains the original launch/deployment envelopes and commands, the complete original forensics and codec archives (including their original outer bytes), the structural decoder/report, the independent root review, and the verified transfer receipts. Its member inventory is in `MANIFEST.json`. The six owned-child log pairs and actual checkpoint are in the original forensics archive inside the supplement.

No archived program was executed while packaging. No native or model experiment, formatter, test, GitHub rerun, ignore change, or blob allowlist change was performed for this append. All new Git blobs remain below the existing 512,000-byte ceiling.
