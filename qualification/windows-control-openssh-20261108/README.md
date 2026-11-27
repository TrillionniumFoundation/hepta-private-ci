# Windows control-journal and OpenSSH follow-through

This change addresses two concrete failures in the original f491 Windows CI. It does not establish Windows runtime success: this publication has Linux qualification and leaves the Windows result pending CI.

## Source and behavior

Base: f49128e503b24bb52ccdb32a860939e6392c8e08. Code commit: 770569422ea9f5cac8461d8b2ae4b7a48eb1b874; code tree: ab05536448cc2b4079af2ec88024fb58c8ca6107.

- The four Cell control failures read a journal through a second file handle while the owner still holds its writer lock. Tests now observe successful shutdown before full byte snapshots, reopen the same journal, and retain exact replay/conflict and single-worker assertions. An empty journal is checked by its exact zero length. Production locking and the shutdown-timeout lock-retention test are unchanged.
- Windows OpenSSH v9.5.0.0 requires ProgramData in init_prog_paths during initialization. The existing isolated verifier cleared its environment and omitted that value. The repair derives one ProgramData value from SHGetKnownFolderPath(FOLDERID_ProgramData), validates an absolute nonempty bounded path, and frees the OS allocation on both successful and failed API results.
- The production verifier still clears its environment, chooses its fixed OS executable, retains the original file and directory pins, and performs both strict Rust and original OpenSSH verification. The two signing fixtures use the same system-derived ProgramData value. No ambient ProgramData value or guessed drive path is accepted.
- The historical Windows children returned 255 with empty captured stderr. Their actual environment and OpenSSH binary version were not retained. The official initialization requirement and the omitted production value are established; they are not proof that this explains every historical failure. The patch also retains captured stdout on fixture failure to preserve future diagnostics.

The two added windows-sys feature declarations are Com and Shell. The required native just bazel-lock-update completed with exit 0. MODULE.bazel.lock was byte-identical before and after, SHA256 e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb; no lockfile difference was manufactured.

## Validation

Native command, from codex-rs:

    just test --locked -p codex-hepta-neuron -p codex-hepta-operator-acceptance --lib -E 'test(cell_generation_control::tests::) | package(codex-hepta-operator-acceptance)'

The corrected attempt ran 33 tests: all 8 Cell control tests and 25 operator-acceptance tests passed; 166 other tests were unselected. This includes actual journal lock retention during shutdown timeout, recovery without another worker invocation, all G5 trust cases, and the original OpenSSH signature differential oracle. It is a Linux result. Windows-only code was excluded by its target cfg and was not executed here.

The first local attempt failed to compile because removing a parent Command import also removed the Unix differential module's inherited import. That original failure, source tree and logs remain in the capsule. The corrected candidate explicitly retains the import only on Unix.

The executed tree was d28e9603ccea36bcda98aad2e9fe31bb1071b499. Official just fmt returned 0 and changed only wrapping in the Windows module; the other five file hashes were identical. The final code tree is ab05536448cc2b4079af2ec88024fb58c8ca6107. Both patches and all file digests are retained. Tests were not rerun after formatting.

## Evidence

native-evidence.zip contains 37 members, with 36 payloads bound by MANIFEST.json. Its SHA256 is 127f79750f1877d48b79296fd7cd89d703a40f4b5e3b474d9993b17c7526f2f9. It preserves the first failed build, successful rerun, official formatter and Bazel receipts, original process records, source identities and before/after patches.

Upstream excerpts bind the complete source log SHA256 and Actions job URL. The capsule contains the relevant verbatim excerpts, not the complete upstream job logs; those original logs remain separately retained by the common CI follow-through. Duplicate printed log sections are not extra experimental trials.

Official references are recorded in OFFICIAL_SOURCES.json, including the retrieved OpenSSH source hash:

- https://github.com/PowerShell/openssh-portable/blob/v9.5.0.0/contrib/win32/win32compat/w32fd.c
- https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath
- https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-cotaskmemfree

This is a scoped implementation and fixture repair. It performs zero model forwards and zero training updates, grants no authority, and leaves every scientific stage at HOLD.
