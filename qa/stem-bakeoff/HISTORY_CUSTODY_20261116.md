# Restoring Cell research inputs after consolidation

The two Cell research histories retain all original source, data, manifests and failure records in ordinary merge-parent history. The maintained tree represents 169 original data files through exact Git blob custody: 167 files exceed the existing blob limit, and two frozen text-corpus files must keep their original words unchanged.

Before invoking current research readers, follow the [current input restoration guide](../repository-consolidation/20261116/cell-history-custody/README.md#current-consumers-restore-inputs-then-run-current-source). Restore the complete 457-file input closure into a new directory outside the checkout, then run the current maintained entrypoint with its explicit data-directory arguments. The current input mode copies no historical source and executes no code.

The affected input directories are:

- `evidence/20261024-cell-parameter-field`
- `evidence/20261024-cell-parameter-field-v2`
- `evidence/20261024-cell-parameter-field-v3`
- `evidence/20261025-cell-field-v4`
- `evidence/20261025-cell-field-v5-v6`
- `evidence/20261025-cell-state-closure-v4`
- `reviews/cell-field-v8-evidence-archive`
- `reviews/cell-field-v8-remaining-terminal`
- `reviews/cell-field-v8-stop-filter`

Original relative links, archive-part lists and historical reproduction commands within these evidence directories describe the complete original layout. Restore the inputs before using those paths. The small reports and their scientific conclusions remain unchanged; the full original subtrees can also be recovered independently with the historical snapshot mode. Historical snapshot recovery is a separate check from validation of current consumers.

The shared-stem workflow continues to require manual dispatch and explicit operator inputs. Its ordinary contract and shared-feature unit tests use synthetic fixtures and do not depend on these archived research assets. Real-data research retains its original model, corpus, archive and source-identity prerequisites.
