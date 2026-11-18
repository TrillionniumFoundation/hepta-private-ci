# Completed real second-teacher diagnostic

The second teacher completed all twelve preregistered calls on the same six
authorized A tasks. Strict scoring gives one successful task on the first call
and the same task on the second. The pair does not show mutual complementarity.

| Teacher | First | Final | Selected | Recovery | Regression |
| --- | --- | --- | --- | --- | --- |
| Qwen2.5-Coder-1.5B frozen, retained original calls | 0/6 | 0/6 | 0/6 | 0/6 | 0/0 |
| Existing Qwen3.8-Flash-Next quantized service | 1/6 | 1/6 | 1/6 | 0/5 | 0/1 |
| Union | 1/6 | 1/6 | 1/6 | — | — |

Union coverage equals the better teacher alone. No new student is trained on
these outputs, so downstream learning and negative transfer remain unmeasured.
All six tasks are exposed A development tasks; independent users remain zero.
Neither this result nor the E1 research NoUpdate grants native adoption, FinalUse
or settlement eligibility.

## Actual failures and costs

Both successful calls concern the counter task. Eight calls fail the unchanged
format or restricted-test gate, and two syntactically accepted pair-map patches
fail the business criterion. Three outputs reach the 384-token cap. The larger
teacher often emits assignments or malformed JSON despite the explicit contract;
raw answers were not repaired, stripped or reranked. Every first result receives
its fixed second attempt using the original verifier's actual feedback.

`READOUT.json` records every request, raw-output and verifier digest, exact token
usage and HTTP wall window. It also retains the separate full weight hashing
cost, baseline and reference verification costs, original successful owner exits,
the zero-call failed endpoint attempt and the cancelled read-only observer. These
windows nest and must not be added as if disjoint. Server-wide compute, energy,
other workloads and full historical engineering cost are unknown.

The two teachers have different checkpoints and architectures but are from the
same model family. Logical information, two-call opportunity and output caps are
matched. Hardware, tokenizer, active parameters, quantization and runtime differ,
so this is not a physically compute-matched E3 causal comparison.

## Identity, scope and originals

Sampling source is `16f21699a4cd661ed998333369f3734a572caf96`. Protocol SHA256 is
`56d8c8f9af6ca8b1dbbc628b99070582626bc60e32dc5b1c51ad387a16138944`.
The actual 98,403,356,224-byte weight file was fully streamed and hashed as
`cedf1e08063f6df77926e1169f67b327dcc6301b5b329589615bdf09d4895f7e`.
The current official community license and the GGUF's Apache label conflict is
retained. Execution uses the user-authorized internal research scope; external
commercial rights are not asserted. No service, credential configuration or
throughput setting was changed.

`teacher-originals.tar.gz` SHA256 is
`0ee947fdd6833a46b52a1165795268ac697969c0f2b167ca261c1b71a0e5f132`.
It contains 149 byte-verified remote files plus its original index, including all
raw HTTP responses, all twelve requests and outputs, slot checks, source freezes,
and durable job exits and witnesses. Index SHA256 is
`fe31938e6b0a744d0f0ef253885cb0189b0410ece46c22af623e96e059d4b9c0`.
Local original-verifier receipts and feedback are under `verification/`.
`readout.py` audits original bindings without generating or rescoring answers.
