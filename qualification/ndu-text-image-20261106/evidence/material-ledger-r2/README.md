# Serial material-budget handoff

The cloud pilot now requires a pinned material-ledger index in addition to its
original image-transfer receipt. Later official-source acquisitions share the
same cumulative body-byte cap and must be included before another transfer.

The index uses `hepta.material-ledger-chain.v1`. It names the image receipt's SHA,
retains each later receipt's exact UTF-8 text, byte length and SHA, and declares
the final receipt SHA and cumulative total. Each increment must use
`hepta.bounded-material-increment.v1` and bind its immediate predecessor.

Validation checks terminal status, integer counts, arithmetic, reservation,
unchanged cap, per-attempt totals and saved-body byte/hash metadata. Partial
failed attempts remain charged. In-progress receipts, missing body bindings,
budget rollback and altered hashes fail before a remote image archive opens.
The original image roster, candidate manifest and exposure history remain pinned.

Both `run` and `transfer-images` require these additional arguments:

```text
--material-ledger-chain /path/to/MATERIAL_LEDGER_CHAIN.json
--material-ledger-chain-sha256 <sha256-of-exact-index-bytes>
```

The dispatcher must select the latest terminal head and serialize consumers.
A valid older prefix is still a valid prefix: this parser does not prove global
freshness, exclusivity or the absence of concurrent spending. The index and all
input receipts must be retained with the execution evidence.

## Observed handoff on 2026-11-08 UTC

The original CPU image-transfer anchor was followed by the official VizWiz
scorer acquisition and then the original SQuAD acquisition. Offline validation
accepted their unchanged original bytes:

| Item | Value |
| --- | --- |
| Cumulative material body bytes | 18,348,465 |
| Existing cap | 26,214,400 |
| Remaining body bytes | 7,865,935 |
| New HTTP body bytes for this validation | 0 |
| Ledger index SHA-256 | `b2d49555e3cdcb534419d097d9b0aab0e5100cbe4efd080464a96d1b294d2c62` |
| Final receipt SHA-256 | `0bd406741fa3c54a34df15bbad3a31fde1e4dc8673a700227803f639f4400dbf` |

Seven targeted software tests passed, including transfer admission, retained
failed spending, child-command failures/timeouts and malformed-ledger rejection.
The initial sparse-checkout dependency failure and the earlier candidate before
independent review are retained in private evidence. Mechanical Ruff formatting
preserved the tested AST.

This change prepares a future bounded worker. It produced zero model
predictions, zero independent training repetitions and no factorial results.
Overall scientific status remains Inconclusive / HOLD.
