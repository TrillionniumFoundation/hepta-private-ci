# Match the parsed bare-deny rationale in the exact-trigger fixture

Base: `eb294db1b084746d3f24ae4a07c7a0d3b1bf8e19`.

The original musl job `140218309355` still failed the exact network-trigger
fixture. The bounded diagnostic introduced in the previous source cut now
shows the mismatch in all three preserved native attempts. The 29 recorded
response observations use two existing transport forms: exec-command Debug
errors (673 bytes) and write-stdin Display errors (451 bytes). They are not 29
independent native attempts.

The fixture returns the bare JSON `{"outcome":"deny"}`. The existing production
`parse_guardian_assessment` fills its missing rationale with
`Auto-review returned a deny decision without a rationale.` and assigns high
risk. The existing unit test for a bare deny already asserts this complete
assessment. The later review formatter uses that nonempty rationale directly;
its separate empty-rationale fallback therefore does not apply to this input.

Only the two expected-rationale arguments in the exact-trigger integration
fixture change to the parser's existing normalized value. The strict output
parser still checks the exact requested rationale, transport form and call or
poll identity. Its negative cases, all approval decisions, production parsing,
formatter behavior, terminal-output checks, original trigger equality assertion,
request limits, nine-poll maximum and one-second yields remain unchanged.

The existing progress-parser example using the formatter's fallback remains:
that parser accepts an explicitly supplied expected rationale, and the example
is still a valid check of its strict matching semantics. No alternate reason,
generic error or broad substring is newly accepted by this correction.

Three complete raw attempt logs and both existing producer/formatter stages
bind the diagnosis. Local work verifies source identity, full-file inverse,
protected sources and locks, formatting and preserved output observations.
This is a test expectation repair, not a change to the production denial or a
native pass claim. Normal CI must establish the new fixture's actual result.
