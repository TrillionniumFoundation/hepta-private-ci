"""Build the bounded local PERC owner/head qualification against unchanged libraries.

The supplied head is an explicit diagnostic Q24 linear model, not the trained
semantic ranking model. This does not enroll a production owner or start agentd.
"""

import argparse
from pathlib import Path

from perc1_native_cell_probe import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).with_suffix(".rs").read_text()
    print(
        build(
            args.repo,
            args.build_dir,
            args.source_ref,
            args.cargo,
            args.rustc,
            source=source,
            offline=not args.online,
        )
    )


if __name__ == "__main__":
    main()
