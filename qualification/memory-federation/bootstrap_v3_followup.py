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


if __name__ == "__main__":
    main()
