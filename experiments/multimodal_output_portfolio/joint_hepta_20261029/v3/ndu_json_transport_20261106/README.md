# Strict JSON envelope adapter: prospective development unit

This standalone adapter accepts complete native JSON or one complete outer
`json` code fence, then checks an explicit public response schema. It does not
edit either frozen pilot, replay their outputs, revise their scores, execute a
model, or call a tool. It is a proposed development integration for the same
fixed Qwen model and eight disclosed tasks, not a confirmation experiment.

## Fixed acceptance contract

The only added wire form is exactly three backticks followed by lowercase
`json`, LF or CRLF, one complete JSON value, LF or CRLF, and exactly three closing
backticks. Only ASCII space, tab, CR and LF may surround the complete response.
Unlabeled fences are deliberately excluded. The opening line must end immediately
after `json`, and the closing marker must begin immediately after LF or CRLF.
Whitespace may precede the opening marker or follow the closing marker, as part
of the allowed surrounding whitespace. Alternate languages, uppercase language
labels, extra blocks, preceding or following
explanations, truncated JSON, comments and Python code as a response are rejected.

The decoded JSON must use unique object keys at every depth and finite numbers;
`NaN`, infinities and overflow such as `1e999` are rejected. Invalid UTF-8 scalar
values, including unpaired surrogate escapes, are rejected. The whole response
is capped at 65,536 UTF-8 bytes. No extraction, repair, evaluation, key insertion,
type coercion, answer imputation or retry occurs. Text resembling code or fences
*inside a valid JSON string* remains data, which is necessary for source-reading
answers. It is never interpreted or executed.

| Public response stage | Required `Schema` | Accepted value shape |
| --- | --- | --- |
| SQL plan | `SQL_QUERY` | Exactly one `query` string, 1–4,000 characters |
| Source plan | `SOURCE_READ` | Exactly `needle` of 1–128 characters, or integer `start_line >= 1` and integer `line_count` from 1 through 120 |
| SQL direct/final answer | `ROWS_ANSWER` | At most 50 row arrays, each containing at most 32 scalar JSON cells |
| Source direct/final answer | `STRINGS_ANSWER` | Array of strings; no expected lengths or answer contents are encoded |
| Separate qualification | `QUALIFICATION` | Exactly `[1]`, with integer 1; booleans, floats and strings do not substitute |

SQL and source plan schemas preserve the original field and length rules.
`SQL_QUERY` does **not** authorize an SQL statement: even a structurally valid
`DROP TABLE` string must reach the original worker's rejection path if dispatched.
The original `legal_payload`, public-task identity checks, SQL authorizer,
query-only mode, progress/output bounds and source restrictions remain mandatory.
The adapter has no executor and imports no model or tool implementation.

## API and provenance

Use [adapter.py](adapter.py) from a **new** runner; keep existing parsers intact:

```python
from adapter import Schema, decode

decoded = decode(raw_model_text, schema=Schema.SQL_QUERY)
payload = decoded.value
```

The result also contains `envelope`, `schema`, `raw_sha256` and `body_sha256`.
Store the original response and these fields before any tool dispatch. Failures
raise `DecodeError`, with a stable rejection `code`; preserve them as failures.
The decoded value is passed unchanged through the existing checks. Parsing and
schema acceptance do not establish tool authorization, answer correctness or
successful delivery. The existing exact verifier remains the quality authority.

[prospective-protocol.json](prospective-protocol.json) declares the next-stage
contract and binds the implementation, tests and unchanged upstream sources.
The adaptation was chosen **after** the parent observed Qwen fence formatting.
It is therefore disclosed post-outcome development. The prior Qwen anchor is
commit `3006bddacab081bafbd533f5a276d475ca3cb1b7`, draft PR #4979. The model remains
`Qwen/Qwen2.5-0.5B-Instruct` at revision
`7ae557604adf67be50417f59c2c2f167def9a775`; no model search is included.

Before any new inference, bind and publish a separate runner and its complete
source freeze. Preserve the original prompts, greedy decoding, 96-token output
cap, 60-second request cap, 130-second episode cap and 1,800-second run cap.
Use new exclusive result directories. Allow at most one separate qualification,
24 task model requests, eight actual task-tool requests and 16 verifier requests.
A failed qualification aborts the candidate run and records all 16 task episodes
as not started; it does not trigger another prompt, parser variant or model.

Report native versus fenced transport, parser acceptance, legal payload, actual
tool dispatch, delivery and exact correctness separately. Record all wall/CPU
costs, including decoding time, and leave unknown monetary costs null. None of
these development observations would establish NDU advantage, untouched-task
confirmation or positive net benefit. Do not widen this contract after seeing
the candidate run's outcomes.

## Validation scope

[test_adapter.py](test_adapter.py) contains 12 synthetic boundary test groups,
including multiple fences, escaped duplicate keys, nested duplicates, numeric
overflow, UTF-8, byte limits, strict integer types and original tool boundaries.
It does not read old model responses, gold answers, or oracle payloads. The tests
passed; [validation.json](validation.json) records the command and source hashes.
The unchanged earlier source sets are bound in
[frozen-source-boundary.json](frozen-source-boundary.json).

```bash
python -B -m unittest discover -s round3_json_adapter -p test_adapter.py -v
```

This delivery contains zero model forwards, zero tool calls and zero retrospective
output replays. Passing parser tests is engineering evidence, not task success.
