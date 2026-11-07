# Windows44 independent packet review

## Decision

The original 184-file package fails its declared plain-source exclusion boundary.
Its `assertion_values44_v3.before_format.py.txt` member is exactly the same 8,888
bytes as the final algorithm published separately. This is a redundant source
alias, not a secret disclosure or an unreviewed algorithm. The original package
and this failure receipt remain unchanged.

The replacement 183-file package passes the selected byte and metadata checks.
The same auditor ran with `python -B -O` against each package: the original exited
1 with the alias finding, and the replacement exited 0. All other custody checks
completed for both packages. A separate comparison proves that all 183 retained
roster objects are identical and only the identified alias was removed.

## Review entry points

- `audit_packet.py`: 494 lines; standard-library byte and metadata checks only.
- `initial_alias_finding/REVIEW.json`: the frozen original-package failure.
- `revision2/REVIEW.json`: the replacement-package result.
- Each sibling `EXECUTION.json` records the exact optimized Python command,
  auditor identity, exit status, and unchanged stdout/stderr.
- `check_revision_delta.py` and `REVISION_DELTA.json`: the exact roster change.
- `checks/`: actual formatter, lint, and spelling receipts.

The auditor verifies the pinned publication and roster identities, all nine
publication files, the complete INDEX mapping, single bounded gzip and XZ
streams, raw tar identity, unique regular members, exact original bytes and
0644 source modes, and all six separately published sources by full bytes.
It preserves the initial preparation, transport, parser, and reviewer failures.
Every read input is checked again before the result is returned.

The canonical reader is pinned by SHA256 and compared with the root's fresh
main-5282 Git leaf. Reversing only the INDEX seal reproduces the entire canonical
reader. The auditor does not import or run that reader or any archived code.

## Boundaries

This review reads no private console or execution ZIP. The two excluded private
streams and three omitted implementations are checked by their recorded
identities only. Package members are decoded in memory; nothing is restored or
executed. No native test, Windows API, network call, or repository write occurs.

These receipts qualify selected evidence custody. They do not change the
prepared-probe and three ACL passes, the two production failures, or the open
P0 and historical ACL migration conditions. The Windows45 report remains a
limited argument about the current factory inputs, not a general impossibility
claim about Windows.
