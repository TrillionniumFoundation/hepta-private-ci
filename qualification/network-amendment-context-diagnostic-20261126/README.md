# Preserve evidence for the network-amendment context assertion

Base: `eb294db1b084746d3f24ae4a07c7a0d3b1bf8e19`.

The original musl job `140218309355` contains one failed attempt of
`allowing_network_policy_amendment_persists_context_and_bypasses_prompt`.
Its assertion that the policy file contains the allow rule completed, followed
by a failure to find the saved-rule annotation in the first turn's captured
model requests. The raw log contains neither those request bodies nor the
execution result. A later successful retry does not establish the cause.

This change adds failure-only evidence to the same assertion. It snapshots
the same captured requests once, keeps the identical text predicate, and on
failure reports the request count and latest matching `network-amendment-1`
function output as byte length, truncation flag and at most 1024 Unicode
characters. The prefix may occupy at most 4096 UTF-8 bytes before Debug escaping.
Full request bodies, headers and unrelated calls are not printed. The existing
test helper can decode and clone a complete captured output before truncation;
this bounds the diagnostic text, not every intermediate allocation.

No diagnostic expression runs after a passing assertion. The original two
mock responses, one-second exec yield, network timeout, approval decisions,
policy-file assertion and second-turn prompt-bypass assertion remain. There
is no new wait, request, retry or relaxed completion condition.

Source inspection shows persistence, contextual-message injection and pending
approval completion are separate awaited stages, while the fixture answers
the first execution output with `done`. An early process yield or injection
timing is a hypothesis, not a finding from the missing original output. The
production ordering, terminalization guards and injection rules are unchanged.
This diagnostic does not repair or qualify that possible race. A future normal
CI observation must establish what the failed turn actually contained before
any behavior change is justified.
