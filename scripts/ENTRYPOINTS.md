# Script navigation

Generate current references from Git-tracked source instead of maintaining a
second checked-in inventory:

```sh
python3 scripts/hepta_entrypoints.py --format markdown
python3 scripts/hepta_entrypoints.py --format json
```

The generator excludes virtual environments, dependencies, symlinks, untracked
files and non-executable metadata. It reports full-path references, static local
Python imports and explicit unittest discovery patterns without executing code.
A textual reference can occur in a comment; a discovery pattern can be skipped
by its enclosing workflow. Neither is a test-pass or liveness claim. Dynamic
imports, external callers and unsupported shell forms remain unknown.

`unknown` means inspect the owner and actual invocation before removal, never
"safe to delete". Output goes to stdout; ordinary development does not require
regenerating or committing an inventory. The old JSON snapshot was retired
because it included environment files and misclassified discovered tests.
