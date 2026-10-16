"""Fail-closed two-process HDCF feature training and blind review CLI.

This is a research tool, NOT a sandbox or a FinalUse endpoint. Use independent
OS processes and file permissions to segregate held-target inputs from train.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
from physical_bank import MAX_INPUT_BYTES, Denied, _dump, score, train


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Denied("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise Denied("invalid nonfinite JSON " + value)


def read_document(filename: str):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(filename, flags)
    with os.fdopen(fd, "rb") as src:
        if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
            raise Denied("input not a regular file")
        data = src.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise Denied("oversized input file")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise Denied("invalid JSON input") from exc


def write_once(filename: str, obj):
    data = _dump(obj) + b"\n"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(filename, flags, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    # A diagnostic file is deliberately not a production durable transaction.
    # Independent external custody/anti-rollback/signatures remain absent.


def main(argv=None):
    parser = argparse.ArgumentParser(description="HDCF research-only CPU Cell-bank trial")
    sub = parser.add_subparsers(dest="mode", required=True)
    fit = sub.add_parser("train", help="Only fit-labeled and held-unlabeled features")
    fit.add_argument("--features", required=True)
    fit.add_argument("--out", required=True)
    fit.add_argument("--steps", type=int, default=256)
    fit.add_argument("--seed", type=int, default=7347)
    review = sub.add_parser("review", help="Join terminal predictions to blind targets")
    review.add_argument("--predictions", required=True)
    review.add_argument("--targets", required=True)
    review.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "train":
            body = train(read_document(args.features), steps=args.steps, seed=args.seed)
        else:
            body = score(read_document(args.predictions), read_document(args.targets))
        write_once(args.out, body)
    except (Denied, OSError) as exc:
        parser.exit(2, f"DENY_ALL: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
