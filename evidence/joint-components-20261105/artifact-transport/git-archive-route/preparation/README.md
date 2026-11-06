# Exact H1/H2/H3 archive transport request (not dispatched)

Target: `TrillionniumFoundation/hepta-private-ci` (ID 1320694176), **public**.
The approved content is existing retained ELF archives and their frozen metadata.
No operator-root files, credential files or configuration bodies are selected.
The four embedded metadata files per archive are explicitly audited in
`metadata-allowlist-audit.json`; the original index and ELF/member scope stay intact.

One new orphan data branch: `refs/heads/evidence/actual-elf-transport-20261105-93bfc-01`. It has 166 exact files:
162 original part envelopes, three original completion JSONs, one transport index.
Each original part becomes canonical base64 UTF-8 with **no newline** under
`archives/H1|H2|H3/parts/<original-name>.b64`. No split or recompression occurs.
Original data totals 670,306,272 bytes; envelopes total 893,742,124 bytes.
The biggest actual envelope is 5,592,408 bytes, already verified by root using
the connector and bounded local receiver; that separate probe is not a push result.

Remote completion paths are `<original-export-root>/completion.json`; original
parts are direct children of that same root. Cloud completion filenames differ.
The script reads/hash-checks original archives and parts, creates a new isolated
bare repository, hashes the exact 166-path tree and creates one parentless commit.
It fsyncs `prepared-data-commit.json` and `push-intent.json` before one empty-lease
push. Failure/unknown gets only the same-ref readback, never another push/account.
Public read reachability does not prove credentials or permission to push.

Existing HTTPS helper responses stay in memory; approve/store/erase are not
forwarded. Existing HTTPS authorization headers may also be used. This route is
HTTPS-only; an SSH origin is rejected with no protocol or identity fallback.
Embedded HTTPS userinfo and unexpected rewritten destinations are rejected.
Inherited nonempty hooks configuration or existing local hooks cause a failure for
review; hooks are not silently disabled. Five original Git configurations and
the entire fixed source are checked before and after. No source/CI/PR is changed.

The frozen request's new archival limit is 1200 seconds, including bootstrap and
the single push (at most 900 seconds). It does not change any native gate budget.
Root must approve this exact request and release the operational window before
dispatch. No desktop operation or upload has been performed by this package.
Afterward a confirmed ref still needs full independent cloud bytes/member verification.
H1/H2/H3 original failures and capture limitations remain unchanged.
