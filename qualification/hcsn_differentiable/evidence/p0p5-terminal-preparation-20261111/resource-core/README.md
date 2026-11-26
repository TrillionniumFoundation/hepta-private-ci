# Frozen C2 resource program

The original source, tests, and configuration are preserved byte for byte in
[`program.zip`](program.zip). The accompanying [freeze receipt](FREEZE.json)
binds the archive and its original manifest. The original [README](program/README.md)
and [stage definitions](program/STAGES.md) remain available without extracting it.

Restore the complete original program into a new directory before passing it
to the historical validation drivers:

```sh
python3 restore_program.py /path/to/new-program-directory
```

Restoration verifies the archive, its manifest, and every file. It does not run
analysis or grant access to model, training, or production inputs.
