# Preserved ordinary-branch evidence

This batch retains fifteen ordinary branch histories and their original
evidence. Eight logs or JSON snapshots contain formatting-significant whitespace.
They are stored as deterministic gzip carriers so their original bytes and
existing SHA-256 witnesses remain intact. Runtime code and CI policy are unchanged.

## Verify and restore

From the assembled repository root:

```sh
python qa/repository-consolidation/20261118/passive-branch-artifacts/restore.py --repository .
python qa/repository-consolidation/20261118/passive-branch-artifacts/restore.py --repository . --destination /tmp/hepta-originals
```

The first command verifies the compressed hashes, decompressed lengths, original
SHA-256 digests and Git blob identities. The second requires a new separate
directory and restores original relative paths there. It refuses to overwrite
files or write within the source repository. Historical artifact manifests refer
to these restored bytes; their original contents remain unchanged.

| Original path | Lossless carrier |
| --- | --- |
| `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-critical-080619Z.json` | `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-critical-080619Z.json.gz` |
| `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-stack-0729Z.json` | `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-stack-0729Z.json.gz` |
| `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-stack-075339Z.json` | `qa/stem-bakeoff/evidence/20261023-parametric-memory-growth/engineering/ci/remote-ci-stack-075339Z.json.gz` |
| `qualification/hcsn_currentstate_ci_readback/43219061969/JOB.log` | `qualification/hcsn_currentstate_ci_readback/43219061969/JOB.log.gz` |
| `qualification/hcsn_currentstate_n256_joint_admission/evidence/actions-43414960629/original-job-131850414245.log` | `qualification/hcsn_currentstate_n256_joint_admission/evidence/actions-43414960629/original-job-131850414245.log.gz` |
| `qualification/hcsn_differentiable/evidence/p0p5-c2-strict-json-20261111/RED-original.stderr` | `qualification/hcsn_differentiable/evidence/p0p5-c2-strict-json-20261111/RED-original.stderr.gz` |
| `qualification/hcsn_saved_continuation_ci_readback/43221327931/JOB.log` | `qualification/hcsn_saved_continuation_ci_readback/43221327931/JOB.log.gz` |
| `qualification/hcsn_scale_intent_ci_readback/43226175031/JOB.log` | `qualification/hcsn_scale_intent_ci_readback/43226175031/JOB.log.gz` |

Three explanatory Markdown documents update links to the carriers; the manifest
records their original and adapted Git blob identities. All other original paths
retain their exact source blobs. The source branch commits remain available as
merge parents and preserve the unadapted documentation.
