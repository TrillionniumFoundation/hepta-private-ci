# Hepta module technical guide template

Module guides share a small structural contract.  The module-specific body
should describe real APIs, state ownership, callers, failure handling and
acceptance evidence; generic governance prose belongs here rather than being
copied into every guide.

Required sections are numbered 1–16 by the readiness registry.  Section 17 is
the generated source implementation receipt and is produced from the module's
`IMPLEMENTATION_MAP.json` by `scripts/hepta-technical-receipts.py`.

## Source implementation receipt contract

The receipt table contains one row per operation with its operation id, native
symbol, source path and bound test paths.  It is navigation evidence only.
Production composition, runtime activation, independent acceptance and release
remain separate claim-boundary fields in the implementation map.

Keep module-specific details in the guide.  Do not satisfy readiness by adding
arbitrary prose or minimum byte/word counts.
