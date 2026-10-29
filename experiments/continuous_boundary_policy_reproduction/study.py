"""Separate same-seed reproduction CLI; every output is immutable and new."""

import argparse
import json
from pathlib import Path

from .identity import initialize
from .phases import confirm, train
from .sources import freeze_source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "initialize", "train", "confirm"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-binary", type=Path)
    parser.add_argument("--score-binary", type=Path)
    parser.add_argument("--publication-commit")
    args = parser.parse_args()
    if args.phase == "freeze":
        print(json.dumps(freeze_source()))
        return
    if args.output is None or args.native_binary is None or args.score_binary is None:
        parser.error(
            "Every run phase requires a fresh output identity and both binaries"
        )
    binaries = {"native": args.native_binary, "score": args.score_binary}
    if args.phase == "initialize":
        result = initialize(args.output, binaries, args.publication_commit)
        print(json.dumps(result))
    elif args.phase == "train":
        train(args.output, binaries)
    else:
        confirm(args.output, binaries, args.publication_commit)


if __name__ == "__main__":
    main()
