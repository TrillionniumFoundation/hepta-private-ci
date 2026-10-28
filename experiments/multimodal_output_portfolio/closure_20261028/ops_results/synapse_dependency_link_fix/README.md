# Bounded dependency link custody

The arm64 Cargo fetch completed successfully. The following evidence step failed
because a locked Nucleo checkout contains `matcher/LICENSE -> ../LICENSE` and the
generic evidence inventory rejects every symbolic link. Exact native logs and
archive/member verification are retained in `../synapse_arm64_792_prefetch/`.

The new seed v2 ledger describes regular files and each exact relative file link.
Every link component stays inside the seed; intermediate components must be real
directories. Directory links, escaping paths, loops, dangling links, special files
and credentials/config/bin entries fail closed. Link targets retain their exact
spelling, resolved file identity and mode. The producer, host orchestrator and
offline builder explicitly require the new schema.

Copying writes verified regular files first, then recreates the bounded links
without following them or applying chmod through them. Complete source and
destination inventories must still equal the frozen input ledger. The general
evidence inventory remains unchanged and continues to reject all links.

Independent review reproduced a meaningful `file/.` counterexample. The final
parser preserves path components and rejects this with the same directory rule
as the actual filesystem. The regression also preserves valid `.././LICENSE`.
The final 21 actual filesystem/process boundary tests passed; syntax/import,
spelling and scoped diff checks passed. These are implementation tests. Native
arm64 cold build and Synapse qualification remain pending a new execution.
