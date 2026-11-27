# Windows durability and SSHSIG source candidate

Baseline: 922f5f9cb258e91d5dafa2a457cf674defd95643. Original failing Windows job: 140594591636, run 46025167575. Full raw failure is preserved separately under common-current-ci-d0f3-20261127.

Production directory flushes now hold real writable Windows directory handles, reject reparse-point aliases, and propagate the actual flush result. The existing terminal-owner fixture opens a real writable directory handle. The authority-owner test first proves that the live child lock prevents rename, then drops that lock while retaining the independent directory anchor and proves that the renamed original retains its state.

Windows now verifies the pinned single-principal Ed25519 SSHSIG version-1 profile using existing base64/Ed25519/SHA dependencies. Unix retains the original OpenSSH process. The reserved wire field is ignored exactly as OpenSSH's verifier does: the signed reserved field is empty. No trust policy, revocation, authority, or lifetime check is removed. Existing test key generation uses the trusted OS OpenSSH binary; on Windows its absolute location is derived from GetSystemDirectoryW.

Actual Mac native checks: original just fmt exit 0; original two-package nextest command exit 0, 67 executed cases passed. The one original ignored entry is the durable_process child worker, which is invoked by the passing parent cross-process fixture. Scoped original just fix exit 0; its one unrelated fixture-only style rewrite was recorded and restored. After independent reserved-field review, the complete operator suite executed 29 cases with zero skips and passed, including real OpenSSH SHA-256/SHA-512 interoperability, the nonempty reserved variant accepted by independent OpenSSH, every-byte mutation/truncation, and wrong message/key/principal/namespace controls.

The first pre-review source snapshot and logs remain in the archive. Windows-specific behavior and all four original affected targets still require the new actual Windows job. This candidate is not a claim that the full Bazel matrix passes.
