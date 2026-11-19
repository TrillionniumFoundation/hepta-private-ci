# Fleet frontier: complete semantic reconciliation

**Conclusion: accept the two incoming commits through a real merge while preserving the current source bytes.** Every incoming change is already represented by the current fixtures. No production, test, build, generated, or other repository file changes in the reviewed merge tree. This report does not claim a fresh native, Clippy, or Windows test result.

## Exact candidate

| Item                                         | Object                                     |
| -------------------------------------------- | ------------------------------------------ |
| First parent                                 | `770179d123b879355b53db1d75f8f9f301280d3e` |
| Incoming parent                              | `0e378dd351e0fca99d32f67613639b37c85605da` |
| Native merge base                            | `7a95aea0002de94d18a11a6e95db3b36cc2c41a8` |
| Native conflicted tree                       | `550954d5cccbbf30662e1c9d9de5666445b3c902` |
| Local review merge commit                    | `b3957ba39ffb9e0378b4ab652e2cb6463acb7004` |
| Resolved tree, exactly equal to first parent | `6911d7b83a7d2ae573efb4fbe08446f748a7a3a4` |

The only newly reachable original commits are:

1. `777e741d25b73d6a52048be34be63fab3fc6d79e`: changes the authority test fixture's error-reporting style.
2. `0e378dd351e0fca99d32f67613639b37c85605da`: canonicalizes the workspace sweep fixture path before constructing its binding.

The captured remote inventory maps these to `codex/sngr-fleet-authority-clippy-20261028` and `codex/sngr-fleet-canonical-sweep-20261029`, respectively. The additional local merge commit is an audit candidate; no remote ref was created, advanced, or deleted.

## Complete semantic decisions

The first commit changes eleven fallible fixture operations from `expect` to `?`, changes the revoked-error assertion from `unwrap_err` to comparison with `Some(Revoked)`, and adds the matching `Result` aliases, signatures, returns, and helper call. It changes no production code, fixture inputs, or test case set.

Current authority fixtures already meet the same success and failure requirements. Host admission explicitly asserts `Ok(())`. Temporary-directory creation, mode `0700`, epoch construction, registry opening, binding calculations, lease publication, issue, and revocation all panic on an error, making the test fail. The incoming `Result` form also makes the test fail on each of these errors. Neither form substitutes defaults or suppresses a failure.

The current revoked-lease check first requires `.err()` to contain an error and then compares that error to exactly `Authority(Revoked)`. Incoming compares the option to `Some(Authority(Revoked))`. Both fail for an unexpected `Ok` and for every other error. The receipt identity, dispatch boundary, authority epoch, authority reference owner/id/revision, nonzero binding digest, changed scope digest, and unchanged payload digest assertions remain present with identical values.

The second commit supplies a canonical workspace path to `WorkspaceBinding::new`. Current already supplies `path.canonicalize()?` directly. The constructor accepts `Into<PathBuf>` and immediately converts the argument, so an owned canonical path and a borrow of that same canonical path produce the same value. Its canonical/no-symlink requirement, directory requirement, and non-overlap with the fleet control root remain unchanged. The sweep retains all eight path names, all 256 subsets, both identity orderings, and the identical pairwise-oracle assertion body.

Current-only behavior is preserved: final allocation dispatch uses `witness.verified_at_unix_ms`, the caller's clock cannot become authoritative, and `authority_port_clock_tests.rs` remains linked. Current private-owner tests in the registry file are retained as well. The entire resolved tree equals the first-parent tree, including every file outside these two paths.

## True merge and explicit conflict resolution

An independent bare object directory reads existing caches through alternates. It has no remote configuration. A private sparse worktree then ran ordinary `git merge --no-ff --no-commit` against the exact incoming commit. Native Git reported five conflict blocks in `authority_port.rs` and one in `registry_tests.rs`; no other path changed. `MERGE_HEAD` and all three stages of both files are recorded in `native-worktree-merge.json`.

Each conflict was mapped to the complete incoming semantic change before choosing the current representation. Six nonconflicting incoming edits also needed deliberate resolution: the `FixtureResult` alias, helper signature, `ledger()?` call, first test's success return, second test's signature, and second test's success return. Keeping only the current conflict blocks would leave an inconsistent mixture of return types. These six edits were therefore explicitly restored to the current fixture style as a coordinated decision. The exact replacements and reasons are in `automatic-edit-decisions.json`; the full conflict-preimage-to-resolved patch is in `explicit-native-conflict-resolution.patch`.

This was not an `ours` merge strategy, a whole-parent attachment without inspection, or an unreviewed file checkout. The normal merge was committed after staging the two fully reviewed resolutions. Direct commit-object readback proves the two parents and the unchanged whole-tree identity. A metadata display command timed out after the commit; `metadata-read-timeout.json` records that bounded read and its successful direct-object recovery. No test process was involved.

## HIA boundary

The complete union of the two parents contains **40,860 commits**, with no missing parent nodes and no shallow boundary. The local merge adds exactly one node to this union.

The latest protected snapshot contains **366 references / 365 unique tips**, SHA-256 `acba9465f6e0f7768fbabeee8b4044093b4f84c745f0488107514d0b776b4c6c`. None of those tips occurs in the union or equals the local review commit. Neither HIA root occurs in it:

- Codex HIA: `f02bb9f3344cdff4e361cca4353540ca0193bd21`
- Cell/HIA: `3aa1f85ba90c79d220a5cadf2261def176892867`

The separately established Cell/HIA descendant anchor `8347769bab248a287efa2e4e82f667b55a0f29bc` is absent too. The earlier 356-reference snapshot and its successful review are preserved; `ancestry-review-latest-366.json` is the current boundary result. The full parent graph and both exact protected TSV snapshots are included for verification.

## Independent review and qualification scope

`/root/local_candidate_audit` independently read both complete incoming patches, the current authority test block, the current registry sweep, and the binding constructor contract. It agreed that preserving the current bytes retains all incoming failure checks and Windows canonicalization behavior. Its bounded static conclusions are recorded in `independent-semantic-review.json`.

Native tests and formatting were not repeated because this reviewed merge changes no bytes anywhere in the repository. This is a semantic/history review, not evidence that a particular platform's CI passed. Root and peer checkouts and their jobs were not modified.

## Review files and use on the publishing branch

- `resolved-merge-review.json`: exact parents, resulting tree, covered commits and refs, and zero source delta.
- `semantic-review.json`: all incoming semantic changes, assertion truth table, and source-invariant checks.
- `conflict-decisions.json`, `conflict-blocks.json`, and `automatic-edit-decisions.json`: every conflicting and automatically applied incoming edit.
- Both full commit patches and raw per-commit file deltas: complete incoming scope.
- `sources/` and `source-manifest.json`: exact base/current/incoming/native-conflicted snapshots and supporting current contract/lint sources.
- `native-merge-tree.*`, `native-worktree-merge.json`, `candidate.commit`, and `final-readback-transcript.json`: merge provenance and direct object verification.
- `ancestry-review-latest-366.json`, protected snapshots, and `ancestor-union.parents`: HIA exclusion evidence.
- `complete_review.py`: the bounded audit/resolution utility, intended only for an independently recreated merge in progress.

If the publishing first parent advances, perform its own real three-way merge. Verify the merge base, incoming uncovered commits, both exact current blobs, any conflicts/automatic edits, and the latest protected ancestry before applying the recorded decisions. The reviewed current blobs are `1020ef1aafd45a64b5bad9561ab6dbe57470093d` for authority and `12f18283d6c30c7c7e04ce04b44d0d350c2492b3` for registry. A newer base can contain unrelated work that must remain intact. This local candidate does not authorize overwriting that work or changing protected refs.

## Reconstruct the original archive

The ordered parts are individually gzip-wrapped slices of the original
compressed archive, keeping every Git blob below 512,000 bytes. Reconstruct
from this directory with Python 3. This only writes the verified original
archive; it does not extract or execute any archived script.

```python
from pathlib import Path
import gzip
import hashlib
import json

index = json.loads(Path("archive-index.json").read_text())
chunks = []
for item in index["parts"]:
    stored = Path(item["path"]).read_bytes()
    assert len(stored) == item["bytes"]
    assert hashlib.sha256(stored).hexdigest() == item["sha256"]
    decoded = gzip.decompress(stored)
    assert len(decoded) == item["decoded_bytes"]
    assert hashlib.sha256(decoded).hexdigest() == item["decoded_sha256"]
    chunks.append(decoded)
original = b"".join(chunks)
assert len(original) == index["archive_bytes"]
assert hashlib.sha256(original).hexdigest() == index["archive_sha256"]
Path(index["archive_name"]).write_bytes(original)
```
