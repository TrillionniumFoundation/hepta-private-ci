#!/usr/bin/env python3
"""Run the existing UI suite with its exact Clippy source and a fresh driver.

Dylint 5.0.0 internally clones Clippy's removed upstream `master` ref. A
job-private compatibility alias binds that name to the revision already pinned
by this lint package. This does not create or claim an upstream master branch.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


CLIPPY_URL = "https://github.com/rust-lang/rust-clippy"


@dataclass(frozen=True)
class ClippyPin:
    commit: str
    tree: str
    first_parent: str
    parent_tree: str
    nightly: str
    parent_nightly: str


PIN = ClippyPin(
    commit="20ce69b9a63bcd2756cd906fe0964d1e901e042a",
    tree="b97d187adcea64eac274d298faf8086dbec76c99",
    first_parent="4b109ed0f40c1da5b1434faeb8599e4f3a8cc173",
    parent_tree="2dc7d5a23e84c79d06b0bcdea631e46f82bedd5d",
    nightly="nightly-2025-09-18",
    parent_nightly="nightly-2025-09-04",
)


class ResolutionError(RuntimeError):
    pass


def git(mirror: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--git-dir", str(mirror), *args],
        text=True,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
    ).strip()


def verify_mirror(mirror: Path, pin: ClippyPin = PIN) -> dict:
    try:
        parents = [
            line.removeprefix("parent ")
            for line in git(mirror, "cat-file", "-p", pin.commit)
            .split("\n\n", 1)[0]
            .splitlines()
            if line.startswith("parent ")
        ]
        observed = {
            "bare": git(mirror, "rev-parse", "--is-bare-repository"),
            "head_ref": git(mirror, "symbolic-ref", "HEAD"),
            "commit": git(
                mirror, "rev-parse", "--verify", "refs/heads/master^{commit}"
            ),
            "tree": git(mirror, "rev-parse", "--verify", pin.commit + "^{tree}"),
            "first_parent": parents[0] if parents else None,
            "parent_tree": git(
                mirror, "rev-parse", "--verify", pin.first_parent + "^{tree}"
            ),
            "nightly": tomllib.loads(
                git(mirror, "show", pin.commit + ":rust-toolchain.toml")
            )["toolchain"]["channel"],
            "parent_nightly": tomllib.loads(
                git(mirror, "show", pin.first_parent + ":rust-toolchain.toml")
            )["toolchain"]["channel"],
        }
    except (subprocess.CalledProcessError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ResolutionError(
            "fixed Clippy objects, parent history or toolchain are unavailable"
        ) from error
    expected = {"bare": "true", "head_ref": "refs/heads/master", **vars(pin)}
    if observed != expected:
        raise ResolutionError(
            "Clippy compatibility mirror does not match its complete fixed source contract"
        )
    return observed


def scoped_environment(parent: dict, mirror: Path, drivers: Path) -> dict:
    child = dict(parent)
    count = int(child.get("GIT_CONFIG_COUNT", "0"))
    if count < 0:
        raise ResolutionError("invalid inherited Git configuration count")
    child[f"GIT_CONFIG_KEY_{count}"] = f"url.{mirror.as_uri()}.insteadOf"
    child[f"GIT_CONFIG_VALUE_{count}"] = CLIPPY_URL
    child["GIT_CONFIG_COUNT"] = str(count + 1)
    child["GIT_NO_REPLACE_OBJECTS"] = "1"
    child["DYLINT_DRIVER_PATH"] = str(drivers)
    return child


def verify_lint_package(lint: Path) -> None:
    manifest = tomllib.loads((lint / "Cargo.toml").read_text())
    toolchain = tomllib.loads((lint / "rust-toolchain").read_text())
    lock = tomllib.loads((lint / "Cargo.lock").read_text())
    clippy = manifest["dependencies"]["clippy_utils"]
    versions = {
        item["name"]: item["version"]
        for item in lock["package"]
        if item["name"] in ("dylint", "dylint_testing")
    }
    if (
        clippy != {"git": CLIPPY_URL, "rev": PIN.commit}
        or toolchain["toolchain"]["channel"] != PIN.nightly
        or versions != {"dylint": "5.0.0", "dylint_testing": "5.0.0"}
    ):
        raise ResolutionError(
            "lint package source or compiler changed; review its pinned resolver"
        )


def main() -> int:
    if len(sys.argv) != 1:
        raise ResolutionError("this fixed UI runner accepts no source overrides")
    lint = Path(__file__).resolve().parents[2] / "tools" / "argument-comment-lint"
    verify_lint_package(lint)
    with tempfile.TemporaryDirectory(prefix="hepta-argument-ui-") as directory:
        root = Path(directory)
        mirror = root / "clippy.git"
        drivers = root / "dylint-drivers"
        drivers.mkdir(mode=0o700)
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=master", str(mirror)],
            check=True,
        )
        # RevIter needs the first parent with the preceding nightly before it
        # emits the fixed revision. A depth-one fetch silently loses that path.
        git(mirror, "fetch", "--depth=2", "--no-tags", CLIPPY_URL, PIN.commit)
        git(mirror, "update-ref", "refs/heads/master", PIN.commit)
        provenance = verify_mirror(mirror)
        child = scoped_environment(os.environ, mirror, drivers)
        # Match Dylint's actual backend selection. This resolver requires its
        # Git CLI path; it must not silently depend on the libgit2 fallback.
        subprocess.run(["git", "--version"], env=child, check=True)
        advertised = subprocess.check_output(
            ["git", "ls-remote", CLIPPY_URL, "HEAD", "refs/heads/master"],
            env=child,
            text=True,
        )
        actual_refs = dict(line.split()[::-1] for line in advertised.splitlines())
        if actual_refs != {"HEAD": PIN.commit, "refs/heads/master": PIN.commit}:
            raise ResolutionError(
                "process-local Clippy URL did not resolve to the verified mirror"
            )
        print(
            json.dumps(
                {
                    "schema": "argument-comment-ui-clippy-source-v1",
                    **provenance,
                    "compatibility_ref_scope": "job-private-only",
                    "upstream_master_claimed": False,
                    "fresh_driver_directory": str(drivers),
                }
            ),
            flush=True,
        )
        # Preserve the original mandatory suite, diagnostics and inherited job
        # budget. This environment applies only to this one Cargo subprocess.
        result = subprocess.run(["cargo", "test"], cwd=lint, env=child, check=False)
        return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == "__main__":
    sys.exit(main())
