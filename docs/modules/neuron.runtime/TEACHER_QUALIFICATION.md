# External teacher observation, provider and data-use contract

## Separate evidence owners

The requested local Codex-auth model is `gpt-6-luna`. A request string, configured
catalog entry, model self-description or successful nonce exchange is not proof of
the actual served model, tool isolation or permission to train from its output.
Keep these decisions separate: advisory connectivity, authenticated provider/model
identity, execution isolation, input/data-use admission, output-training rights,
and admission of a specific teacher dataset to a specific training purpose.

`codex-rs/hepta-neuron/qualification/teacher_connectivity.py` is a bounded reader
of retained OpenClaw Gateway observations. It makes no provider request, reads no
credentials and retries no uncertain operation. It is NOT a native Codex JSONL
adapter. A native CLI event log must not be relabelled as Gateway `agentMeta`.
Native output without transport-owned model identity leaves that identity unproved.
All provider, rights, data-admission, acceptance and activation flags emitted by
this diagnostic remain false even when advisory connectivity is observed.

## Gateway diagnostic contract

The catalog, response and diagnostics are bounded; duplicate/non-finite JSON is
rejected. A returned run ID is retained for reconciliation even on an error.
Outer and inner `ok` fields, when present, must be actual booleans. Explicit inner
denial or nonterminal status cannot be overridden by outer success. Completion
requires literal `meta.aborted=false`, no result/provider error, the exact requested
provider/model, a single nonce-bound JSON text payload and no media attachment.
Payload `isError` must be absent or literal false, not 0, null or a false-like string.
The payload's advisory/training flags are also typed, not truthiness conversions.

Malformed `ok` flags report `invalid_gateway_flag`; inner denial reports
`gateway_error_reconcile_before_retry`; nonterminal state reports
`gateway_not_terminal`. These are diagnostic classifications, not operation truth
or authorization. Historical observations retain their validator digest. A later
stricter validation is a separate observation, not a rewritten old receipt.

The CLI stores only bound hashes and safe diagnostic fields, creates its output
exclusively, and exits 2 when connectivity is not established. Preserve the raw
observation under its existing restricted evidence owner; never commit credential
files, tokens, account identifiers or unredacted diagnostic/prompt content.

```sh
cd codex-rs/hepta-neuron/qualification
python3 -m unittest -v test_teacher_connectivity test_teacher_entitlement \
  test_teacher_connectivity_boundaries
```

Fixtures and local CLI subprocess tests verify parsing and immutable evidence
behavior only. A missing response, local exit, timeout or process kill never proves
that a remotely dispatched request was not executed. Use the same operation/run
identity for reconciliation; do not switch providers/models or retry blindly.

## Native Codex nonce observation profile

`teacher_native_observation.py` separately validates retained native CLI JSONL.
It never calls Codex, reads an auth file, executes a tool, retries a request or
imports Gateway identities. The narrow profile requires exactly one thread and
one completed turn, bounded typed usage counters, valid item lifecycles, exactly
one nonce-only agent message, the same nonce in the final-message file, and an
observed local exit code zero. It admits closed reasoning events without copying
reasoning text into its report. Tool activity, extra messages, unknown events,
contradictory fields, duplicate JSON, truncation and post-terminal events reject.
Unsupported events mean this profile cannot validate the observation; they are
not evidence of provider rejection or permission to retry.

The report retains thread identity and input/validator hashes, not raw prompts,
reasoning, diagnostics or credentials. An already observed completed turn remains
visible when the local exit is missing or nonzero. This grants neither retry nor
proof of remote nonexecution. Separate terminal-event, nonce-reply and final-file
observations scan the whole bounded stream even when an earlier startup error
rejects its sequence. They are observations, not a valid-turn or connectivity
verdict; later success cannot erase an earlier error. The requested model is caller context:
actual provider/model stay null; provider qualification, tool isolation, training
rights, dataset admission and activation stay false even after a successful nonce.
A lack of observed tool calls cannot prove that tool execution was impossible.

The CLI creates a new private report exclusively and never overwrites a previous
observation. Each input is bounded to 256 KiB and the event stream to 256 entries.
Validating an older event stream with a newer validator is a new validation of
historical input, not a fresh provider call or evidence from a newer execution SHA.
This package-local diagnostic profile is not a new public wire schema or owner.

```sh
python3 -m unittest -v test_teacher_native_observation
python3 teacher_native_observation.py --events /restricted/events.jsonl \
  --final /restricted/final.txt --diagnostics /restricted/stderr.txt \
  --requested-model gpt-6-luna --nonce NONSECRET_NONCE --exit-code 0 \
  --output /restricted/new-native-observation.json
```

## Actual provider qualification experiment

Use the existing authorized local account without copying its credentials. Bind
the executable and reviewed configuration, requested model and auth route, clean
read-only workspace, nonce, deadline, cost limit, process/session identity and
complete terminal observation. Check supported options against the installed CLI;
ignore user/project configuration only through its supported mechanism. No project
or training data is needed for the initial nonce-only connectivity observation.

Provider qualification additionally needs transport-owned actual provider/model
identity, the applicable account/model entitlement, independently observed tool
and network restrictions, and error/cancellation/unknown-result handling through
the existing operation owner. A configuration echo and a model-generated identity
are insufficient. If the transport omits identity, retain that limitation rather
than filling it from the requested model. Isolation needs executed evidence, not
merely a command-line flag or the model's promise not to call tools.

## Account-specific rights and dataset admission

Before teacher output enters training, the responsible rights/data owner must
identify the actual account/product agreement and any controlling written terms,
then record the reviewed scope: permitted inputs, outputs, training purpose and
model, redistribution/deployment restrictions, effective dates, retention and
revocation handling. Store a restricted evidence reference/digest, not private
agreements or account data in source. Repository administration permission cannot
supply a third party's training rights; output ownership alone is not that review.

The official Services Agreement and consumer Terms have different scopes. The
Services Agreement's section 3.3(e) includes a defined Permitted Exception; do not
replace that conditional language with either blanket permission or a blanket ban.
The account's applicable agreement, exact exception conditions and written terms
must be evaluated for the intended use. This contract is an engineering admission
boundary, not an account-specific legal determination.

Once rights and input admission are established, bind each dataset to exact
provider observations, collection/code versions, transformation provenance and
allowed use. Keep diagnostic nonces and unadmitted outputs out of training. Teacher
agreement is an advisory label, not ground truth: retain independently observed
environment outcomes, human review where required, student-state coverage and an
untouched prospective holdout. Hashes establish integrity, not permission or truth.

Official references rechecked 2026-09-30. The current Services Agreement and
ROW consumer Terms both state an effective date of 2026-01-01; their scopes are
not interchangeable. The Services Agreement applies to specified business/API
products and its section 3.3(e) preserves a defined Permitted Exception. Consumer
Terms separately prohibit use of output to develop competing models. Neither
successful CLI authentication nor a Pro plan establishes which agreement or
exception covers the proposed teacher-training/distribution use. Record the
applicable account/product and controlling written terms rather than inferring
permission from repository ownership. This remains unresolved until reviewed by
the responsible rights owner; this document grants no rights.

Resolve current applicable versions at use:

- [OpenAI Services Agreement](https://openai.com/policies/services-agreement/),
  scope, sections 3.3, 4.1 and the definitions of exceptions.
- [Consumer Terms of Use](https://openai.com/policies/row-terms-of-use/),
  scope and output-use restrictions.
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive/),
  event-stream, configuration and credential-handling documentation.


### Service availability is not this provider's qualification

Official availability checked 2026-09-30: [GPT-6 Sol and Luna](https://openai.com/index/introducing-gpt-6-sol-and-luna/)
are announced for Codex and the API; [Work and Codex access](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)
still depends on the plan, workspace settings and rollout. This resolves the
public model-name/availability question only. It neither demonstrates which model
a particular native request served nor qualifies its isolation or training use.
An old Gateway rejection is transport-specific historical evidence, not proof
that the separately announced native/API model does not exist.

The reviewed public Services Agreement and ROW consumer Terms remain effective
2026-01-01 at this check. Their scope differs; do not apply a Services Agreement
exception to a consumer subscription by analogy. The engineering receipt should
bind the rights owner's decision reference, governing agreement/version, account
route, permitted training purpose and distribution scope, validity period and
revocation policy. If any of these are unresolved, record that field as unresolved
and keep dataset admission closed. This specification is not the rights decision
and does not authorize new teacher collection. Diagnostic nonces remain excluded.
