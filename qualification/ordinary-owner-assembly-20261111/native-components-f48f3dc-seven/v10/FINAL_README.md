# V35 exact-source diagnostic candidate: fetch failed

The unchanged original full entry for `f48f3dc42602f28d8e7e6ab8845d3a02547d1cd8` / tree `384222cf500019cb1293723dd8668eeb35a1e4cb` naturally exited 1 before checkout, formatting, checker, QA, helper or native tests. Original git fetch exited 128 after 194.74196172691882 seconds, without a harness timeout. Its exact log reports connection reset, unexpected disconnect and early EOF. No deeper cause is asserted.

The actual idle preflight and isolated clone passed. Only the reached read-only-reference cleanup passed; the reference head, tree and status were unchanged. No source-clean or nine-check cleanup is claimed. The failed work directory and original receipts are retained. No retry or network/credential/permission repair was performed.

`RESULT.json`, complete `progress.final.json`, `terminal.complete.log` and the three original `logs/` files bind this failure to its exact source, original request and session. Root fetched and independently byte/hash-checked each complete file. The `raw/` read receipts retain the transport evidence. The earlier live checkpoint remains historical and is superseded only as to terminal status.

No native tests or QA were reached. Ordinary complete / positive adoption / NoUpdate-or-rollback counts remain **0 / 0 / 0**. Independent C and real daemon-plus-Root OS restart remain unaccepted. V34's separate failed qualification is not inherited. This six-file diagnostic candidate does not contain the pending same-session phase. Both product PRs remain Draft; nothing was merged.
