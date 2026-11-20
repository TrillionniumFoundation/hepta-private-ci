# Exact candidate blob gate readback

The unchanged repository blob-size gate passed once on the complete PR range `e4b4eb5028578be87d5cad0829103632f2bff3a3..b6822f9afe283e1e1b4493173ee98cc2f740ef0a`: 104 changed files; maximum 500,000 bytes; limit 512,000 bytes. The executed candidate tree is `ace010f9ff23207de53c5941db73c11079fc8034`. Exit code 0, wall time 0.9883465460152365 seconds. See `blob-gate-b682-full-pr-1/RESULT.json` and exact stdout.

The earlier restored-source gate is separately retained: `e4b4eb50..1818fde5`, 41 files, exit 0, 0.3766644010320306 seconds. Neither result is a claim that a later receipt-only evidence commit was itself executed by this gate. A final evidence commit must retain its own precise changed-blob budget check and identity.

## Object repair and failed attempts

The partial clone lacked original blobs and lazy fetch stalled on precise reads. The original root-owned 120-second gate timeout and 5-second diagnostic remain intact outside this addendum. Nine missing original object/file byte sequences were restored from their exact Git source identities. The exact candidate commit/tree fetch completed, but a separate 56-blob fetch timed out after 30.034390680026263 seconds and was terminated; its intent, exit -15, empty streams and result remain here.

The fallback reused the already retained original bytes: 56 unique missing blobs in 22 create-only bundles totaling 21,629,163 bytes. Every source and remote bundle, every original blob SHA256, and every Git blob SHA were checked before `git hash-object -w --stdin`. The complete 104-path candidate closure was then read from the object database. The restoration and gate kept the detached checkout at `1818fde55d964a87cfc8aed49f26a6a866a0e0a5`; refs, configuration metadata, index metadata, gate source and allowlist were unchanged by these operations. No source-policy change or new allowlist exemption was introduced.

## Scope and costs

This is repository evidence restoration and verification. It adds zero model loads, model generation calls, training updates, and task-native evaluation children. Git, hash, transfer, diagnostic and Python-controller work did occur. The recorded stage wall times and available owner CPU measurements are preserved; they are not an assertion of measured full-system energy or a complete additive end-to-end cost. An early metadata read while a result file was not yet complete returned a helper INVALID_ARGUMENT; the later complete readback succeeded. No unknown model job was replayed.

The candidate objects were installed only in the isolated verification checkout. This subagent moved no local or GitHub ref. The parent owns any later compare-and-swap publication.
