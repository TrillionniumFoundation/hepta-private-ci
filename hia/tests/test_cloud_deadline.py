"""Replay the exact cloud-save calculation and original std-duration date APIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
from cloud_deadline_cases import deadline_cases
from datetime_calendar_oracle.custody import binding, compile_original, require
from test_datetime_calendar import identity
from test_duration_units import preserve

ROOT = Path(__file__).resolve().parents[2]


def unique(pattern, text):
    matches = list(re.finditer(pattern, text, re.M | re.S))
    require(len(matches) == 1, "missing or duplicate production calculation")
    return matches[0][0]


def qualify(args, report):
    require(sys.flags.optimize == 0, "caller qualification cannot disable assertions")
    producer = identity()
    contract = json.loads((ROOT / "hia/cloud_deadline_contract.json").read_bytes())
    build = json.loads((args.build / "build.json").read_bytes())
    lock = json.loads((ROOT / "hia/toolchain.json").read_bytes())
    require(build["status"] == "built" and build["build_mode"] == "native-selfhost"
            and build["compiler_fixed_point"]
            and build["compiler_sha256"] == contract["compiler_sha256"], "native fixed point differs")
    for name, key in [("toolchain.json", "toolchain_lock_sha256"),
                      ("build.py", "build_driver_sha256"), ("cargo_build.rs", "cargo_helper_sha256")]:
        require(binding(ROOT / "hia" / name)["sha256"] == build[key], "native build input differs")
    require(build["toolchain"] == lock and set(build["modules"]) == set(lock["modules"])
            and len(lock["modules"]) == contract["production_native_modules"],
            "complete production module catalog differs")
    for name, module in build["modules"].items():
        require(binding(ROOT / f"hia/{name}.hepta")["sha256"] == module["source_sha256"],
                "production native source differs: " + name)
    archives = []
    for name in ("duration_units", "datetime_arithmetic"):
        row = build["modules"][name]
        component = json.loads((ROOT / f"hia/{name}_buffer_contract.json").read_bytes())
        require(row["source_sha256"] == component["source_sha256"]
                and row["core_sha256"] == component["core_sha256"], "qualified component source or Core differs")
        frozen = contract["qualified_components_reused"][name]
        require(row["source_sha256"] == frozen["source_sha256"] and row["core_sha256"] == frozen["core_sha256"]
                and binding(args.build / f"{name}.o")["sha256"] == frozen["object_sha256"],
                "production machine object differs from the qualified component")
        archive = binding(args.build / f"libcodex_hia_{name}.a")
        require(archive["sha256"] == row["codex_link_abi"]["archive_sha256"], "native static archive differs")
        archives.append(archive)
    report.update(producer=producer, native_build=binding(args.build / "build.json"),
                  linked_native=archives, contract=binding(ROOT / "hia/cloud_deadline_contract.json"))
    transport = binding(ROOT / contract["transport"]["path"])
    require(all(transport[key] == contract["transport"][key] for key in ("bytes", "sha256")),
            "production ABI transport differs from the source contract")
    caller_path = contract["caller"]["path"]
    original = subprocess.check_output(["git", "-C", str(args.original_repo), "show",
                                        contract["reference_commit"] + ":" + caller_path])
    current = (ROOT / caller_path).read_bytes()
    for label, raw in [("original", original), ("current", current)]:
        expected = contract["caller"][label]
        require(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"],
                label + " complete production source differs")
    test = contract["original_tests"]
    test_bytes = subprocess.check_output(["git", "-C", str(args.original_repo), "show",
                                          contract["reference_commit"] + ":" + test["path"]])
    require(test_bytes == (ROOT / test["path"]).read_bytes() and len(test_bytes) == test["bytes"]
            and hashlib.sha256(test_bytes).hexdigest() == test["sha256"], "complete original cache tests changed")
    methods, generated = [], []
    for label, raw in [("original", original), ("current", current)]:
        text = raw.decode()
        method = unique(r"^    pub\(super\) async fn save\(\n.*?^    \}\n", text)
        prefix = unique(r"^        let now = Utc::now\(\);\n.*?(?=^        let signed_payload = )", method)
        ttl = unique(r"^const CLOUD_CONFIG_BUNDLE_CACHE_TTL: Duration = [^\n]+;\n", text)
        require(prefix.count("Utc::now()") == 1, "production clock call count changed")
        methods.append({"kind": label, "method_sha256": hashlib.sha256(method.encode()).hexdigest(),
                        "prefix_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
                        "rest": method.replace(prefix, "CALCULATION\n"), "ttl": ttl})
        native = (f'#[path = {json.dumps(str(ROOT / "hia/datetime_deadline.rs"))}]\n'
                  "pub(super) mod hia_datetime_deadline;\n" if label == "current" else "")
        generated.append(f"mod {label} {{\nuse super::*;\n" + native + ttl
                         + "fn calculate() -> Result<DateTime<Utc>, CloudConfigBundleCacheError> {\n"
                         + prefix.replace("Utc::now()", "super::read_clock()")
                         + "Ok(expires_at)\n}\n"
                         + "pub fn cloud(now: DateTime<Utc>) -> (Option<DateTime<Utc>>, u64) {\n"
                         + "CLOCK.with(|clock| clock.set(Some((now, 0))));\n"
                         + "let result = calculate().ok();\n"
                         + "(result, CLOCK.with(|clock| clock.get().unwrap().1))\n}\n}\n")
    require(methods[0]["rest"] == methods[1]["rest"] and methods[0]["ttl"] == methods[1]["ttl"],
            "production save outside date calculation or original TTL changed")
    report["methods"] = [{k: v for k, v in row.items() if k not in ("rest", "ttl")} for row in methods]
    generated_path = args.output / "production_calculations.rs"
    generated_path.write_text("".join(generated))
    report["generated_source"] = binding(generated_path)
    component = json.loads((ROOT / "hia/datetime_arithmetic_buffer_contract.json").read_bytes())
    _, custody = compile_original(ROOT, args.original_lock, args.cargo, args.rustc, args.output,
                                  component, "hia/tests/datetime_arithmetic_oracle")
    report["original"] = {"receipt": binding(args.output / "original-custody.json"),
                          "toolchain": custody["toolchain"], "executable": custody["executable"]}
    messages = [json.loads(line) for line in (args.output / "build.stdout").read_bytes().splitlines()]
    chrono = [name for row in messages if row.get("reason") == "compiler-artifact"
              and row["target"]["name"] == "chrono" for name in row["filenames"] if name.endswith(".rlib")]
    require(len(chrono) == 1, "original compile has no unique Chrono library")
    chrono = Path(chrono[0]).resolve(strict=True)
    require(chrono.is_relative_to(args.output / "target"), "original library escaped its fresh target")
    cases = deadline_cases()
    raw = b"".join(struct.pack("<5Q", *row) for row in cases)
    require(len(cases) == contract["input_cases"] and hashlib.sha256(raw).hexdigest() == contract["input_sha256"],
            "complete frozen caller corpus differs")
    corpus = args.output / "inputs.bin"
    corpus.write_bytes(raw)
    report["inputs"] = preserve(args.output / "inputs.bin.gz", raw)
    executable = args.output / "cloud-deadline-callers"
    command = [str(args.rustc), "--edition=2024", "--test", "--cfg", 'feature="hia-native"',
               str(Path(__file__).with_name("cloud_deadline_callers.rs")), "--extern", "chrono=" + str(chrono),
               "-L", "dependency=" + str(chrono.parent), "-L", "native=" + str(args.build),
               "-l", "static=codex_hia_duration_units", "-l", "static=codex_hia_datetime_arithmetic",
               "-o", str(executable)]
    env = dict(os.environ, CODEX_CLOUD_DEADLINE_METHODS=str(generated_path),
               CODEX_CLOUD_DEADLINE_CASES=str(corpus), CODEX_CLOUD_DEADLINE_TRACE=str(args.output / "observations.bin"))
    report.update(linked_chrono=binding(chrono), compile_argv=command,
                  transport=binding(ROOT / "hia/datetime_deadline.rs"),
                  replay_source=binding(Path(__file__).with_name("cloud_deadline_callers.rs")))
    compiled = subprocess.run(command, env=env, capture_output=True, timeout=60)
    for stream in ("stdout", "stderr"):
        (args.output / ("compile." + stream)).write_bytes(getattr(compiled, stream))
    report["compile_returncode"] = compiled.returncode
    require(compiled.returncode == 0, "actual cloud calculation replay failed to compile")
    report["executable"] = binding(executable)
    executed = subprocess.run([str(executable), "--nocapture", "--test-threads=1"], env=env,
                              capture_output=True, timeout=120)
    for stream in ("stdout", "stderr"):
        (args.output / ("tests." + stream)).write_bytes(getattr(executed, stream))
    report["test_returncode"] = executed.returncode
    require(executed.returncode == 0 and b"1 passed; 0 failed; 0 ignored" in executed.stdout,
            "actual cloud calculation or native standard duration transport failed")
    records = re.findall(rb"CLOUD_DEADLINE_REPORT=(\{[^\n]+\})", executed.stdout)
    require(len(records) == 1, "caller observation counts are missing or duplicated")
    counts = json.loads(records[0])
    require(counts["input_cases"] == len(cases)
            and counts["cloud_cases"] + counts["generic_cases"] + counts["outside_typed_domain"] == len(cases),
            "caller corpus observation accounting is incomplete")
    report["observations"] = counts
    trace = args.output / "observations.bin"
    require(trace.stat().st_size == len(cases) * 72, "complete original/native trace is truncated")
    report["trace"] = preserve(args.output / "observations.bin.gz", trace.read_bytes())
    require(identity() == producer and binding(chrono) == report["linked_chrono"]
            and all(binding(Path(row["path"])) == row for row in archives), "source or linked implementation changed")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "original-repo", "original-lock", "cargo", "rustc", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("build", "original_repo", "original_lock", "cargo", "rustc"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    args.output = args.output.resolve()
    require(not args.output.is_relative_to(ROOT) and not args.output.is_relative_to(args.build),
            "caller output must be outside source and production native output")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.cloud-deadline-callers.v1", "passed": False, "started_unix": time.time(),
              "controller": binding(Path(__file__).resolve()),
              "scope": "Exact cloud-save date calculation and actual standard duration/UTC date APIs; unit-error category only",
              "clock_seam": "Utc::now() -> identical counting clock in both source fragments",
              "whole_production_crate_qualified": False, "chrono_removed": False, "legacy_retirement": False}
    try:
        qualify(args, report)
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        report["finished_unix"] = time.time()
        path = args.output / "report.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "report": binding(path)}), flush=True)


if __name__ == "__main__":
    main()
