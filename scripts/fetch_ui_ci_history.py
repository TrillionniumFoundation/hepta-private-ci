"""Fetch the two immutable PR histories without fetching unrelated repository refs."""

import argparse
import base64
import json
import os
import re
import subprocess


def git(*args):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *args], text=True
    ).strip()


def fetch_history(base, source, repository, token):
    for name, value in (("base", base), ("source", source)):
        if re.fullmatch(r"[0-9a-f]{40}", value or "") is None:
            raise ValueError(f"{name} must be an immutable full commit SHA")
    before = {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain", "--untracked-files=normal"),
    }
    if before["head"] != source or before["status"]:
        raise ValueError("history fetch requires the clean exact source checkout")
    shallow_before = git("rev-parse", "--is-shallow-repository") == "true"
    fetch_env = os.environ.copy()
    fetch_env.pop("HEPTA_UI_CHECKOUT_TOKEN", None)
    # Auth is scoped to this one HTTPS fetch and never written into repository
    # configuration. Do not inherit optional Git tracing into an authenticated fetch.
    for key in list(fetch_env):
        if key.startswith("GIT_TRACE") or key == "GIT_CURL_VERBOSE":
            fetch_env.pop(key)
    command = ["git", "--no-replace-objects"]
    if token:
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or "") is None:
            raise ValueError("authenticated history fetch requires the repository name")
        expected = f"https://github.com/{repository}"
        if git("remote", "get-url", "origin") not in (expected, expected + ".git"):
            raise ValueError(
                "authenticated history fetch requires the exact GitHub origin"
            )
        fetch_env["HEPTA_UI_GIT_AUTH"] = (
            "AUTHORIZATION: basic "
            + base64.b64encode(f"x-access-token:{token}".encode()).decode()
        )
        command += [
            "-c",
            "http.followRedirects=false",
            "--config-env=http.https://github.com/.extraheader=HEPTA_UI_GIT_AUTH",
        ]
    command += ["fetch", "--no-tags", "--no-recurse-submodules"]
    if shallow_before:
        command.append("--unshallow")
    command += [
        "origin",
        f"+{base}:refs/hepta-ui-ci/base",
        f"+{source}:refs/hepta-ui-ci/source",
    ]
    subprocess.run(command, env=fetch_env, check=True)
    for revision in (base, source):
        if git("rev-parse", f"{revision}^{{commit}}") != revision:
            raise ValueError("fetched commit identity differs")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("the immutable PR histories remain shallow")
    after = {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain", "--untracked-files=normal"),
    }
    if after != before:
        raise ValueError("history fetch changed the source checkout")
    return {
        "schema": "hepta.ui-exact-history.v1",
        "base_sha": base,
        "source_sha": source,
        "source_tree": before["tree"],
        "shallow_before": shallow_before,
        "shallow_after": False,
        "checkout_unchanged": True,
        "requested_refs": ["refs/hepta-ui-ci/base", "refs/hepta-ui-ci/source"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("HEPTA_UI_BASE_SHA"))
    parser.add_argument("--source", default=os.environ.get("HEPTA_UI_SOURCE_SHA"))
    parser.add_argument("--repository", default=os.environ.get("HEPTA_UI_REPOSITORY"))
    args = parser.parse_args()
    token = os.environ.pop("HEPTA_UI_CHECKOUT_TOKEN", "")
    print(json.dumps(fetch_history(args.base, args.source, args.repository, token)))


if __name__ == "__main__":
    main()
