# Explicit original-route output-cap witness

`hepta-native-provider-cap-witness` is separate from the ordinary connectivity
marker. It is an opt-in research executable, not a production native agent or
primary A/B admission. Without `--run`, it validates arguments and prints the
plan without loading authentication/configuration.

The original successful marker supplies the expected model, provider ID,
scoped-auth policy label and exact request-settings evidence SHA. The binary
compares those against the same original installed owners before admission.
It preserves configured reasoning effort, summary, verbosity and service tier.

```sh
hepta-native-provider-cap-witness \
  --evidence-dir /absolute/new/private/cap-witness \
  --expected-model gpt-6.1-sol \
  --expected-provider-id openai \
  --expected-auth-policy configured_jwt_only \
  --expected-request-settings-sha256 "$CAP_SETTINGS_DIGEST" \
  --maximum-provider-input-tokens 8192 \
  --requested-wire-output-tokens 32 \
  --maximum-elapsed-seconds 60
```

Use the actual original labels and digest; do not fabricate missing marker
evidence. After the owner has admitted this concrete new trial, `--run` sends
one request, using a new evidence directory and a fresh original consumed
lease. There is no automatic retry, backend/auth/model replacement or removal
of a rejected cap. A local deadline does not prove provider generation stopped.

The fixed harmless prompt requests all integers 1 through 256, one per line,
without omission. The cap is explicitly constrained to 16–64 tokens. Ordinary
short completion is inconclusive. A successful witness requires original raw
`response.incomplete` / `max_output_tokens`, valid actual usage within the
declared bounds, no unexpected tool, retained original reservation and both
original terminal ACKs. Contradictory/invalid limit echoes reject the witness.

The raw incomplete event is written by the same private continuation owner to
`provider-opaque-incomplete.json`. `provider-incomplete.json` binds its digest,
original request/turn/admission, actual usage and full held reservation. The
policy terminal stays `Indeterminate` with that receipt digest, and the encoded
terminal also stays `Indeterminate`. It does not produce a completed/replayable
continuation or authorize another round. Missing/invalid usage is retained raw
and never replaced with zero. A private-retention failure still invokes both
original conservative terminal owners.

An observed witness is scoped to this exact request. The public Responses API
[documents max_output_tokens](https://developers.openai.com/api/reference/resources/responses/methods/create),
including reasoning output, but that documentation alone does not prove that a
different installed ChatGPT-auth backend implements it. Before a witness, the
requested limit is unqualified; after one witness, complete financial or
multi-turn budgets are still unqualified. The program always reports primary
A/B as `not_admitted` and complete provider hard budget as unqualified.

The original governance seam protects admitted attempt identities and blocks
automatic retry of Indeterminate bindings. Numeric reservation evidence here
remains in the same qualification owner; it is not a new production token-quota
or financial ledger. Never print the raw private provider file.

Scoped tests cover exact final cap bytes, original settings, default-wire
preservation, incomplete raw usage/unknown fields, server-keeps-SSE-open
delivery, invalid usage/echo, actual loopback transmission, cap rejection with
no retry, original-owner retention failure, reservation/cap mismatch before
dispatch and conservative witness decisions. A loopback fixture is not a real
provider result.
