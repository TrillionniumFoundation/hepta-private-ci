# Actual v3 target recovery attempt: stopped before creation

The exact reviewed request 15d6e1c17bf2bbb72f855cbe45ff334fa45040e9 ran as H job `1a1d0ae00c6-2564-1bb3`. The authoritative original terminal is **failed / exit 1**, complete and durable, with no timeout or cancellation. The full original 655-byte stdout and 624-byte stderr are retained, and their lossless byte cursors and hex/text equality were checked against the terminal log counts.

The observed `/data` parent remains device 2067, inode 2, UID 1000, mode 0o40755, with 194867552256 bytes free at the check; the original identity and 64 GiB minimum gate passed. The preflight observed `FileNotFoundError` for each original v1/v2 target path. This does not establish whether their parent directories existed.

The script then stopped at line 72, the first private V8 asset's full-hash admission. `hash_owned` at line 33 could not lstat `/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz`. The prior three historical receipt/manifest hashes had already passed. The reason for the missing archive is unknown. The binding.rs asset was not reached, so this attempt establishes neither its current existence nor its absence.

The failure occurs before the first mkdir. This job created no v3 target or recovery evidence directory, downloaded or copied no asset, and ran no helper or native test. The original output-file read separately returned FileNotFoundError for the missing recovery directory. No success receipt or new identity exists for this attempt, and no old e5c/441 record has been relabelled.

Both source roots were checked before preflight: fixed 453/tree8cbd and the preserved a671/tree647b. Because the failure occurs before the report/try block, there is no after-check creation receipt; this directory does not invent one. Any asset restoration must retain the exact original V8 version, lengths, complete hashes and existing-file protections, and any later creation/native request must record its own actual result. Ordinary acceptance remains zero.
