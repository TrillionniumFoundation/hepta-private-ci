"""Replay exact original/current cache methods and the original plugin TTL test."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
from datetime_calendar_oracle.custody import binding, require
from test_datetime_calendar import identity

ROOT = Path(__file__).resolve().parents[2]


def extract(text, pattern):
    matches = list(re.finditer(pattern, text, re.M | re.S))
    require(len(matches) == 1, "production method or original test is missing or duplicated")
    return matches[0][0]


def qualify(args, report):
    require(sys.flags.optimize == 0, "caller qualification cannot disable assertions")
    before = identity()
    contract = json.loads((ROOT / "hia/datetime_cache_buffer_contract.json").read_bytes())
    differential = json.loads((args.differential / "report.json").read_bytes())
    require(differential["passed"] and differential["producer"] == before,
            "complete differential belongs to another producing tree or failed")
    custody = json.loads((args.differential / "original-custody.json").read_bytes())
    require(binding(args.rustc) == custody["toolchain"]["rustc"], "caller compiler differs from original oracle")
    report.update(producer=before, differential=binding(args.differential / "report.json"),
                  rustc=custody["toolchain"]["rustc"], clock_seam="Utc::now() -> super::read_clock() in both model methods only")
    baseline = contract["reference"]["commit"]
    originals, currents = {}, {}
    for row in contract["production_callers"]:
        raw = subprocess.check_output(["git", "-C", str(args.original_repo), "show", baseline + ":" + row["path"]])
        require(len(raw) == row["original_bytes"] and hashlib.sha256(raw).hexdigest() == row["original_sha256"],
                "original complete caller file differs from its immutable commit")
        current = (ROOT / row["path"]).read_bytes()
        require(len(current) == row["current_bytes"] and hashlib.sha256(current).hexdigest() == row["current_sha256"],
                "current complete caller file differs")
        originals[row["path"]] = raw.decode()
        currents[row["path"]] = current.decode()
    test_path = "codex-rs/core-plugins/src/remote/catalog_cache_tests.rs"
    original_tests = subprocess.check_output(["git", "-C", str(args.original_repo), "show", baseline + ":" + test_path])
    require(original_tests == (ROOT / test_path).read_bytes(), "complete original plugin tests changed")
    test = extract(original_tests.decode(), r"^#\[test\]\nfn catalog_cache_freshness_honors_ttl\(\) \{\n.*?^\}\n")
    report["original_test"] = {"path": test_path, "sha256": hashlib.sha256(test.encode()).hexdigest()}
    model_path, plugin_path = [row["path"] for row in contract["production_callers"]]
    generated, methods = [], []
    for label, sources in [("original", originals), ("current", currents)]:
        model = extract(sources[model_path], r"^    fn is_fresh\(&self, ttl: Duration\) -> bool \{\n.*?^    \}\n")
        plugin = extract(sources[plugin_path], r"^fn is_fresh\(fetched_at: Option<DateTime<Utc>>, now: DateTime<Utc>\) -> bool \{\n.*?^\}\n")
        ttl = extract(sources[plugin_path], r"^const REMOTE_PLUGIN_CATALOG_DISK_CACHE_TTL: Duration = [^\n]+;\n")
        require(model.count("Utc::now()") == (1 if label == "original" else 2), "model clock call inventory changed")
        methods.append({"kind": label, "model_sha256": hashlib.sha256(model.encode()).hexdigest(),
                        "plugin_sha256": hashlib.sha256(plugin.encode()).hexdigest(),
                        "clock_substitutions": model.count("Utc::now()"), "original_test_sha256": report["original_test"]["sha256"]})
        model = model.replace("Utc::now()", "super::read_clock()")
        native = (f'#[path = {json.dumps(str(ROOT / "hia/datetime_cache.rs"))}]\nmod hia_datetime_cache;\n'
                  if label == "current" else "")
        generated.append(f"mod {label} {{\nuse super::*;\n" + native + ttl
                         + "struct ModelsCacheEntry { fetched_at: DateTime<Utc> }\nimpl ModelsCacheEntry {\n"
                         + model + "}\n" + plugin + test
                         + "pub fn model(fetched_at: DateTime<Utc>, now: DateTime<Utc>, ttl: Duration) -> (bool,u64) {\n"
                         + "CLOCK.with(|clock| clock.set(Some((now,0))));\n"
                         + "let result = ModelsCacheEntry { fetched_at }.is_fresh(ttl);\n"
                         + "(result, CLOCK.with(|clock| clock.get().unwrap().1))\n}\n"
                         + "pub fn plugin(fetched_at: Option<DateTime<Utc>>, now: DateTime<Utc>) -> bool { is_fresh(fetched_at,now) }\n}\n")
    generated_path = args.output / "production_methods.rs"
    generated_path.write_text("".join(generated))
    report.update(methods=methods, generated_source=binding(generated_path),
                  transport=binding(ROOT / "hia/datetime_cache.rs"),
                  replay_source=binding(Path(__file__).with_name("datetime_cache_callers.rs")))
    messages = [json.loads(line) for line in (args.differential / "build.stdout").read_bytes().splitlines()]
    chrono = [path for item in messages if item.get("reason") == "compiler-artifact"
              and item["target"]["name"] == "chrono" for path in item["filenames"] if path.endswith(".rlib")]
    require(len(chrono) == 1, "original oracle has no unique compiled Chrono library")
    chrono = Path(chrono[0]).resolve(strict=True)
    require(chrono.is_relative_to(args.differential / "target"), "original library escaped its fresh target")
    archive = args.build / "libcodex_hia_datetime_cache.a"
    build = json.loads((args.build / "build.json").read_bytes())
    require(binding(archive)["sha256"] == build["modules"]["datetime_cache"]["codex_link_abi"]["archive_sha256"],
            "linked native archive differs from the production build")
    corpus = args.output / "caller-inputs.bin"
    with gzip.open(args.differential / "inputs.bin.gz", "rb") as source, corpus.open("xb") as dest:
        while block := source.read(1024 * 1024):
            dest.write(block)
    require(binding(corpus)["sha256"] == contract["differential_corpus"]["input_sha256"], "caller corpus changed")
    executable = args.output / "cache-callers"
    command = [str(args.rustc), "--edition=2024", "--test", "--cfg", 'feature="hia-native"',
               str(Path(__file__).with_name("datetime_cache_callers.rs")), "--extern", "chrono=" + str(chrono),
               "-L", "dependency=" + str(chrono.parent), "-L", "native=" + str(args.build),
               "-l", "static=codex_hia_datetime_cache", "-o", str(executable)]
    env = dict(os.environ, CODEX_DATETIME_CACHE_METHODS=str(generated_path), CODEX_DATETIME_CACHE_CASES=str(corpus))
    require(not env.get("RUSTFLAGS") and not env.get("CARGO_ENCODED_RUSTFLAGS"), "external flags are not admitted")
    report.update(linked_chrono=binding(chrono), linked_native=binding(archive), compile_argv=command)
    compiled = subprocess.run(command, env=env, capture_output=True, timeout=60)
    (args.output / "compile.stdout").write_bytes(compiled.stdout)
    (args.output / "compile.stderr").write_bytes(compiled.stderr)
    report["compile_returncode"] = compiled.returncode
    require(compiled.returncode == 0, "actual caller replay failed to compile")
    report["executable"] = binding(executable)
    executed = subprocess.run([str(executable), "--nocapture", "--test-threads=1"], env=env,
                              capture_output=True, timeout=120)
    (args.output / "tests.stdout").write_bytes(executed.stdout)
    (args.output / "tests.stderr").write_bytes(executed.stderr)
    report["test_returncode"] = executed.returncode
    require(executed.returncode == 0 and b"3 passed; 0 failed; 0 ignored" in executed.stdout,
            "actual callers or the original plugin TTL test failed")
    records = re.findall(rb"CACHE_CALLER_REPORT=(\{[^\n]+\})", executed.stdout)
    require(len(records) == 1, "caller observation report is missing or duplicated")
    observed = json.loads(records[0])
    report["observations"] = observed
    require(observed == contract["caller_replay_observations"], "actual caller coverage or clock behavior differs")
    require(identity() == before and binding(chrono) == report["linked_chrono"]
            and binding(archive) == report["linked_native"], "producing source or linked implementations changed")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("build", "differential", "rustc", "original-repo", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("build", "differential", "rustc", "original_repo"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    args.output = args.output.resolve()
    require(not any(args.output.is_relative_to(path) for path in (ROOT, args.build, args.differential)),
            "caller output must be outside source and existing evidence")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.datetime-cache-production-callers.v1", "passed": False,
              "started_unix": time.time(), "controller": binding(Path(__file__).resolve()),
              "scope": "Exact production cache methods with symmetric clock injection and unchanged original plugin TTL test",
              "whole_production_crates_qualified": False, "whole_product_qualified": False, "legacy_retirement": False}
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
