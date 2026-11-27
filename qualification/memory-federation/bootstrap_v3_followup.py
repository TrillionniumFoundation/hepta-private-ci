#!/usr/bin/env python3
"""Apply required-CI and cross-host follow-up edits after V3 bootstrap."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rewrite(relative: str, transform) -> None:
    target = ROOT / relative
    source = target.read_text(encoding="utf-8")
    result = transform(source)
    if result != source:
        target.write_text(result, encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label}: replacement anchor is missing or ambiguous")
    return source.replace(old, new, 1)


def patch_blocking(source: str) -> str:
    old = (
        "  memory-federation:\n"
        "    name: Memory federation qualification\n"
        "    needs: scope\n"
        "    if: needs.scope.outputs.native == 'true' || needs.scope.outputs.full_repo == 'true'\n"
        "    uses: ./.github/workflows/memory-federation-v3-qualification.yml\n"
        "    secrets: inherit\n"
    )
    expression = "$" + "{{ github.base_ref || 'main' }}"
    new = (
        "  memory-federation:\n"
        "    name: Memory federation qualification\n"
        "    needs: scope\n"
        "    if: needs.scope.outputs.native == 'true' || needs.scope.outputs.full_repo == 'true'\n"
        "    uses: ./.github/workflows/memory-federation-v3-qualification.yml\n"
        "    with:\n"
        "      run_merge_candidate: true\n"
        f"      base_ref: {expression}\n"
        "    secrets: inherit\n"
    )
    return replace_once(source, old, new, "blocking-ci federation job")


def patch_qualification(source: str) -> str:
    # Pull requests enter through blocking-ci so qualification participates in
    # the single protected CI fan-in instead of running as an optional duplicate.
    start = source.find("  pull_request:\n")
    if start >= 0:
        end = source.find("  workflow_dispatch:\n", start)
        if end < 0:
            raise SystemExit("qualification pull-request block has no dispatch boundary")
        source = source[:start] + source[end:]
    old = (
        "        lane: ${{ fromJSON((github.event_name == 'pull_request' || "
        "(github.event_name == 'workflow_dispatch' && inputs.run_merge_candidate)) && "
        "'[\"source-head\",\"base-merge\"]' || '[\"source-head\"]') }}"
    )
    new = (
        "        lane: ${{ fromJSON(inputs.run_merge_candidate && "
        "'[\"source-head\",\"base-merge\"]' || '[\"source-head\"]') }}"
    )
    return replace_once(source, old, new, "qualification matrix")


def patch_protocol(source: str) -> str:
    source = replace_once(
        source,
        "        if self.generation < previous.generation || self.frontier < previous.frontier {\n"
        "            return Err(FederationProtocolError::FrontierRollback);\n"
        "        }",
        "        if self.generation < previous.generation\n"
        "            || self.frontier < previous.frontier\n"
        "            || (self.generation == previous.generation\n"
        "                && self.frontier == previous.frontier)\n"
        "        {\n"
        "            return Err(FederationProtocolError::FrontierRollback);\n"
        "        }",
        "frontier strict progress",
    )
    source = replace_once(
        source,
        "        self.nonce.validate()?;\n        self.message.validate()",
        "        self.nonce.validate()?;\n"
        "        if let FederationWireMessageV1::Response(response) = &self.message {\n"
        "            if response.frontier.owner_peer_id != self.sender_peer_id {\n"
        "                return Err(FederationProtocolError::FrontierOwnerMismatch);\n"
        "            }\n"
        "        }\n"
        "        self.message.validate()",
        "response frontier sender binding",
    )
    return source


def patch_technical(source: str) -> str:
    source = replace_once(
        source,
        "Declared exclusive target roots:\n\n"
        "- `codex-rs/hepta-memory-federation`\n\n"
        "Existing declared roots at this exact source snapshot:\n\n"
        "- `codex-rs/hepta-memory-federation`",
        "Declared exclusive target roots:\n\n"
        "- `codex-rs/hepta-memory-federation`\n"
        "- `codex-rs/hepta-memory-federation-wire`\n\n"
        "Existing declared roots at this exact source snapshot:\n\n"
        "- `codex-rs/hepta-memory-federation`\n"
        "- `codex-rs/hepta-memory-federation-wire`",
        "technical source roots",
    )
    source = replace_once(
        source,
        "No component in this module enrolls peers, mutates a remote store, owns credentials, "
        "issues grants, writes cognitive facts or maintains a retry queue. Current owner/capability "
        "facts stay in their existing owners.",
        "The in-process V2 engine and product adapter do not enroll peers, mutate a remote store, "
        "own credentials, issue grants, write cognitive facts or maintain a retry queue. The separate "
        "wire candidate defines a bounded directional credential registry contract, but it is not a "
        "selected product credential store and does not move current owner/capability facts from their owners.",
        "technical credential boundary",
    )
    source = replace_once(
        source,
        "Registered cross-host wire protocol schemas:\n\n"
        "None.\n\n"
        "The V2 Rust structs are an in-process checked-adapter contract, not a registered remote wire format. "
        "A future cross-process or multi-host transport must register an authenticated versioned schema and "
        "peer-identity/credential binding before these semantics may be carried across a host boundary. It may "
        "not serialize the Rust structs by convention and treat transport integrity as remote identity authentication.",
        "Registered cross-host wire protocol schemas:\n\n"
        "- `hepta-memory-federation-authenticated-frame-v1` at platform wire V2, implemented by "
        "`codex-hepta-memory-federation-wire`.\n\n"
        "The V2 Rust structs remain an in-process checked-adapter contract and are never serialized by convention. "
        "The registered frame schema is a transport-neutral authenticated candidate with directional peer credentials, "
        "canonical encoding, MAC, nonce/replay protection, frontier witnesses and cancellation acknowledgements. It is "
        "not connected to the current product adapter and does not establish mutually authenticated network transport, "
        "operator acceptance, activation or release.",
        "technical registered wire schema",
    )
    source = replace_once(
        source,
        "`memory.federation` owns no database, migration, remote fact, enrollment registry, credential store or durable retry state.",
        "The current product path owns no database, migration, remote fact, durable enrollment registry, selected-host "
        "credential store or durable retry state. The wire crate's in-memory bounded registries are protocol reference "
        "components, not activated durable product state.",
        "technical persistence boundary",
    )
    source = replace_once(
        source,
        "- [V2_HARDENING.md](V2_HARDENING.md).",
        "- [V2_HARDENING.md](V2_HARDENING.md).\n"
        "- [WIRE_V1.md](WIRE_V1.md).\n"
        "- [codex-rs/hepta-memory-federation-wire/src/lib.rs](../../../codex-rs/hepta-memory-federation-wire/src/lib.rs).",
        "technical operating references",
    )
    return source


def patch_dossier(source: str) -> str:
    source = replace_once(
        source,
        "Roots: `codex-rs/hepta-memory-federation`.\nPackages: `MEM-3-FEDERATION`.",
        "Roots: `codex-rs/hepta-memory-federation`, `codex-rs/hepta-memory-federation-wire`.\n"
        "Packages: `MEM-3-FEDERATION`.",
        "dossier source roots",
    )
    source = replace_once(
        source,
        "The canonical contract implementation remains owned by `codex-rs/hepta-memory-federation`. Product composition uses",
        "The canonical one-peer contract remains owned by `codex-rs/hepta-memory-federation`; the registered authenticated "
        "wire candidate is owned by `codex-rs/hepta-memory-federation-wire`. Product composition uses",
        "dossier ownership",
    )
    return source


def main() -> None:
    rewrite(".github/workflows/blocking-ci.yml", patch_blocking)
    rewrite(
        ".github/workflows/memory-federation-v3-qualification.yml",
        patch_qualification,
    )
    rewrite(
        "codex-rs/hepta-memory-federation-wire/src/protocol.rs",
        patch_protocol,
    )
    rewrite("docs/modules/memory.federation/TECHNICAL.md", patch_technical)
    rewrite(
        "qualification/module-execution-dossiers/detail/memory.federation.md",
        patch_dossier,
    )


if __name__ == "__main__":
    main()
