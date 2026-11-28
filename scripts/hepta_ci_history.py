#!/usr/bin/env python3
"""Fetch exact comparison inputs without every historical branch and tag."""

import argparse
import base64
import os
from pathlib import Path
import re
import subprocess


def git(repository, *arguments, environment=None):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *arguments],
        cwd=repository,
        env=environment,
        stderr=subprocess.PIPE,
        text=True,
    ).strip()


def fetch_environment(repository):
    environment = os.environ.copy()
    # Auth exists only in the fetch process, never in argv or repository config.
    for key in tuple(environment):
        if key.startswith("GIT_TRACE") or key == "GIT_CURL_VERBOSE":
            del environment[key]
    token = environment.get("GH_TOKEN")
    if token:
        origin = git(repository, "remote", "get-url", "origin")
        expected = (
            environment.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
            + "/"
            + environment.get("GITHUB_REPOSITORY", "")
        )
        if origin.removesuffix(".git") != expected or not origin.startswith("https://"):
            raise ValueError("CI token requires the exact HTTPS event repository")
        count = int(environment.get("GIT_CONFIG_COUNT", "0"))
        authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        environment[f"GIT_CONFIG_KEY_{count}"] = f"http.{origin}/.extraheader"
        environment[f"GIT_CONFIG_VALUE_{count}"] = (
            f"AUTHORIZATION: basic {authorization}"
        )
        environment["GIT_CONFIG_COUNT"] = str(count + 1)
    return environment


def snapshot_lacks_objects(repository, commit):
    objects = git(
        repository,
        "rev-list",
        "--objects",
        "--no-object-names",
        "--missing=print",
        "--max-count=1",
        commit,
    )
    return any(line.startswith("?") for line in objects.splitlines())


def prepare(repository, commits, *, full_history=False, with_blobs=False):
    commits = list(dict.fromkeys(commits))
    if not commits or any(
        re.fullmatch(r"[0-9a-f]{40}", commit) is None for commit in commits
    ):
        raise ValueError("comparison inputs must be exact SHA-1 commits")
    refetch = False
    if full_history:
        selected = commits
        if with_blobs:
            refetch = "true" == git(
                repository,
                "config",
                "--type=bool",
                "--default=false",
                "--get",
                "remote.origin.promisor",
            )
    else:
        selected = []
        for commit in commits:
            try:
                git(repository, "cat-file", "-e", f"{commit}^{{commit}}")
            except subprocess.CalledProcessError:
                selected.append(commit)
                continue
            if with_blobs and snapshot_lacks_objects(repository, commit):
                selected.append(commit)
                refetch = True
    if selected:
        arguments = ["fetch", "--no-tags", "--no-recurse-submodules"]
        arguments.append("--no-filter" if with_blobs else "--filter=blob:none")
        if refetch:
            # With an advertised commit already present, normal negotiation can
            # incorrectly rely on blobs deliberately omitted by a prior fetch.
            arguments.append("--refetch")
        if full_history:
            if git(repository, "rev-parse", "--is-shallow-repository") == "true":
                arguments.append("--unshallow")
        else:
            arguments.append("--depth=1")
        git(
            repository,
            *arguments,
            "origin",
            *selected,
            environment=fetch_environment(repository),
        )
    for commit in commits:
        if git(repository, "cat-file", "-t", commit) != "commit":
            raise ValueError("comparison input is not a commit object")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="append", required=True)
    parser.add_argument("--full-history", action="store_true")
    parser.add_argument(
        "--with-blobs",
        action="store_true",
        help="include file content in comparisons or local merges",
    )
    args = parser.parse_args()
    prepare(
        Path.cwd(),
        args.commit,
        full_history=args.full_history,
        with_blobs=args.with_blobs,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # A failed fetch must stop the lane; it must never become an empty diff.
        raise SystemExit(
            f"exact comparison history fetch failed (exit {error.returncode})"
        ) from error
