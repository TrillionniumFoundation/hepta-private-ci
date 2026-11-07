# Local caller audit history

**r4 passed 56 typed scanner tests, 69 B4 tests, and the closed-set proof for 171 boundaries across 5,315 Rust files.** This is local source-audit evidence on the frozen, pre-native-format tree below. It is not final product qualification. r3's later-discovered scope defect and every subsequent failing regression remain in the archive.

| Iteration | Typed scanner tests | B4 tests | Caller proof |
| --- | --- | --- | --- |
| Initial (r1) | 20 passed | 69 run, 1 failed | Failed: two real split-owner callers missing from CALLERS |
| r2 | 26 passed | 69 passed | 171 boundaries / 5,309 Rust files passed |
| r3 | 30 passed | 69 passed | 171 boundaries / 5,309 Rust files passed; later scope defect retained |
| r4 | 56 passed | 69 passed | 171 boundaries / 5,315 Rust files passed; authorityGranted=false |

These are separate executions. Do not add their totals or transfer a PASS between source versions. `manifest.json` binds each raw log, result and source set. The two successful caller receipts are byte-identical, so `cp-ok.json.gz` is stored once and referenced by both runs. The original failed `--self-test` CLI invocation and its corrected run are retained separately and do not count as product tests.

## Preserved r4 repair history

The initial r4 lexical repair passed 43 tests, then a new generic-argument regression failed three subcases. The 45-test repair exposed unsupported active pattern shadows in 14 negative subcases. The 54-test repair was followed by a failing match-guard keyword regression; the 55-test repair was followed by five failing struct-pattern subcases. The current 56-test source resolves those recorded defects. Each intermediate passing source also has its own 69-test B4 log; none is reused as the current result.

The scanner keeps only live lexical bindings, applies completed declarations in source order, and marks unsupported active pattern names unresolved. It does not infer authority types from destructuring. Original equal-offset pattern text retains struct binding names while the lifetime mask excludes closed blocks and earlier match arms. These regressions demonstrate the listed cases, not completeness as a Rust type checker.

## Exact source boundary

r4 is bound to Python hashes in `src-r4.json.gz` and Rust subtree `412371f6259acdffae1392ef92b431c2c6accc75`. Before and after the full scan, all 9,451 tracked entries (128,226,182 blob bytes) independently matched their Git object identities, all 5,315 Rust files belonged to that tree, and all eight audit source hashes were unchanged. `src-r4-post.json.gz` preserves the second check; `cp-r4.run.json.gz` records the actual successful exit and 330.9-second run. This semantic repair precedes native formatting; the result does not qualify a subsequent formatted tree or whole publication commit.

r3 used the local Python worktree hashes in the manifest with Rust subtree `d31e8d30825164a81ea7320796b9f6d61ed09d77`, matching `73414467c27bf238757c733e9b5035746c77e14c:codex-rs`. The unchanged staged Rust and its tree were verified after the run, before native formatting. `src-r3.json.gz` preserves that capture and hashes of the two scanner Python files, CALLERS, the independent inventory and supporting audit drivers.

The local Git HEAD remained `a6f3aa12ba187448c35449c7da0a9798ae4ca987`; it is only the checkout base. The later Python publication `b4afdbadc247c6fadfad4e416c00a9a853affa1c` also contains a different, natively formatted Rust tree and **is not qualified as a whole by these logs**. Earlier source hashes are reconstructed from the preserved pre-fix copy / unchanged staged r2 files; their original launch receipts did not record a Rust tree.

## Review and integrity

Gzip members contain exact original bytes, with deterministic gzip timestamps. The manifest records both compressed and raw SHA-256 and byte counts. From the repository root:

```python
from pathlib import Path
import gzip, hashlib, json
root = Path("qualification/cell-architecture-20261106/audit")
m = json.loads((root / "manifest.json").read_text())
for item in m["artifacts"]:
    packed = (root / item["path"]).read_bytes()
    raw = gzip.decompress(packed)
    assert len(packed) == item["gzip_bytes"]
    assert len(raw) == item["raw_bytes"]
    assert hashlib.sha256(packed).hexdigest() == item["gzip_sha256"]
    assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
```

This proves local Python audit outcomes and archive integrity. It does not execute Rust products, models or external effects, or establish independent authority custody. Final native/CI validation must rerun and bind the exact final formatted source. No record grants authority.
