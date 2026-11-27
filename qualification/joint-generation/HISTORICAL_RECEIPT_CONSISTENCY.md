# Historical inspection receipt consistency

This repairs metadata checking in the published five-artifact storage inspector. Previously, inspect_output rechecked artifact bytes and relations but accepted an existing completion receipt after checking only status and scientific_execution_performed. A stale or edited descriptor/file/relation/root field could therefore survive that check. This did not bypass the independent artifact-byte checks.

The existing restore path and inspection path now share one completion-receipt builder. When a receipt exists its canonical JSON must exactly match freshly verified evidence, including file identities, descriptor, relations, roots and scope. Missing receipts remain valid only for the internal precompletion inspection; that return is not a completion claim. No original scientific record, gzip payload or descriptor is modified.

Compatibility: an existing receipt records absolute source/output roots. Moving either tree causes receipt verification to fail even if artifact bytes match. Do not edit historical receipts to disguise relocation. For a different location, use the existing explicit fresh-output restoration workflow to produce a new receipt, preserving the old one. No automatic restoration, overwrite or retry is added.

Verification uses tiny synthetic files and an explicitly substituted relation function to isolate receipt consistency. It exercises real inspect_output path, file, hash, inventory and receipt checks, but does not qualify historical relations, decompression, model behavior or science. Tests import only the repaired stdlib restore code. All incorrect receipts are synthesized in temporary fixtures; no old implementation is included or loaded.

The exact original published function's output fields are preserved by the refactor. Original58 size-policy violations are unrelated; this change is not a full-branch CI pass, production acceptance or permission to run any historical experiment.
