#!/usr/bin/env python3
"""Exercise the real Bazel downloader and pinned zlib extraction, never a build substitute."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PACKAGE = "zlib1g_1.3.dfsg-3.1ubuntu2.1_amd64.deb"
# rules_rs v0.0.96 rs/private/rustc_repository.bzl, x86_64 _LINUX_ZLIB.
SHA256 = "7074b6a2f6367a10d280c00a1cb02e74277709180bab4f2491a2f355ab2d6c20"
ORIGIN = "https://snapshot.ubuntu.com/ubuntu/20260801T000000Z/pool/main/z/zlib/" + PACKAGE
REPOSITORY_RULE = '''def _impl(ctx):
    result = ctx.download_and_extract(
        url = ctx.attr.url,
        sha256 = ctx.attr.sha256,
        output = "deb",
        type = ".deb",
    )
    if not ctx.path("deb/data.tar.zst").exists:
        fail("missing pinned zlib data archive")
    ctx.extract("deb/data.tar.zst", output = "lib", stripPrefix = "usr/lib/x86_64-linux-gnu")
    ctx.file("receipt.json", json.encode({"sha256": result.sha256, "url": ctx.attr.url}))
    ctx.file("BUILD.bazel", 'exports_files(["receipt.json"])\\nfilegroup(name="payload", srcs=glob(["lib/**"], allow_empty=False), visibility=["//visibility:public"])\\n')
fetch_zlib = repository_rule(implementation=_impl, attrs={"url": attr.string(mandatory=True), "sha256": attr.string(mandatory=True)})
'''


def invoke(command: list[str], cwd: Path, log: Path) -> dict:
    start = time.monotonic_ns()
    with log.open("xb") as stream:
        try:
            result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False)
            code, expired = result.returncode, False
        except subprocess.TimeoutExpired:
            code, expired = None, True
    return {"command": command, "exit_code": code, "timed_out": expired,
            "wall_ns": time.monotonic_ns() - start, "log": log.name,
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}


def execute_case(bazel: str, output: Path, config: Path, name: str, digest: str, force_mirror: bool) -> dict:
    root = output / name
    root.mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "defs.bzl").write_text(REPOSITORY_RULE)
    (workspace / "MODULE.bazel").write_text(
        'module(name="zlib_transport_probe")\nfetch_zlib = use_repo_rule("//:defs.bzl", "fetch_zlib")\n'
        f'fetch_zlib(name="pinned_zlib", url={json.dumps(ORIGIN)}, sha256={json.dumps(digest)})\n')
    (workspace / "BUILD.bazel").write_text(
        'filegroup(name="probe", srcs=["@pinned_zlib//:payload"])\n'
    )
    policy = config.read_text()
    # Blocking the original *after* rewrite forces success to use the production
    # alternate. It does not alter the committed policy or bypass TLS/SHA checks.
    if force_mirror:
        policy += "\nblock snapshot.ubuntu.com\n"
    policy_path = root / "downloader.config"
    policy_path.write_text(policy)
    base = root / "bazel-output"
    command = [bazel, "--batch", "--ignore_all_rc_files", f"--output_base={base}",
               "build", "--lockfile_mode=off", f"--repository_cache={root / 'cache'}",
               f"--repo_contents_cache={root / 'contents-cache'}",
               f"--downloader_config={policy_path}", "//:probe"]
    outcome = invoke(command, workspace, root / "bazel.log")
    outcome.update({"case": name, "original_blocked": force_mirror, "expected_sha256": digest})
    if digest == SHA256:
        receipts = list((base / "external").glob("*pinned_zlib/receipt.json"))
        if outcome["exit_code"] == 0 and len(receipts) == 1:
            receipt = json.loads(receipts[0].read_text())
            libraries = [p for p in (receipts[0].parent / "lib").glob("libz.so*") if p.is_file()]
            outcome["receipt"] = receipt
            outcome["libraries"] = [
                {
                    "name": p.name,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in libraries
            ]
            outcome["passed"] = receipt == {"sha256": SHA256, "url": ORIGIN} and bool(libraries)
        else:
            outcome["passed"] = False
    else:
        log = (root / "bazel.log").read_text(errors="replace")
        # A network/analysis failure is not proof that the checksum fence worked.
        outcome["passed"] = (outcome["exit_code"] not in (None, 0)
                             and re.search(r"(?i)checksum.*(?:was|mismatch|does not match)", log) is not None
                             and digest in log)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bazel", default="bazel")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    config = repository / ".bazel_downloader_config"
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = subprocess.check_output(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=repository, text=True).splitlines()
    report = {"schema": "hepta-exact-zlib-downloader-probe-v1", "source": source,
              "production_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
              "expected_package_sha256": SHA256, "cases": [], "passed": False,
              "scope": "real downloader/extraction only; no SDK, full repository, PoN, model or release acceptance"}
    try:
        for name, digest, forced in [("forced-mirror", SHA256, True), ("production-policy", SHA256, False),
                                    ("wrong-checksum", "0" * 64, True)]:
            row = execute_case(args.bazel, output, config, name, digest, forced)
            report["cases"].append(row)
        report["passed"] = all(row["passed"] for row in report["cases"])
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
