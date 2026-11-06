# Windows fixture evidence supplement

This supplement preserves the exact original and candidate files, patches, definitions, source bindings and actual formatting, spelling and forward/reverse patch receipts for draft PRs [#5049](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5049) and [#5050](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/5050). The earlier native checkpoint remains unchanged.

The Matrix change adds failure-stage context only. The original generic Initialization error does not establish whether client construction, session publication or reload failed first. The TUI change gives the fixture an owned working directory and requires actual child output before interruption. Its existing shutdown assertions and timing limits remain intact. The original Windows failure log is already preserved in the native checkpoint; neither change is represented as a native pass.

Restore these twelve original evidence files into a new directory outside this bundle:

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The restorer is the reviewed Core v3 implementation with only the fixed index hash, allowed archive root and descriptive title adapted. It checks every exact regular-file member before writing, preserves safe regular modes, never writes into the input bundle and reports to stdout. The separate actual restoration receipt establishes byte integrity only. No Rust compilation, Windows execution, crash-durability experiment or full-source CI qualification is performed by this package.
