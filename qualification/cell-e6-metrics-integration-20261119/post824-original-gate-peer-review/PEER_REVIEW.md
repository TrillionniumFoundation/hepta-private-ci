# Post-824 blob gate: independent read-only review

**PASS for this exact controller and its current frozen input inventory.** This is a source/inventory review, not execution of the next candidate's blob gate. No final head is certified by this review.

Reviewed controller: `post824_blob_gate.py`, SHA-256 `d46ea0a8266efafd0ac7cbf8301527b5eaaa62f9a1ea1fdcf0e0073dcf5e11f9`.

## Binding and completeness

The controller pins parent `8240292307116aa4063f7c63d8cdf48a0e8ef773`, tree `2ec6ba4ee575eba4daee656ccf3d218074efd65c`, the original preparation controller, and the preceding passing RESULT. It imports objects into a new, initially absent bare object directory. Every imported object must match its recorded length, SHA-256, Git object identity, and actual Git readback.

I independently read all 240 unique objects from the previous object store with `git cat-file --batch`, recomputed their identities, and checked the previous pass receipt. I also verified both extra objects: the exact 5,503-byte workflow tree and the exact 1,331-byte original Codespell workflow. The raw workflow tree reconstructs byte-for-byte from the retained nonrecursive GitHub tree API response, and its identity is linked through the exact 824 base tree. Its Codespell entry links to the expected old workflow blob.

The original manifest reader rejects noncanonical relative paths, verifies file bytes/SHA-256/Git blob identity, and the new controller rejects duplicate paths, unchanged paths, and unsupported file modes. Rebuilding every affected tree must produce the actual candidate API tree. The candidate must have exactly the one fixed parent; unsigned commit reconstruction must reproduce its full Git SHA.

The entire actual added/modified path list must equal the supplied manifest, and a second full status diff rejects deletions and type changes. Thus a partial manifest cannot silently exclude a changed blob while still matching the candidate tree and diff.

## Original gate and mutation limits

The candidate's checker and allowlist are bound to the original Git OIDs and SHA-256 hashes. The exact original checker is invoked with `--max-bytes 512000` and a 120-second child deadline. No allowlist or acceptance rule was widened.

The controller contains no fetch, checkout, reset, push, or ref-update operation. Writes are confined to the new output object store and its receipts. Prior-object reads are `cat-file` only. The actual checker receives a before/after comparison of HEAD, config, index, packed-refs, and refs; a changed identity cannot produce PASS.

My read-only verification also recorded identical prior HEAD/config/index/refs before and after. This environment had no Git location/config overrides; the sole existing `GIT_` variable was `GIT_PAGER`. Assertions were enabled, and `GITHUB_STEP_SUMMARY` was absent. The review does not claim a general-purpose hermetic execution sandbox.

## Scope and receipts

No material acceptance-bypass or source/ref mutation issue was found. The previous `EXACT_OBJECTS.json` is recorded by the controller rather than constant-pinned; this independent review pins its actual SHA-256 `736d68f7a70cd9b2533b30c93118af6c568b253a726b14b4e044fbdf0496c37d` and verifies all 240 actual unique objects. Git identity and the fixed base tree remain mandatory controller checks.

The automated read-only receipt is `READONLY_INPUT_VERIFICATION.json`, SHA-256 `5a8a95899eeb91b544ad26916835268be4b0070ff07288d0a4e9512eef0253d9`. The verification script and all individual object observations are retained. No gate, native test, Cargo command, model call, training update, remote host job, or ref update was run by this review.
