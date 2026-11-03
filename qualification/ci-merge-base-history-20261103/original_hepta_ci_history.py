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


def prepare(repository, commits, *, full_history=False):
    commits = list(dict.fromkeys(commits))
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="append", required=True)
    parser.add_argument("--full-history", action="store_true")
    args = parser.parse_args()
    prepare(Path.cwd(), args.commit, full_history=args.full_history)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        # A failed fetch must stop the lane; it must never become an empty diff.
        raise SystemExit(
            f"exact comparison history fetch failed (exit {error.returncode})"
        ) from error
