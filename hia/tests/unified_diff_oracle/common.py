"""Actual commands, immutable source inventories and canonical native admission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
import time
import types

BASE = "aeb88f596b83186456caac577080bcb2f253ad32"
CRATE = "codex-rs/apply-patch"
CRATE_TREE = "df2e05444c0768915f267c7aa5ba65f896a54ec5"
DRIVER_SHA = "8488fc2c358d14e0f1a5a51f1d91fe1f0b86a0c23d2ff84a8298720bffb05f6b"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def bind(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def create(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def snapshot(repo):
    names = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    rows = []
    for name in sorted(set(names) - {""}):
        path = repo / name
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            data = os.readlink(path).encode()
            row = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": "symlink"}
        else:
            require(stat.S_ISREG(mode), "unsupported source file kind")
            row = {"bytes": path.stat().st_size, "sha256": sha(path), "kind": "file"}
        rows.append(dict(row, path=name, mode=oct(stat.S_IMODE(mode))))
    return rows


def arguments(description, *, public=False):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path)
    parser.add_argument("--offline", action="store_true")
    if public:
        parser.add_argument("--original-root", type=Path, required=True,
                            help="Git repository containing the exact aeb88 original object")
        parser.add_argument("--policy-report", type=Path, required=True)
    return parser.parse_args()


class Context:
    sha = staticmethod(sha)
    bind = staticmethod(bind)
    create = staticmethod(create)

    def __init__(self, args, schema):
        require(__debug__, "qualification cannot run with Python assertions disabled")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        self.args = args
        self.repo = args.repo.resolve(strict=True)
        self.rustc = args.rustc.resolve(strict=True)
        self.output = args.output_dir.resolve()
        self.report_path = args.report.resolve()
        self.library_dir = args.library_dir.resolve(strict=True)
        require(not self.output.is_relative_to(self.repo) and not self.report_path.is_relative_to(self.repo),
                "qualification output must be outside the source checkout")
        require(not self.output.exists() and not self.report_path.exists(), "qualification output already exists")
        require(not git(self.repo, "status", "--porcelain", "--untracked-files=all").strip(),
                "qualification requires a clean producing checkout")
        self.output.mkdir(parents=True)
        self.report = {"schema": schema, "passed": False, "commands": [], "tests_skipped": 0,
                       "whole_product_qualified": False, "all_build_arrangements_qualified": False,
                       "mixed_policy_qualified": False, "lto_qualified": False,
                       "performance_qualified": False, "compiler": bind(self.rustc),
                       "producer_commit": git(self.repo, "rev-parse", "HEAD").decode().strip(),
                       "producer_tree": git(self.repo, "rev-parse", "HEAD^{tree}").decode().strip()}
        self.before = snapshot(self.repo)
        create(self.output / "source-before.json", self.before)
        self.report["source_before"] = bind(self.output / "source-before.json")
        module_path = self.repo / "hia/unified_policy_ci.py"
        module = types.ModuleType("unified_policy_ci")
        module.__file__ = str(module_path)
        exec(compile(module_path.read_bytes(), str(module_path), "exec"), module.__dict__)
        self.ci = module
        env = os.environ.copy()
        require(not env.get("RUSTC_WORKSPACE_WRAPPER"), "qualification starts with the ordinary compiler; Clippy installs its own verified chain")
        config_path = env.get("CODEX_HIA_SIMILAR_POLICY_CONFIG")
        require(config_path, "prepare the per-checkout policy configuration before this gate")
        self.config, config_binding = module.validate_configuration(self.repo, self.rustc, config_path)
        wrapper = str(self.repo / "hia/similar_policy.py")
        require(env.get("RUSTC_WRAPPER") in (None, "", wrapper), "an existing wrapper cannot be silently replaced")
        target = args.target_dir or Path(env.get("CARGO_TARGET_DIR", self.output / "target"))
        target = target.resolve()
        require(not target.is_relative_to(self.repo), "Cargo target must be outside the source checkout")
        env.update(RUSTC=str(self.rustc), RUSTC_WRAPPER=wrapper, RUSTUP_TOOLCHAIN="1.96.1",
                   CARGO_BUILD_JOBS="1", CARGO_INCREMENTAL="0", CARGO_PROFILE_DEV_DEBUG="0",
                   CARGO_PROFILE_TEST_DEBUG="0", CARGO_TARGET_DIR=str(target),
                   CODEX_HIA_NATIVE_LIB_DIR=str(self.library_dir), PYTHONDONTWRITEBYTECODE="1")
        env["PATH"] = str(self.rustc.parent) + os.pathsep + env.get("PATH", "")
        self.env = env
        self.report["configuration"] = config_binding
        self.report["environment"] = {k: v for k, v in env.items() if k in {
            "RUSTC", "RUSTC_WRAPPER", "RUSTUP_TOOLCHAIN", "CODEX_HIA_SIMILAR_POLICY_CONFIG",
            "CODEX_HIA_NATIVE_LIB_DIR", "CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL",
            "CARGO_PROFILE_DEV_DEBUG", "CARGO_PROFILE_TEST_DEBUG", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
            "BINDGEN_EXTRA_CLANG_ARGS", "TMPDIR"} or k.startswith("CARGO_PROFILE_")}
        self.report["policy_environment"] = module.admit_environment(self.repo, self.rustc, env)
        self.helper = module.load_helper(self.repo)
        self.helper_cfg = {**self.config, "_root": Path(self.config["receipt_root"]),
                           "_binding": bind(config_path)}
        self.native_before = self.native_inputs()
        self.report["native_inputs"] = self.native_before

    def native_inputs(self):
        path = self.library_dir / "build.json"
        build = json.loads(path.read_text())
        require(build.get("status") == "built" and build.get("compiler_fixed_point") is True,
                "a real canonical fixed-point native build is required")
        record = build["modules"]["unified_diff"]
        source = self.repo / "hia/unified_diff.hepta"
        archive = self.library_dir / "libcodex_hia_unified_diff.a"
        abi = record["codex_link_abi"]
        require(record["source_sha256"] == sha(source) == self.ci.EXACT["hia/unified_diff.hepta"],
                "canonical native source differs from frozen v4")
        require(abi["symbol"] == "codex_hia_unified_diff" and abi["archive_sha256"] == sha(archive),
                "canonical archive/symbol binding differs")
        return {"build": bind(path), "source": bind(source), "archive": bind(archive), "symbol": abi["symbol"],
                "scope": "Source/archive binding for unified_diff; other module receipt gates remain separate."}

    def run(self, name, argv, env=None, stdin=None, *, expected=0, diagnostic=None, timeout=None):
        start = time.monotonic()
        stdout, stderr = self.output / (name + ".stdout"), self.output / (name + ".stderr")
        with stdout.open("xb") as out, stderr.open("xb") as err:
            source = Path(stdin).open("rb") if stdin is not None else None
            try:
                result = subprocess.run([str(a) for a in argv], cwd=self.repo / "codex-rs",
                                        env=env or self.env, stdin=source, stdout=out, stderr=err, timeout=timeout)
            finally:
                if source:
                    source.close()
        row = {"name": name, "argv": [str(a) for a in argv], "cwd": str(self.repo / "codex-rs"),
               "returncode": result.returncode, "signal": -result.returncode if result.returncode < 0 else None,
               "seconds": time.monotonic() - start, "stdout": bind(stdout), "stderr": bind(stderr)}
        if stdin is not None:
            row["stdin"] = bind(stdin)
        self.report["commands"].append(row)
        (self.output / "commands.json").write_text(json.dumps(self.report["commands"], indent=2) + "\n")
        require(result.returncode == expected, f"{name} returned {result.returncode}; expected {expected}; see {stderr}")
        if diagnostic is not None:
            require(diagnostic in stderr.read_text(errors="replace"), "required rejection reason missing: " + name)
        return row

    def finish(self, failure=None):
        try:
            self.report["source_unchanged"] = snapshot(self.repo) == self.before
            self.report["native_inputs_unchanged"] = self.native_inputs() == self.native_before
        except Exception as error:
            self.report["source_unchanged"] = False
            self.report["native_inputs_unchanged"] = False
            failure = (failure or "") + "\nFinal input admission failed: " + str(error)
        self.report["passed"] = failure is None and self.report["source_unchanged"] and self.report["native_inputs_unchanged"]
        if failure is not None:
            self.report["exception"] = failure
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        create(self.report_path, self.report)
        print(json.dumps({"passed": self.report["passed"], "report": bind(self.report_path)}), flush=True)
        return 0 if self.report["passed"] else 1
