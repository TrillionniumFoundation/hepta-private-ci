"""Format the reviewed Rust stack admitted by the daemon maintenance lane."""

import argparse
import json
from pathlib import Path

import format as repository_format


RUST_OWNERS = (
    "codex-rs/hepta-agentd/",
    "codex-rs/hepta-learning-artifacts/",
    "codex-rs/hepta-intelligence-eval/",
    "codex-rs/hepta-contracts/",
    "codex-rs/hepta-neuron/",
    "codex-rs/hepta-learning-ledger/",
)


def is_owned_rust(path: str) -> bool:
    return path.endswith(".rs") and path.startswith(RUST_OWNERS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args(argv)

    rust_inputs = repository_format.rust_configuration_scope(
        repository_format.changed_paths(args.base)
    )
    selected = [path for path in rust_inputs if is_owned_rust(path)]
    outside = [path for path in rust_inputs if not is_owned_rust(path)]
    args.inventory.write_text(
        json.dumps(
            {
                "base": args.base,
                "owners": RUST_OWNERS,
                "selected": selected,
                "outside_maintenance_owners": outside,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Formatting {len(selected)} reviewed Rust inputs across "
        f"{len(RUST_OWNERS)} maintenance owners",
        flush=True,
    )
    commands = tuple(
        repository_format.rust_file_command(path, check=False) for path in selected
    )
    result = repository_format.run_formatter_group(
        repository_format.FormatterGroup("Rust", commands)
    )
    if result.output:
        print(result.output, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
