"""Pinned codec incident: selected local workflow entrypoint, not a hosted job."""

import argparse
import json
from pathlib import Path
import shlex
import sys
import time

from attempt_ledger import accounting, ledger
from bounded_process import digest, save
from process_meter_v2 import run
from ruff_executor import inventory, semantic_pass
from runtime_profile import load_runtime
from task_contract_v2 import (
    CODEC_SHA256,
    HERE,
    codec_contract,
    export_inputs,
    materialize,
    replacements,
    source_bytes,
)


def selection(spec, original, proposed):
    marker = ("        run: " + spec["original_command"]).encode()
    before, found, after = original.partition(marker)
    if not found or original.count(marker) != 1:
        raise ValueError("original workflow entrypoint is not unique")
    prefix = before + b"        run: "
    if not proposed.startswith(prefix) or not proposed.endswith(after):
        raise ValueError("workflow changes outside selected test entrypoint")
    command = proposed[len(prefix) : len(proposed) - len(after)].decode()
    if command not in (spec["original_command"], spec["runner_command"]):
        raise ValueError("workflow entrypoint outside immutable task intent")
    return shlex.split(command)


def evaluate(
    fixture,
    candidate,
    output,
    python,
    ffmpeg,
    ffprobe,
    openssl,
    *,
    runtime_profile=None,
    runtime_profile_sha256=None,
    accounting_file=None,
):
    started_wall, started_cpu = time.monotonic(), time.process_time()
    fixture, candidate, output = (
        Path(p).absolute() for p in (fixture, candidate, output)
    )
    if output.resolve().is_relative_to(
        fixture.resolve()
    ) or fixture.resolve().is_relative_to(output.resolve()):
        raise ValueError("output overlaps original fixture")
    output.mkdir(exist_ok=False)
    save(
        output / "submitted-request.json",
        {
            "fixture": str(fixture),
            "candidate": str(candidate),
            "runtime_profile": str(runtime_profile) if runtime_profile else None,
            "runtime_profile_sha256": runtime_profile_sha256,
            "accounting_file": str(accounting_file) if accounting_file else None,
        },
    )
    result = {
        "schema": "hepta.memory-cell.codec-evaluation.v2",
        "accepted": False,
        "status": "rejected",
        "scope": "selected local entrypoint and static selection; not full GitHub workflow",
        "profiles": {},
        "processes": [],
    }
    expected, tool_links, tools = {}, {}, {}
    runtime, external, read_count, raw_count = {}, accounting(None), 0, 0
    try:
        if sys.platform != "linux":
            raise ValueError("Linux-only codec profile")
        spec = codec_contract()
        runtime = load_runtime(
            spec, CODEC_SHA256, runtime_profile, runtime_profile_sha256
        )
        result["runtime"] = runtime
        external = accounting(accounting_file)
        expected[HERE] = inventory(HERE)
        save(
            output / "request.json",
            {
                "fixture": str(fixture),
                "candidate": str(candidate),
                "contract_sha256": CODEC_SHA256,
                "runtime": runtime,
                "source_code": expected[HERE],
            },
        )
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("candidate must be regular file")
        with candidate.open("rb") as stream:
            raw = stream.read(spec["limits"]["candidate_bytes"] + 1)
        (output / "candidate.raw").write_bytes(raw)
        raw_count = len(raw)
        changed = replacements(raw, spec)
        source = source_bytes(spec, fixture)
        read_count = sum(map(len, source.values()))
        expected[fixture] = spec["files"]
        tools = {
            name: str(Path(path).resolve())
            for name, path in {
                "python": python,
                "ffmpeg": ffmpeg,
                "ffprobe": ffprobe,
                "openssl": openssl,
            }.items()
        }
        if any(digest(tools[name]) != pin for name, pin in runtime["tools"].items()):
            raise ValueError("runtime executable pin mismatch")
        files = source | changed
        argv = selection(spec, source[spec["workflow"]], files[spec["workflow"]])
        if argv == shlex.split(spec["runner_command"]) and spec["runner"] not in files:
            raise ValueError("selected candidate runner is missing")
        manifest = json.loads(files[spec["module_directory"] + "/MANIFEST.json"])
        if any(
            manifest.get(field) is not False for field in spec["no_promotion_fields"]
        ):
            raise ValueError("no-promotion source manifest changed")
        for profile, available in spec["profiles"].items():
            root = output / profile
            root.mkdir()
            workspace = root / "workspace"
            materialize(workspace, files)
            expected[workspace] = inventory(workspace)
            toolbox, temporary = root / "tools", root / "temporary"
            toolbox.mkdir()
            temporary.mkdir()
            for name in available:
                link = toolbox / name
                link.symlink_to(tools[name])
                tool_links[link] = tools[name]
            environment = {
                "PATH": str(toolbox),
                "LANG": "C.UTF-8",
                "TMPDIR": str(temporary),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONHASHSEED": "0",
            }
            observer_request = root / "observer-request.json"
            save(
                observer_request,
                {
                    "workspace": str(workspace),
                    "module_directory": spec["module_directory"],
                    "selection": argv,
                    "evidence": str(root / "observed"),
                    "nested_output_bytes": spec["limits"]["nested_output_bytes"],
                },
            )
            process = run(
                [
                    tools["python"],
                    "-I",
                    "-B",
                    str(HERE / "candidate_observer_v2.py"),
                    str(observer_request),
                ],
                workspace,
                root / "execution",
                spec["limits"],
                environment,
            )
            result["processes"].append(process)
            receipt = root / "observed/semantic.json"
            report = json.loads(receipt.read_bytes()) if receipt.is_file() else None
            clean = not any(
                process.get(key) for key in ("error", "cleanup_error", "reap_error")
            )
            full = (
                bool(report)
                and clean
                and process["returncode"] == 0
                and not process["timeout"]
                and semantic_pass(report, spec["test_ids"])
            )
            refusal = (
                bool(report)
                and clean
                and process["returncode"] not in (None, 0)
                and not process["timeout"]
                and process["returncode"] > 0
            )
            result["profiles"][profile] = {
                "passed": full if profile == "provisioned" else refusal,
                "semantic_full_pass": full,
                "missing_tool_refused": refusal if profile != "provisioned" else None,
                "semantic": report,
            }
        result["accepted"] = all(row["passed"] for row in result["profiles"].values())
        result["status"] = "passed" if result["accepted"] else "task_failed"
    except Exception as error:
        result.update(
            accepted=False, status="rejected", error=f"{type(error).__name__}: {error}"
        )
    finally:
        observed = {}
        for path, pinned in expected.items():
            try:
                observed[str(path)] = inventory(path)
                if observed[str(path)] != pinned:
                    raise ValueError("source inventory drift")
            except Exception as error:
                result.update(
                    accepted=False, status="inventory_failed", error=f"{path}: {error}"
                )
        for link, target in tool_links.items():
            if not link.is_symlink() or str(link.resolve()) != target:
                result.update(
                    accepted=False,
                    status="inventory_failed",
                    error="tool path binding drift",
                )
        for name, path in tools.items():
            try:
                if digest(path) != runtime["tools"][name]:
                    raise ValueError("executable bytes changed during attempt")
            except Exception as error:
                result.update(
                    accepted=False, status="inventory_failed", error=str(error)
                )
        save(output / "observed-inventories.json", observed)
        result["cost_ledger"] = ledger(
            result["processes"],
            output,
            read_count,
            raw_count,
            runtime,
            external,
            started_wall,
            started_cpu,
        )
        save(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    inputs = commands.add_parser("inputs")
    execute = commands.add_parser("evaluate")
    for command in (inputs, execute):
        command.add_argument("--fixture", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--runtime-profile")
        command.add_argument("--runtime-profile-sha256")
    for name in ("candidate", "python", "ffmpeg", "ffprobe", "openssl"):
        execute.add_argument(f"--{name}", required=True)
    execute.add_argument("--accounting", dest="accounting_file")
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "describe":
        print(json.dumps(codec_contract(), indent=2, sort_keys=True))
        return 0
    if command == "inputs":
        print(json.dumps(export_inputs(**args), indent=2))
        return 0
    result = evaluate(**args)
    print(json.dumps({key: result[key] for key in ("accepted", "status")}))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
