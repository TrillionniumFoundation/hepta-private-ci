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


def prepare(repository, commits, *, full_history=False, merge_base=False):
    comparison = list(commits)
    if merge_base and (full_history or len(comparison) != 2):
        raise ValueError(
            "merge-base mode requires exactly two tips and no full-history mode"
        )
    commits = list(dict.fromkeys(comparison))
    if not commits or any(
        re.fullmatch(r"[0-9a-f]{40}", commit) is None for commit in commits
    ):
        raise ValueError("comparison inputs must be exact SHA-1 commits")
    if full_history:
        selected = commits
    else:
        selected = []
        for commit in commits:
            try:
                git(repository, "cat-file", "-e", f"{commit}^{{commit}}")
            except subprocess.CalledProcessError:
                selected.append(commit)
    if selected:
        arguments = ["fetch", "--no-tags", "--filter=blob:none"]
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
    if merge_base:
        deepen = 1
        while True:
            try:
                bases = git(repository, "merge-base", "--all", *comparison).splitlines()
            except subprocess.CalledProcessError as error:
                if error.returncode != 1:
                    raise
                bases = []
            shallow_path = Path(git(repository, "rev-parse", "--git-path", "shallow"))
            if not shallow_path.is_absolute():
                shallow_path = repository / shallow_path
            shallow = (
                set(shallow_path.read_text().splitlines())
                if shallow_path.exists()
                else set()
            )
            # Finding any merge base is insufficient: a short merge-parent path
            # can expose an older common ancestor while a better one remains
            # hidden beyond a shallow first-parent boundary. Only boundaries
            # behind the known common ancestors can no longer affect three-dot
            # semantics. Ignore shallow refs unrelated to these two exact tips.
            remaining = (
                set(git(repository, "rev-list", *commits, "--not", *bases).splitlines())
                & shallow
            )
            if not remaining:
                if not bases:
                    raise ValueError("exact comparison tips have no common ancestor")
                return
            git(
                repository,
                "fetch",
                "--no-tags",
                "--filter=blob:none",
                f"--deepen={deepen}",
                "origin",
                *commits,
                environment=fetch_environment(repository),
            )
            deepen *= 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="append", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full-history", action="store_true")
    mode.add_argument("--merge-base", action="store_true")
    args = parser.parse_args()
    prepare(
        Path.cwd(),
        args.commit,
        full_history=args.full_history,
        merge_base=args.merge_base,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # A failed fetch must stop the lane; it must never become an empty diff.
        raise SystemExit(
            f"exact comparison history fetch failed (exit {error.returncode})"
        ) from error
