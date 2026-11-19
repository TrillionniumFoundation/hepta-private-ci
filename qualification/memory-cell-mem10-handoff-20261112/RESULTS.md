# MEM10: exact provider handoff, no causal benefit claim

**Draft / HOLD / NoUpdate. Zero real-model calls and zero new scored memory-benefit episodes.**

This narrow stage continues #6098 at `865cfadced0bedb6de397115e34bef481a46e8b1`.
It sends the exact request bytes framed in a supplied successful launch's stdout,
checks expected actor/launcher labels and pins, and retains transport evidence.
It does not authenticate that launch's custody or remote model execution.

## Implemented boundary

- One text Responses request with a fixed route/model and `store=false`;
  conversation, tool and cache-control extensions are rejected. Body bytes are
  never rebuilt or augmented. Proxy configuration is digest-bound; inherited
  proxy/CA settings remain in force. No credentials or cookie jar are introduced.
- Stable request identity reserves and syncs a journal directory before sending.
  The caller provisions its durable parent and reuses the same journal root.
  Exact re-entry returns retained evidence; conflicting identities are rejected.
  Interrupted admission and uncertain transport never cause another send.
- Complete HTTP responses, including errors/redirects, are retained as RECEIVED.
  Redirects are not followed. Disconnects, size limits, framing ambiguity and
  missing/corrupt retained bytes remain UNKNOWN. No automatic retry exists.
- The launch, request, response and response headers are pinned. The attempt
  counter is not a server-observed physical-request count. HTTP success is not
  model success; server cache/history and model artifacts remain unverified.
- Socket timeouts and chunk-boundary elapsed checks are not a hard process
  deadline. Use an outer supervisor, as the 60-second CI command does.

## Validation and identity

The final transport suite passed **16/16**, zero failures/skips, using real
localhost HTTP servers and synthetic framed launches. It covers exact bytes,
identity/replay, failed actors, forbidden history/tool input, 503, redirect,
post-receive disconnect, short/duplicate framing, overflow and evidence tampering.
The existing causal contract passed **16/16** on clean local source. These are
32 distinct software controls, not model or memory-benefit episodes.

Tested local source: `43e7a8f053d04f2b4feec90384ada22c24cd7f0a`, tree
`250ef3de911783e310ca22703b7aced5f4da18e5`. Final repository `just fmt` exited
zero; both Python ASTs stayed identical to tested bytes. Tests were not repeated
after formatting. Formatted source: `606ff40892d762802211812c1a2de9b507f039fa`,
tree `8cf4b4dd5cf6c214c7750760d7696be1ba937e91`. Ruff check and diff checks passed.
Publication commit metadata may differ; compare complete trees and file bytes.

[EVIDENCE.json](./EVIDENCE.json) binds complete final logs, tested/formatted
postimages and archive hashes. [raw-validation.tar.xz](./raw-validation.tar.xz)
also retains the earlier 15-test subset, summaries of early invocations whose
complete raw logs were not saved, and a rejected CI-wrapper setup invocation
that executed zero tests. No missing original bytes are reconstructed.

## Remaining adoption gates

This transport has no default authenticated observer and emits no
`AuthenticatedObservation` or REAL_MODEL assertion. The causal scorer still
requires independent provider, original-owner, timeline and exposure authority.
An E-specific source roster, semantic A/C review, analysis and full physical
cost protocol remain prerequisites for real scoring. Learning association and
retrieval heads remain unavailable until separately implemented and qualified.
The hosted namespace failure and all inherited adoption gates remain open.
This stage does not rerun MEM5/MEM6 actors, merge the stack or deploy it.
