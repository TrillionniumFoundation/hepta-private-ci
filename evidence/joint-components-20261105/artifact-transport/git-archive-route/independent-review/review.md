# Independent review of the frozen HTTPS archive transport

**Verdict: no identified blocking defect in the exact HTTPS-only package.** This is a local source and byte-binding review. No remote credential lookup, push, native test, archive export, or download was performed by this review. Root owns the final dispatch decision.

The reviewed runner is `1676fdc30a8bbd60c51fd087eebdf6c9e44de83405a5d70e0c55029911e34626`; plan is `5a27e3f47c70b210d5d0a944dd43ef6c270405851f0259e3ee9f4fa9c43e8a3b`; exact launch request is `15e215b7c44aecda1d4f038a7ae5b5f257bb20b00cdd7cf6f39ed09ff87165e4`. The package's eleven declared files, three bootstrap members, request stdin, plan/self pins and original completion/part lists were independently compared as bytes.

## Destination and bounded publication

The existing authorized repository is **TrillionniumFoundation/hepta-private-ci**, ID **1320694176**, with observed **public** visibility. The name is not evidence of privacy. The original repository response is preserved. Neither public reachability nor an existing credential proves write authorization or successful publication.

The only proposed destination is `refs/heads/evidence/actual-elf-transport-20261105-93bfc-01`. A fresh isolated bare repository creates a single parentless data commit with exactly 166 mode-100644 blobs: 162 canonical base64 envelopes of the original parts, three original completion files, and one transport index. No candidate source, workflow, PR or learning input is added. The exact part count and sizes are:

| Phase | Original parts | Original bytes | Envelope bytes |
|---|---:|---:|---:|
| H1 | 32 | 130,746,864 | 174,329,236 |
| H2 | 62 | 256,132,128 | 341,509,668 |
| H3 | 68 | 283,427,280 | 377,903,220 |
| Total | 162 | 670,306,272 | 893,742,124 |

The largest envelope is 5,592,408 bytes. Original part offsets, names, SHA256 values and completion bytes are preserved; parts are neither recompressed nor re-split. Remote completion paths correctly use each original output directory's `completion.json`, and original parts are direct children of that directory.

## Reviewed refusal and reconciliation boundaries

The final runner accepts only the existing HTTPS origin for the fixed repository. SSH is rejected before any SSH invocation or fallback. The earlier SSH option-appending concern is therefore excluded from this frozen route, rather than assumed solved by appending options. Embedded HTTPS userinfo, a different destination, a redirect or cookie route, and an isolated-repository URL rewrite cause refusal.

Existing HTTP settings and credentials stay in process memory. The original helper receives only `get`; `store` and `erase` are not forwarded. Raw Git streams, the origin URL and credential contents are not persisted. Any configured `core.hooksPath`, including whitespace, or any existing non-sample hook causes refusal. No inherited hook is disabled or overridden.

The script pins the complete source guard and compares its full raw-worktree identity, plus five original Git configuration hashes, before preparation, before push, and afterward. The new bare repository's init-generated config must remain byte-identical. These are required runtime checks; the static review does not assert they have already run on desktop.

The exact tree and orphan commit are prepared before a single empty-lease compare-and-swap push. Prepared commit and push intent are written and fsynced before the push. Success, failure or uncertainty is reconciled only by reading the same ref and comparing the prepared commit. No automatic push retry, alternate account or ref overwrite is introduced. The new 1,200-second archival bound includes bootstrap, hashing, packing, one push capped at 900 seconds, and ref readback; it does not alter native budgets.

## Evidence scope

The owner preserved five cloud utility outcomes, all passing in 0.027 seconds. Their raw output and exact test source were read; they were not rerun or described as native, credential, or push evidence. Original exporters admit four exact metadata files per archive, plus the existing image/index members. H2's incomplete second-daemon prefix remains incomplete; H1's three missing per-case observations remain missing; H3's FinalUse capture failure remains a failure.

A confirmed ref is only publication evidence. Complete independent cloud readback, original part reconstruction, whole archive hashes, every member and the H3-dependent H4 consumer must still complete. This review makes no release, WAN, full runtime closure, or historical native success claim. Existing bulk download pause state was not modified.
