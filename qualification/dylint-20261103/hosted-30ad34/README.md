# Original maintained Dylint gates on 30ad34

Candidate 30ad34c1895597a04dc42f0d233505aa7566a6b7 passes the original
argument-comment lint job 126235308440 in run 41726681773. The actual test
checkout is merge cf13fb2ffc18e7ef7a814845faf26b95f1fcca89; its entire tree
is identical to the candidate's fcbb3b9c180f929661348dc5d6453e8c04fe369e.

The complete original log records a real cache miss, both CLI tools built
from source with cargo install --locked on fixed Rust 1.97.0, then the original
package and driver on nightly-2025-09-18. Five library tests and three binary
tests pass. One library test is the UI aggregate and exposes nine passing
nested UI cases; these are not added again to the eight outer tests. All six
original Python wrapper tests and the clean-worktree check also pass. Rust
failures, ignored, measured and filtered counts are zero.

The exact candidate's original committed-lock job 126233179938 in run
41726681634 also passes. The previous independent replay compared all 1,664
recorded inputs to actual Git bytes, all nine output hashes, unchanged inputs,
three original zero-exit commands and identical committed/generated/Git locks.
The complete ZIP remains original GitHub artifact 13274416692 (610,346 bytes),
whose exact SHA-256 and reproduction inputs are in manifest.json. It is not
copied into the repository. The 143,712-byte original native job log is retained
losslessly as gzip; its decoded digest matches the previously verified log.

To reproduce, obtain the exact original artifact with authenticated GitHub CLI:

```sh
gh api repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/13274416692/zip > /tmp/dylint-lock-13274416692.zip
python3 qualification/dylint-20261103/hosted-30ad34/verify.py --repository . --artifact /tmp/dylint-lock-13274416692.zip --output /tmp/dylint-verified.json
```

The Git checkout must contain the source commit above. The verifier reads Git
objects and archive bytes, executes no archived source, rejects optimized
Python, and fails on any missing, changed, unsafe or extra artifact member.
This newly restored verifier has not run locally: the execution environment
is unavailable. The fresh independent hosted replay is recorded separately;
no pending replay is represented as completed.

This checkpoint preserves the completed lint/bootstrap and committed-lock
scopes. Other full-CI failures, the separate native release matrix and wider
scientific, security, performance and activation gates remain open. Draft /
HOLD_NO_GO / DENY_ALL is retained; no original Library content is deleted.
