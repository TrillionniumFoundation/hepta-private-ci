# Protected host authority contracts

These are the original Hepta authority contracts imported from the clean local
candidate recorded in `ROOT_CONTRACTS_SOURCE.json`. The import creates no signer,
production policy, current-cut witness, service installation or authority grant.
All new implementation files remain private modules behind explicit crate exports.

## Ownership and wire

`authority_host_peer` and `authority_host_channel` bind an already connected
Linux Unix stream to the expected peer UID, PID and pre-held pidfd. Lifetime
failure closes that capability; no discovery, reconnect or same-path replacement
restores it. Frame I/O is bounded. `authority_consumer_wire` and
`authority_root_frontier` carry the original FinalUse frontier operations.

`authority_host_store` owns root-protected, durably synchronized authority state.
`authority_host_clock` derives live time and expiry from the protected host's
boot-time and retained epoch/ceiling. An unavailable clock is not replaced by
process wall-clock time. Its bounded cached observation does not itself create
writer authority. Production construction requires the independently protected
source and exact expected owner, scope, epoch and lifetime.

`authority_host_issuer` and its transport bind signing to the original typed
request and current original state. There is no arbitrary-message signing API.
Private signing material remains inside the original authority owner. It must
never be copied into the desktop, Session, renderer, or ordinary Agentd client.

`authority_lease` rechecks the protected clock after acquiring the original
consumer lock, including final entry. This closes the expiry-while-waiting gap.
The pair-boundary module applies original consumer frontier retirement without
inventing a second grant ledger or allowing a stale owner to resume.

## Development and checks

The source inventory records exact imported file hashes. This mechanically
imported closure is intentionally kept coherent; deleting its peer lifetime,
protected clock, or durable frontier parts is not a supported reduced profile.

Run the ordinary owning tests with `just test -p codex-hepta-contracts --lib`.
After tests, use scoped `just fix -p codex-hepta-contracts`, then `just fmt`.
Rustix event/time feature changes also require the repository Bazel lock refresh.
Ordinary tests use explicit fixtures and cannot establish real root ownership.
Privileged process-isolation qualifications are separate ignored tests and must
use fresh isolated state, real UID separation and the original binary. Their
results must never be reported as admission of a production policy.

The target is Linux. Native Asterinas must independently implement and qualify
SO_PEERCRED, pidfd lifetime and CLOCK_BOOTTIME semantics before using this path;
a host proxy or constant clock is not equivalent native authority.

## This stage's qualification

The ordinary owning suite passed 227 tests with 10 ignored helper/privileged
entries. A separately selected original Root process-isolation test also passed
against real UID 0 and UID 60001 processes. It used a fresh private bind-mounted
state directory on ext4, the unchanged test ELF copied with its hash verified
into a root-owned executable directory, the actual issuer protocol and original
nonce-replay refusal. All temporary state and executable copies were removed.
This validates that selected isolation boundary; it is not the five-lane service
qualification or a deployed production policy.
