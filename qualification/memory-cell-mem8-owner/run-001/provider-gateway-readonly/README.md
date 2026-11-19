# Original provider journal check and current GET observations

## Result

The original provider outcome remains **UNKNOWN**. The two authorized read-only jobs completed once with exit 0, no automatic retry, and complete authoritative terminal receipts. No native test, model request, owner restart, service change, credential read, or database read was performed.

## Original window

On ai395, current unit metadata reports `dual-llm-gateway.service` with StandardOutput=`journal` and StandardError=`inherit`. One bounded `journalctl --user --unit=dual-llm-gateway.service` query covered **2026-11-11 04:47:00–04:49:00 UTC**, with a 2,000-entry / 4 MiB / 12-second bound. It completed at 2026-11-11T05:53:25.347529+00:00, exit 0, stdout 0 B and stderr 0 B. There were **0 records and 0 exact original identifier matches**. This does not prove completion, failure, or nonexecution. Current unit configuration is not proof of historical configuration.

Only exact matches for the original thread `01a1c8ef-125f-75ae-aaf1-0fe5a4c079f6`, turn `01a1c8ef-1fbd-75b0-bc6e-2b22a1f1f596`, or client key `qualification-e2e-message:Integer(2)` could be projected. A client-key-only match would not prove unique request identity. No unrelated request text or credential value is included.

## Current availability

On Desktop, three separate GETs to the confirmed original port **18083** completed once each during **05:53:41–05:53:42 UTC**. `/health`, `/routing`, and `/v1/models` each returned HTTP 200. The safe health projection was `status=ok`; the current model-list projection contained `qwen38-flash-next-uc`. Routing body content was not retained; only its status, byte count and digest remain.

These are current availability observations only. The diagnostic request identifiers, hashed response-ID metadata, and current model-list IDs are separate from the original inference identity. They do not settle the original turn or reveal the original physical provider request count. Raw GET bodies were not retained.

## Durable identities and readback

- ai395 job: `1a1c92b0b1b-135c4-442`; key: `mem8-provider-journal-ai395-20261111-ed353-v1`.
- Desktop job: `1a1c92b2dac-135c4-444`; key: `mem8-provider-get-desktop-20261111-ed353-v1`.
- Original host RESULT files were read in one complete bounded chunk each and independently matched their reported SHA256/byte counts.
- A later durable stdout/stderr frontend read did not return. Only that waiting orchestration cell was terminated; no remote job or service was cancelled, and no diagnostic was repeated. Its incomplete read is recorded explicitly. Authoritative terminal receipts and complete safe RESULT files are included; raw durable process stdout is not included.

The archive member manifest identifies every included file. The package contains the executed diagnostic source, exact launch identities, terminal receipts, safe results, transfer pins and this audit. It contains no new provider outcome or memory-benefit evidence.
