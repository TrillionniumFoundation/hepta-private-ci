# HIA bridge to the original NDU algorithms

This standalone executable calls `codex_hepta_ndu::evaluate_recursive_utility`
and `codex_hepta_ndu::evaluate_candidates_with_policy` from the unchanged native
owner crates. It does not contain a Python replacement evaluator. Its own Cargo
workspace and lock describe only this executable and its dependency closure;
the application workspace and Bazel dependency graph are unchanged.

The corresponding public Hepta adapter is `hepta/hia_ndu.py`; its build entry is
`tools/build_hia_ndu_bridge.py`. Point that builder at this repository, a Cargo
and rustc executable, and a writable output directory. The builder creates an
identity manifest binding the exact native Rust files, their workspace
dependency declarations, the bridge and lock, compiler version and executable
SHA256. No source archive or replacement implementation is downloaded by the
builder. Cargo may download the dependencies named in the standalone lock.

## Protocol

One bounded JSON request is read from stdin, one JSON response is emitted, and
the process exits. `--identity` returns the identity embedded during compilation.
The request schema is `hepta.hia.ndu.request.v1`. Unknown or repeated fields,
floating-point integers, invalid identities, over-limit inputs and missing
required fields reject. The input limit is 1 MiB, with at most 128 candidates
including a literal `abstain`. Each path contains 1 to 512 ordered events.

The complete request contains:

| Field | Meaning |
| --- | --- |
| `objective_digest` | Frozen objective, including semantic and performance contract |
| `snapshot_digest` | Exact IR, target, verifier, owner and resource state |
| `generation` | Nonzero immutable generation |
| `utility_unit` | Bounded stable identifier for the registered utility units |
| `resource_unit` | `nanoseconds`, `microseconds`, `bytes` or `modeled-work` |
| `risk_unit` | `probability` |
| `resource_budget_q32`, `risk_ceiling_q32` | Nonnegative hard ceilings |
| `candidates` | Fully disclosed paths and independent evidence identities |

All numeric quantities use signed Q32 integers. Risk and uncertainty are in
`[0, 2^32]`. A candidate contains `id`, `verified`, `verification_digest`,
`support_digest`, `resource_cost_q32`, `risk_q32`, `uncertainty_q32`,
`terminal_q32` and `events`. Each event contains `event_digest`,
`preference_digest`, `instant_q32` and `discount_q32`.

The original recursive function computes the complete supplied continuation
backwards, with its original ties-to-even arithmetic. Actual or modeled refusal,
rollback and control costs belong in their event's net instantaneous utility;
the resource total separately constrains feasibility. Costs must not be counted
twice in the net utility. The aggregate resource field is supplied evidence, not
an instrumented measurement made by this executable. Projected/clamped utility
is rejected by this bridge profile.

The original evaluator then rejects the supplied hard violation, risk ceiling
and resource ceiling failures before Pareto comparison. Ties return the native
unresolved frontier; no candidate ID is used as a hidden tie-break. `abstain`
must have exactly zero utility, risk and cost. A negative-value optimization can
therefore lose to stopping. Choosing an existing useful baseline is represented
by a separate `stop` candidate with its actual terminal value.

The response binds the raw request SHA256, objective, snapshot, generation,
source identity, per-path native recursive receipts and native evaluation/policy
digests. Its authority is always `DENY_ALL`, and `safety_certificate` is false.

## Boundary and validation

`verified` and verification/support digests report upstream decisions. This
transport cannot authenticate them or prove code equivalence, memory safety,
resource lifetimes, ABI compatibility or deployment permission. The compiler
must independently verify candidates before evaluation and revalidate the chosen
code at its deployment boundary. A locally trusted identity manifest detects
build drift; it is not remote attestation against a compromised build host.

The supplied candidates are complete deterministic or pre-evaluated paths.
The bridge does not invent missing branches, identify unknown transition laws,
solve an unrestricted stochastic control problem or certify global optimality.
Its disclosed scope is `bounded-supplied-candidate-paths-only`.

Public Hepta's `tests/test_hia_ndu.py` exercises the actual executable. Set
`HEPTA_NDU_IDENTITY` to the builder's identity manifest, then run that test with
unittest discovery. Tests cover a two-step continuation with later refusal and
stopping, independent fixed-point recursion, infeasible high-utility candidates,
explicit abstention/ties, stale identities, duplicate events and malformed
protocol inputs. The small deterministic examples verify integration and do not
claim a measured performance advantage for NDU.

The executable also has five Rust protocol tests in `src/protocol_tests.rs`.
They call the original recursion and candidate evaluator through the typed
request parser, including later refusal cost, hard/resource/risk rejection,
abstention, unresolved frontiers and exact request/snapshot identity. Run them
using the repository runner:

```sh
just test --manifest-path "$PWD/tools/hia-ndu-bridge/Cargo.toml" \
  -p hepta-hia-ndu-bridge --profile default --release --locked
```

The dedicated `.github/workflows/hia-ndu-bridge.yml` job embeds the actual source
and compiler identity, runs those tests, builds the executable and sends a real
stdin request. It retains test logs and source/binary/response evidence. This
scoped job supplements the existing repository CI; it does not replace the
blocking workspace, Bazel, platform or dependency gates, nor treat their failures
as successful bridge qualification.
