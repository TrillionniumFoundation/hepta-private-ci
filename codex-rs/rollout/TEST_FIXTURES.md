# Rollout fixture homes

Run the owning package with `just test -p codex-rollout` from `codex-rs`.
Rollout tests create temporary homes through the private, test-only
`test_support::private_temp_dir` helper. It requests Unix mode `0700` at directory
creation, so a group-writable caller umask cannot create a shared SQLite home.
Other platforms keep the temporary-directory implementation's defaults.

The helper covers recorder, metadata, state database, compression, name index,
reference index and history fixtures. Keep their file contents, expected
metadata, compression permission assertions and recovery outcomes intact when
changing fixture setup. Tests which set file permissions explicitly still own
those permission transitions.

Product SQLite initialization validates existing home and dispatch-lock
ownership and permissions. The helper creates new test directories; it does
not change that validation, alter the process umask or repair an existing
product directory. After a fixture correction, run the complete owning package
and retain any previous failure logs under their original source identity.
