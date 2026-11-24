# Original #6858 daemon CI evidence

This appendix retains the exact completed attempt-1 evidence for source `72fb96148a3d12db0d3482f46ab0653f7353d532`, tree `8e90cff71a6bc5ccdbe85c1d9f50c03fe546a8f0`.

The original run [44867872646](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44867872646), job [136735522608](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/44867872646/job/136735522608), completed with **FAILURE**. Ordinary **2,184/2,184** and the original **46/46 Root parents** passed on the clean source head. The original lost-RPC regression case passed in 0.078 seconds. Later formatting failed on an archived Rust snapshot; maintenance retention then rejected out-of-owner evidence changes.

| Scope | Canonical result | Executor elapsed | Test elapsed |
|---|---|---:|---:|
| Ordinary six packages | 2,184 passed; zero failure/error/XML skip | 663.051068054 s | 268.533 s |
| Root fixed parents | 46 passed; zero failure/error/XML skip | 28.760399203 s | 26.199 s |
| Whole workflow | Failed after native test success | 2,146 s job interval | Nested scopes; do not add |

Nextest separately reported 159 ordinary and 1,614 Root skipped/unselected entries. They are not additional canonical executed cases. The complete result and source/fixture boundaries are in `CI_SUMMARY.md`.

## Restore the exact retained bundle

The 18 binary parts are consecutive slices of the already-frozen `CI_EVIDENCE_BUNDLE.tar.gz`. They preserve its exact outer bytes. The parts, byte offsets, and SHA256 values are in `MANIFEST.json`; every part is at most 360,000 bytes.

```sh
cat CI_EVIDENCE_BUNDLE.tar.gz.part0[0-1][0-9] > CI_EVIDENCE_BUNDLE.tar.gz
sha256sum CI_EVIDENCE_BUNDLE.tar.gz
tar -tzf CI_EVIDENCE_BUNDLE.tar.gz
```

This directory contains only parts 000 through 017. Expected reconstructed size: **6,387,961 bytes**. Expected SHA256:

```text
d3a4e988fddee753149f6a2fb4603d49b37fe5cb899fccc6f69737f349c806d9
```

`BUNDLE_MANIFEST.json` is the unchanged manifest of that 31-member audit container. The container itself is audit-created, while these original evidence bytes inside it are preserved:

- GitHub artifact ZIP **14693493582**, 5,585,270 bytes, SHA256 `dbead6f4108832f2403dc9f939c6395082257c79b56cf5474812e01550b18f73`, independently matched to GitHub's digest; it restores all 42 original artifact members, including both canonical JUnit files and original maintenance failures.
- Complete original job-log tool returned UTF-8 content, losslessly stored as gzip: 4,770,606 decoded bytes, SHA256 `20cb18d711f3b19d60281a172463ce5b8537391b9041c0ce37a57a727c8b6eab`.
- Complete Rust-format and closed-set blocking-job logs, original API responses, pinned source copies and clearly identified audit-derived reviews.

The gzip stores the exact decoded log bytes returned by the connector; no claim is made about preserving the original HTTP transfer encoding. The bundle's format-scope review is a proposal captured at review time, not an implemented repair or new successful workflow result.

## Scope retained

Checkout, before-tests and after-tests source inventories are identical and clean. Native results apply to that published head before maintenance. Final maintenance was dirty, `fmt` failed, retention failed, and the later binary check was not reached. The workflow remains failed.

The Root fixture counts do not replace the separate source-84721 lifecycle-v1 warm Adopt failure or its two cold parents with zero attempts. No external student-weight adoption, model gain, fresh-D recovery, FinalUse, settlement eligibility or deployment is established by this CI result.

This append changes no path in the earlier 32-file evidence package or 9-file lifecycle failure append. Packaging performed no workflow dispatch/rerun, native/model execution, formatter run, source mutation, ignore change or blob allowlist change. Git stores the binary part bytes; base64 is used only for API transport.
