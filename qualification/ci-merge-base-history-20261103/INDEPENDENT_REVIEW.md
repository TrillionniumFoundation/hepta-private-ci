# Independent source review

Reviewer: sibling agent `/root/private_ci_blockers`, read-only review of the
three-file diff before repository formatting. The reviewer did not run the 11
history tests or the real `adaeb185` / `1ef3216` replay. This is a static review,
not an additional test execution.

Reviewed input hashes (SHA-256):

| File | SHA-256 |
| --- | --- |
| `scripts/hepta_ci_history.py` | `31840c13a99ad823bec9437d3b69f38ec07e8b0443bb6351663d1936fa81b9ce` |
| `scripts/test_hepta_ci_history.py` | `456885ca3319feb7fcd8e9b4d815b46b3e2dc30f92180e0bce4d7c7fcfbd9dac` |
| `.github/workflows/v8-canary.yml` | `79d78f7cd028402234bedc20eb36babb8f1fab3477e443ec333149c244f8cdc0` |

The reviewer found no blocking defect within this scope. They checked that the
frontier condition is sufficient: after removing the ancestors of every known
merge base, any hidden history capable of introducing a better common ancestor
would have to remain behind a reachable shallow boundary. The helper therefore
does not stop merely because it finds some common ancestor.

They also checked the exact lowercase 40-hex input validation, exact SHA fetch
refspecs, no-tags/blob filtering, disabled replacement objects, unmoved checkout,
unchanged original modes, exact HTTPS event-origin check, and authentication
restricted to the fetch environment.

Their remaining boundary note is retained: if the remote itself is shallow and
deepening cannot advance, the job fails through its existing timeout. There is
no successful empty-diff fallback and no timeout increase.

Required formatting later changed only the Python layout. `FORMAT_RECEIPT.json`
binds both versions and verifies equal Python ASTs; the exact reviewed/tested
copies remain under `tested-before-format/`.
