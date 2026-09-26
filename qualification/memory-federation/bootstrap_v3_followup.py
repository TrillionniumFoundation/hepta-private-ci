#!/usr/bin/env python3
"""Apply required-CI follow-up edits after the V3 integration bootstrap."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rewrite(relative: str, transform) -> None:
    target = ROOT / relative
    source = target.read_text(encoding="utf-8")
    result = transform(source)
    if result != source:
        target.write_text(result, encoding="utf-8")


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
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit("blocking-ci federation job anchor is missing or ambiguous")
    return source.replace(old, new, 1)


def patch_qualification(source: str) -> str:
    # Pull requests enter through blocking-ci so qualification participates in
    # the single protected CI fan-in instead of running as an optional duplicate.
    start = source.find("  pull_request:\n")
    if start < 0:
        return source
    end = source.find("  workflow_dispatch:\n", start)
    if end < 0:
        raise SystemExit("qualification pull-request block has no dispatch boundary")
    return source[:start] + source[end:]


def main() -> None:
    rewrite(".github/workflows/blocking-ci.yml", patch_blocking)
    rewrite(
        ".github/workflows/memory-federation-v3-qualification.yml",
        patch_qualification,
    )


if __name__ == "__main__":
    main()
