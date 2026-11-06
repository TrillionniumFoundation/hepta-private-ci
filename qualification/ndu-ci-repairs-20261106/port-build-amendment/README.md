# Additive source binding for the existing i18n Bazel alias

PR #5028's real producer passed all 319 committed source, index, mode and tree bindings, then rejected the old i18n vendor inventory before any Cargo or Bazel command. PR #4976 had already added the versioned public Bazel alias from exact donor #4375. That existing BUILD file was included in the old complete vendor inventory but not the original 35 integration inputs.

BUILD_AMENDMENT.v7.3.json is a separate, code-sealed record. It binds the original recipe, integration manifest, formatting amendment and dependency amendment without modifying their bytes. Its sole change is the reviewed 147-to-415-byte BUILD.bazel identity, mode 100644. The producer, artifact consumer and isolated Synapse source guard now bind 320 source files, preserve the empty integrated patch and copy the new record. All native commands and all previous dependency graph, external rules_rs facts, licenses, modes and policy checks remain unchanged.

Local verification used the complete actual 14-file i18n directory, all 284 actual backport files, real temporary Git repositories and negative mutations. The other eight old vendor inventories in the focused function probe were controlled inputs; a separate untruncated remote-tree audit verifies all nine old vendor directories, 2,040 files, have identical Git blobs and modes to #4976. These are source checks, not native compiler evidence.

All 75 port tests, 16 post-qualification tests and seven isolated source/restore tests passed with zero skips. The full 32-method Synapse boundary run retained three AF_UNIX PermissionError subcases in its existing cleanup test; this local restriction is not reclassified as success. The earlier #5028 hosted full boundary suite passed, but the new integrated source must run it again.

The #5028 repository formatter also identified two new Python files. This unit formats its five affected Python files with the exact repository-locked Ruff 0.15.13 wheel, validates its published wheel hash, and runs both format and lint checks. Formatting does not change the native-command or old graph-check ASTs. No formatter exclusions or policy exceptions were added.

ORIGINAL_FAILURE.json indexes the original producer artifact and logs. Concatenate producer-artifact.zip.part-00 followed by part-01 to recover the exact 560,441-byte ZIP, SHA256 7acba3eb8414c7d5879c782e6306025832c3e2a17b9652b7b2a1b2ead3e98878. Each part has its own identity. The gzip files preserve original decoded UTF-8 log bytes without trimming or normalization. Earlier local fixture failures are separately identified and are not passing tests.

Acceptance remains the actual producer on the new complete source head: real locked Cargo metadata, Bazel lock regeneration and check with zero drift, then unchanged consumer/native and full CI gates. No passing result from a previous source head is transferred to this candidate.
