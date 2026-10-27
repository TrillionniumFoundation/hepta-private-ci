# Original Root session and registered writer File

The registered owner has one private `Arc<File>` for its original writer lock.
The authenticated Root session must retain that exact allocation while it can
still authorize the original process. Config destruction alone cannot retire a
publicly retained `AgentdRootProductionAttachment::root_session`.

## Implementation and retirement

`AgentdConfig::retain_root_session` delegates to the session's private binding.
The original signed agent and spawn generation must match, and a second binding
must point to the same allocation. It opens no file and returns no authority.
The ordinary joint/Notes composition and both original handoff loaders call it
after acquiring the original File and before postload refusal can destroy Config.
All original process, Registry, proof and authority checks remain mandatory.

The private session custody is a shared once-initialized slot containing that
same File. Only the session, its complete original observation-worker future,
and its actual consumer synchronization jobs hold the slot. The worker wrapper
drops its full future before its custody field. A queued synchronization job
owns the original consumers before its final custody field; running work keeps
custody until its original CAS and checks return, including cancellation,
timeout and error paths. Aborting an async await does not cancel blocking CAS.

Session Drop still fences the original cache, requests worker cancellation and
clears the original consumer cycle. Read-only clock/verifier clones retain only
the fenced LiveRoot. They cannot retain the registered File after the actual
session and work have retired. Existing live host/writer handles independently
retain that same File through the original verifier wrapper.

The Root preparation `strong_count != 1` refusal is unchanged. A fresh Config
has no bound session. A bound operational session is an additional real holder
and cannot be made eligible by changing a threshold or explicitly unlocking it.
No identity, Registry, signer, Root, clock, grant or ledger is duplicated.

## Development and qualification

Use `just fmt`, scoped `just fix -p codex-hepta-agentd`, and `just test`; do not
invoke `cargo test`. Focused cases cover retained public session composition,
original blocking CAS retirement, postload birth refusal, the existing owner
and writer locks, and original consumer/journal retirement. Keep retries at zero.
The postload test executes the consuming original tail, not Root0600 descriptor
admission, credential drop or the front half of the Root handoff.

Ordinary fixtures use controlled same-UID peers and synthetic signing keys.
They prove registered-lock lifetime and refusal ordering, not a deployed Root,
human authorization, model run, physical Current material or duplicate DB write.
The registered File, SQLite writer fence and two FinalUse journal locks are
distinct. Report each observed lock separately.

The ignored actual-Root preparation cases must also be run under real UID/EUID0
with an explicit private test root, preserving the retained-uninstalled-writer
refusal and fresh handoff availability. Earlier source/ELF results cannot be
transferred to a new source combination. Native ELF file/LOAD gates remain
8 MiB/16 MiB and require a separate original default-release build and guest run.
