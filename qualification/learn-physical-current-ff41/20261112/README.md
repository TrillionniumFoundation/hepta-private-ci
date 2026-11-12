# Physical CURRENT and resident qualification records

These records preserve failures as well as later repairs. They are evidence, not an acceptance grant.

## Exact source identities

| Stage | Local source | Published source | Tree |
| --- | --- | --- | --- |
| Resident integration repair | 88e30974b8d2802f5f6819ed3411df09851ea755 | 39204b8362a52babec66e94478bda9c2e274573b | b965c72c3a4432df6e059b36c7bc67d5bf6c2c76 |
| Complete source formatting | 8cc82616acef3e57b5b81827cf268491901ad06a | 5ae3d5fe358dc01d9e94c5a38758685f0920328f | dabffe7ed9571c676d889975dc8f025f5ac4220d |

All published trees and ordered parents were read back. The three original repair stages and eight format stages retain separate local-to-remote mappings. Each formatting commit has fewer than 800 changed lines. The 43 Rust postimages independently equal rustfmt output for their original blobs.

## Results and limits

- Original focused 7a6c execution: 109 cases, 89 passed and 20 failed. The hosted exact-source native run independently observed the same 20 failing names among 1,419 cases.
- Original physical-corruption failure is at `neuron_cell_evaluation_execution_store_tests.rs:376:9`, immediately after corrupting bytes. Restoration is at line 377; its later assertion was not reached. Therefore the original observation is failure to detect the first corrupt read, not an observed successful read after restoration.
- b514 shared native: 1,314 executed, 1,296 passed and 18 failed. The physical-corruption regression and three new witness tests passed on the first attempt. The 18 failed tests used one retry and retain their rerun failures in the original JUnit.
- b514 GNU Bazel agentd: 993 passed / 18 failed / 71 ignored. Its failure set equals the original 20 minus the physical-corruption and Holdout cases. Separate failure classes are retained; they are not all attributed to timeout or crypto cost.
- b514 Windows selected LEARN: 36/36 passed with zero retries. The overall private-state job failed on formatting, and later directory-attack qualification was skipped. The separate legacy sandbox refusal is retained as an independent failure.
- b965 source closure: 259 methods passed. Complete six-package formatting still failed on 43 inherited f8ea files. Its full caller was explicitly interrupted for resource serialization; no receipt was produced.
- Intermediate formatted f3c source closure: 259 methods, two errors. Both original logs and the exact failed patch/commit are retained. The corrected locators preserve real receiver and order checks, and add two deletion controls.
- dabffe source closure: **259 methods passed in 68.377 seconds**; clean before/after. Complete original six-package format check, 329 protected rows, caller self-test and the exact digest blob policy passed. A helper invocation missing mandatory `--allowlist` returned exit 2; its failed invocation and corrected exit-0 invocation are both retained.
- dabffe full caller started at 2026-11-12 02:20:06 UTC on the unchanged clean source and is running at this record checkpoint. The original full scope is retained with a 1 GiB address-space limit. Its final result is not claimed here and will be appended as a separate record.
- #6018 blocking run 43098715965, attempt 2, is **completed / failure**, updated 2026-11-12 01:09:49 UTC. The attempt-2 repository-check job and its caller step were cancelled. Earlier attempt-1 caller PASS remains a separate observation; there is no overall candidate PASS.

The live-owner poison and restore controls do not establish persistent corruption memory after constructing a new owner, joint rollback freshness, or whole-system cold recovery. f8ea changes runtime composition, so a later crypto profile candidate on this base is not a strict b514 A/B comparison. Cargo profile outcomes do not qualify Bazel.

Accepted complete ordinary **Adopt = 0**, complete ordinary **NoUpdate = 0**, complete daemon-plus-Root **cold recovery = 0**. Concrete Resident late-delivery and Candidate readback components do not by themselves qualify ordinary main, independent B authority or the complete adoption route.

## Primary run and review links

- [Original integration PR #5981](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5981)
- [Original exact-source native run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43115842564)
- [b514 qualification PR #6031](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6031)
- [b514 shared native run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43126736569)
- [b514 full blocking run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43126736813)
- [b514 Windows private-state run](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43126736341)
- [Current repair PR #6076](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6076)
- [#6018 blocking attempt 2](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43098715965/attempts/2)

## Read and verify originals

`manifest.jsonl` contains one JSON object per original file: its complete byte length and SHA-256, plus the ordered compressed chunks and each compressed digest. Compression is deterministic gzip with mtime 0. Large originals are split into fixed 400,000-byte chunks so every Git blob remains below the existing size budget. The final empty original also has one verifiable gzip stream.

The following reads all records without writing reconstructed files:

```python
import gzip, hashlib, json
from pathlib import Path
root = Path("qualification/learn-physical-current-ff41/20261112")
for line in (root / "manifest.jsonl").read_text().splitlines():
    row = json.loads(line)
    data = bytearray()
    for part in row["parts"]:
        packed = (root / part["path"]).read_bytes()
        assert hashlib.sha256(packed).hexdigest() == part["compressed_sha256"]
        chunk = gzip.decompress(packed)
        assert len(chunk) == part["raw_bytes"] and len(data) == part["offset"]
        data.extend(chunk)
    assert len(data) == row["raw_bytes"]
    assert hashlib.sha256(data).hexdigest() == row["sha256"]
```

Detailed audit notes retain source identities, run/attempt/job identities, failure classification, guard mappings, failed helper invocations, local-to-published mappings and the individual original hashes. Native and complete blocking qualification of the latest published head remains required.
