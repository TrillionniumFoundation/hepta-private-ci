"""Record one complete Agentd package run with a private diagnostic compiler cfg."""

import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
CWD = ROOT / "codex-rs"
BASE = "6daa4ecafeecc2c3e80bf72d2bba60319eb76bea"
BASE_TREE = "547a28d6f524492c6a6f6e8bc84acfc48fbd0507"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REF = "refs/heads/integration/hepta-rust-validation-20261117-59d82"
CI_MODES = {
    ".github/workflows/hepta-agentd-phase-diagnostic.yml": "100644",
    ".github/scripts/validate_agentd_phase_diagnostic.py": "100644",
    ".github/scripts/agentd_phase_rustc_wrapper.py": "100755",
}
DIAGNOSTIC_IMAGES = {
    "codex-rs/hepta-agentd/src/circuit_feature_current.rs": {
        "base": "cf84a80c1d0eedbf8fee6d9dffccd5d4730b87a3",
        "post": "8f3db5549ac1f31c320ee6ecdce5525f7929986e",
    },
    "codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs": {
        "base": "300080cc47dea3f0f3af81aeba1c6d4e7fc6c1e6",
        "post": "3694d3a468c9ee80f024ac59070fc83ba22530b0",
    },
    "codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs": {
        "base": "b10334c2e89bb2862ea753708a11cee863ab300b",
        "post": "25637825f1e1807093c446754a22650d93037feb",
    },
    "codex-rs/hepta-agentd/src/circuit_learning_read_service.rs": {
        "base": "d2f5062ce271600fdd20ec87998a6eb40e9693b4",
        "post": "96fdcac65dc53666a446e8eb5834290e1e5da835",
    },
    "codex-rs/hepta-agentd/src/circuit_learning_read_support_tests.rs": {
        "base": "71def38dfe19995ba1caf27bf27dcca0f416b9a5",
        "post": "1d197613143482d4f0669bd6f566d3027ee09e09",
    },
    "codex-rs/hepta-agentd/src/circuit_next_use_command_evidence.rs": {
        "base": "8f2b039c6c96ce90029ef22e29d2ccf5d1ed6039",
        "post": "c6f1e45b950c318417a8f1ec68a45ef44d73ecda",
    },
    "codex-rs/hepta-agentd/src/circuit_next_use_command_owner_tests.rs": {
        "base": "8f1d295d42977224e7784d518af3847e5bc256e1",
        "post": "3649f5d563299481a4d85a3077845e9145709226",
    },
    "codex-rs/hepta-agentd/src/circuit_next_use_command_support_tests.rs": {
        "base": "91fb1d4a1657e328c25318c5935e52c203b5bc43",
        "post": "6aea216e81f8b65d2f688a286a5c061f86abf291",
    },
    "codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs": {
        "base": "a667b23ad21d3bec8407a8f1c466e6d55ea95969",
        "post": "5948a7f824ec042dd8b903f653ebd99d4cb58ef1",
    },
    "codex-rs/hepta-agentd/src/circuit_selection_command_evidence.rs": {
        "base": "8ef7dbaad9bd465c99692f798b9ef6d8a32183e6",
        "post": "7229d4c3758d7ba384b760aaba407afc62876dbb",
    },
    "codex-rs/hepta-agentd/src/circuit_selection_command_support_tests.rs": {
        "base": "9fa17c8f8ad218246c0215c9e35bfa4b5e1225a4",
        "post": "033e044d7e35210c7d4189c25078802c3a7b65e1",
    },
    "codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs": {
        "base": "3fb90129d801c9bc1d8079ec98388c9cd47bdcce",
        "post": "e58c657783a7153f3b57a508ebe7d69ce7074e1f",
    },
    "codex-rs/hepta-agentd/src/neuron_generation_current_store.rs": {
        "base": "edf20edad1435f04ed777762ee9a2faaabb2c094",
        "post": "74dcfab42578495cee89851d9667ee34c9086dec",
    },
    "codex-rs/hepta-agentd/src/neuron_generation_update_live.rs": {
        "base": "6d4cbd37af0c533a6a739bf8c4e7f09dc77eb899",
        "post": "b07412fa893b62fc00ca8894706ce23d10b2b80c",
    },
    "codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs": {
        "base": "930fb5bbb0d468170833218f3dd8e330805a003a",
        "post": "b5449499d806602ac067d5f8661bb48aead458fc",
    },
    "codex-rs/hepta-agentd/src/neuron_generation_update_test_store.rs": {
        "base": "f086e8d54f9ae64e6937b4dae5524410075ccb1d",
        "post": "90d63ddc08682b0db7b2f684f85b3b2efd7df70a",
    },
    "codex-rs/hepta-agentd/src/root_observation_stream.rs": {
        "base": "e229c4e77ffc73288444d987661cc170ffb0877a",
        "post": "0765a2e51660c7e5f7a0b7f9762bcf00ceddaa21",
    },
    "codex-rs/hepta-contracts/src/authority_host_peer.rs": {
        "base": "614eb8399aab090150cc88c1e8c287831dc00d1c",
        "post": "5b9481d012a5cd99b066b7206ae47fcafecff793",
    },
    "codex-rs/hepta-contracts/src/final_use_live_owner.rs": {
        "base": "13744a8e2b3f5cca575cd2fbb7bf3769d1f897e6",
        "post": "0b3047193fc521a253009bb64836811ed9b34d39",
    },
    "codex-rs/hepta-contracts/src/final_use_retained.rs": {
        "base": "1448f86da58da835c08c881c4c333e8219ee3c2e",
        "post": "bd7fdc19f4c34f755eec2d1d551e795fbfab7282",
    },
    "codex-rs/hepta-contracts/src/final_use_store.rs": {
        "base": "6269b7dd6e5a76149d6937b78ee4a3d1f343283b",
        "post": "5af707f76afafedc01029f8ead7b8a4e4b278124",
    },
    "codex-rs/hepta-contracts/src/lib.rs": {
        "base": "8e6b5afbc9e5387b6703d2397cbb74e1c6233bdc",
        "post": "24b263111c59b138fa8bffd80a5a85b0758958d9",
    },
    "codex-rs/hepta-contracts/src/phase_diagnostic.rs": {
        "base": None,
        "post": "a4753c70d31458b96d21c109d5e37831b0220405",
    },
}
CONTROL_PINS = {
    "AGENTS.md": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a",
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/format.py": "d4eabe70b68605933240e9129245f7f4cccbde5d",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
    "scripts/pyproject.toml": "ac49a948a2d32e2bf4576ad5ede4076029dba227",
    "scripts/uv.lock": "3fd02698ddb7a4042cad2f417db92779fafd01bf",
    ".prettierrc.toml": "4c58c583e5fa327928190f625a1095a9c4d9e72f",
    ".codespellignore": "28cc4f7ee35a5e3e192425945b38ca9c386832cc",
    ".codespellrc": "56333087756a027ef7645fc93f58640f7311c71b",
    "codex-rs/Cargo.toml": "e6747d71be508707a49034f37c414bc87ffc91f9",
    "codex-rs/Cargo.lock": "525f6bde0c7e6c5e3de052b910d2f0570ae44879",
    "codex-rs/hepta-agentd/Cargo.toml": "a8d710eb1b18b9f2f67952e20f3bd8f54e9f2cad",
    "codex-rs/hepta-contracts/Cargo.toml": "6a992ea678f603a2460e81370c4d35fefe0174b5",
    "codex-rs/.config/nextest.toml": "dee9888eb89babc27201e5fd19b640ec319aa79e",
    "codex-rs/rust-toolchain.toml": "917d2492264a35bc9c0feaef41878d8825870866",
    ".github/actions/setup-ci/action.yml": "8abd2dbd5f09585734f8213011a9ed540a2ee88e",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "scripts/hepta_cell_test_helpers.py": "f5b702a55b44c081c6d8f5556da3a2152a33eec3",
    "scripts/hepta_ci_v8.py": "088b737c0cca7386161e06b254c794bf972380ad",
    ".github/workflows/hepta-daemon-learning-native.yml": "02a3cdfee4516aed95dd83c9b9d8d2267f60430e",
    ".github/scripts/validate_guardian_microbatch.py": "8e708409cadaf6d9d3507b42fa6aca3c3d517ebe",
}
COMMON_PATH = ".github/scripts/validate_guardian_microbatch.py"
COMMON_BLOB = "8e708409cadaf6d9d3507b42fa6aca3c3d517ebe"
EVIDENCE_CASE = "runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::original_next_use_evidence_timing_diagnostic"
MATERIAL_CASE = "runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::model_material::original_evaluation_model_material_rejects_pages_renewal_and_completed_regression"


def load_common():
    data = (ROOT / COMMON_PATH).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != COMMON_BLOB:
        raise ValueError("the reviewed snapshot and natural-wait helper changed")
    return SimpleNamespace(**runpy.run_path(str(ROOT / COMMON_PATH)))


def validate_event(common, output):
    raw = common.read_bounded(Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024)
    (output / "push-event.json").write_bytes(raw)
    event = json.loads(raw)
    head = os.environ["GITHUB_SHA"]
    if (
        re.fullmatch(r"[0-9a-f]{40}", head) is None
        or head == "0" * 40
        or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != REF
        or not isinstance(event, dict)
        or not isinstance(event.get("repository"), dict)
        or event["repository"].get("full_name") != REPOSITORY
        or event.get("after") != head
        or event.get("ref") != REF
        or event.get("deleted") is not False
    ):
        raise ValueError("not the exact non-deleted temporary-branch push")
    commit = common.git("cat-file", "commit", "HEAD")
    (output / "checkout-commit.raw").write_bytes(commit)
    parents = [
        line[7:].decode()
        for line in commit.split(b"\n\n", 1)[0].splitlines()
        if line.startswith(b"parent ")
    ]
    if common.git("rev-parse", "HEAD").decode().strip() != head:
        raise ValueError("checkout is not the actual push HEAD")
    common.save(
        output / "event-identity.json",
        {
            "head": head,
            "orderedParents": parents,
            "eventSha256": hashlib.sha256(raw).hexdigest(),
        },
    )
    return hashlib.sha256(raw).hexdigest()


def source_guard(common, output):
    if common.git("rev-parse", f"{BASE}^{{tree}}").decode().strip() != BASE_TREE:
        raise ValueError("base source tree differs")
    common.git("merge-base", "--is-ancestor", BASE, "HEAD")
    changed = {
        os.fsdecode(p)
        for p in common.git(
            "diff", "--name-only", "--no-renames", "-z", BASE, "HEAD"
        ).split(b"\0")
        if p
    }
    if changed != set(DIAGNOSTIC_IMAGES) | set(CI_MODES):
        raise ValueError(
            "candidate is not precisely the 23 diagnostic and three CI paths"
        )
    for path, images in DIAGNOSTIC_IMAGES.items():
        original = common.git("ls-tree", BASE, "--", path).decode().strip()
        expected = f"100644 blob {images['base']}\t{path}" if images["base"] else ""
        if original != expected:
            raise ValueError(f"diagnostic preimage differs: {path}")
        current = common.git("ls-tree", "HEAD", "--", path).decode().strip()
        if current != f"100644 blob {images['post']}\t{path}":
            raise ValueError(f"diagnostic postimage differs: {path}")
    for path, mode in CI_MODES.items():
        if common.git("ls-tree", BASE, "--", path):
            raise ValueError(f"CI path already existed in base: {path}")
        entry = common.git("ls-tree", "HEAD", "--", path).decode().split()
        if len(entry) != 4 or entry[:2] != [mode, "blob"]:
            raise ValueError(f"CI path has unexpected mode or object type: {path}")
    for path, blob in CONTROL_PINS.items():
        if common.git("rev-parse", f"HEAD:{path}").decode().strip() != blob:
            raise ValueError(f"original control changed: {path}")
    before, receipt = common.snapshot(output, "source-before")
    if before["status"] or any(
        row.get("blob") != row["indexBlob"]
        or row.get("mode") != row["indexMode"]
        or row["stage"] != "0"
        for row in before["rows"]
    ):
        raise ValueError("checkout/index are not the complete, clean source tree")
    return before, receipt


def environment_guard(common, output):
    fixed = {
        "CARGO_INCREMENTAL": "0",
        "CARGO_BUILD_JOBS": "2",
        "CARGO_PROFILE_TEST_DEBUG": "0",
        "CARGO_PROFILE_DEV_DEBUG": "0",
    }
    forbidden = [
        key
        for key in os.environ
        if (
            key.startswith(
                ("NEXTEST_", "CARGO_PROFILE_", "CARGO_BIN_EXE_", "HEPTA_PHASE_")
            )
            and key not in fixed
        )
        or key
        in {
            "RUST_TEST_THREADS",
            "RUST_MIN_STACK",
            "RUSTFLAGS",
            "CARGO_ENCODED_RUSTFLAGS",
            "RUSTC",
            "RUSTDOC",
            "RUSTC_BOOTSTRAP",
            "RUSTDOCFLAGS",
            "CARGO_ENCODED_RUSTDOCFLAGS",
            "RUSTC_WRAPPER",
            "RUSTC_WORKSPACE_WRAPPER",
            "HEPTA_NEXTTEST_FULL_METADATA",
            "CARGO_BUILD_RUSTFLAGS",
        }
        or (key.startswith("CARGO_TARGET_") and key.endswith("_RUSTFLAGS"))
    ]
    if forbidden or any(os.environ.get(key) != value for key, value in fixed.items()):
        raise ValueError(
            f"unexpected test/build environment overrides: {sorted(forbidden)}"
        )
    if os.environ.get("RUNNER_OS") != "Linux" or os.geteuid() == 0:
        raise ValueError("the ordinary Agentd package requires the normal Linux runner")
    target = Path(os.environ["CARGO_TARGET_DIR"])
    if (
        not target.is_absolute()
        or target.resolve().is_relative_to(ROOT)
        or os.path.lexists(target)
    ):
        raise ValueError("Cargo target must be new and outside the source tree")
    common.save(
        output / "resources-before.json",
        {
            "disk": dict(
                zip(
                    ("total", "used", "free"),
                    shutil.disk_usage(target.parent),
                    strict=True,
                )
            ),
            "meminfo": Path("/proc/meminfo").read_text(),
            "target": str(target),
            "fixedEnvironment": fixed,
            "capacityThresholdApplied": False,
        },
    )
    tools = []
    for argv, pattern in (
        (["rustc", "-Vv"], r"(?m)^release: 1\.96\.0$"),
        (["cargo", "--version"], r"^cargo 1\.96\.0(?:\s|$)"),
        (["rustfmt", "--version"], r"^rustfmt "),
        (["cargo", "clippy", "--version"], r"^clippy 0\.1\.96(?:\s|$)"),
        (["just", "--version"], r"^just 1\.51\.0(?:\s|$)"),
        (["cargo", "nextest", "--version"], r"^cargo-nextest 0\.9\.103(?:\s|$)"),
        (["uv", "--version"], r"^uv 0\.11\.3(?:\s|$)"),
        ([sys.executable, "--version"], r"^Python 3\.12\.14(?:\s|$)"),
        (["git", "--version"], r"^git version "),
    ):
        result = subprocess.run(argv, cwd=CWD, capture_output=True, check=False)
        text = result.stdout.decode(errors="replace") + result.stderr.decode(
            errors="replace"
        )
        tools.append(
            {
                "argv": argv,
                "cwd": str(CWD),
                "exitCode": result.returncode,
                "output": text,
            }
        )
        common.save(output / "tools.json", tools)
        if result.returncode or re.search(pattern, text) is None:
            raise ValueError(f"tool version mismatch: {argv}")
    records = output / "compiler-invocations"
    records.mkdir()
    os.environ["HEPTA_PHASE_WRAPPER_RECORDS"] = str(records)
    os.environ["RUSTC_WRAPPER"] = str(
        ROOT / ".github/scripts/agentd_phase_rustc_wrapper.py"
    )


def helper_command(output):
    return [
        sys.executable,
        "scripts/hepta_cell_test_helpers.py",
        "--package",
        "codex-hepta-infer-worker-host",
        "--package",
        "codex-cli",
        "--output-dir",
        str(output / "helpers"),
    ]


def commands_for(output):
    return [
        ("format", ["just", "fmt"], CWD, 600),
        ("format-base", ["just", "fmt", "--base", BASE], CWD, 600),
        ("format-check", ["just", "fmt", "--base", BASE, "--check"], CWD, 600),
        (
            "locked-fetch",
            ["cargo", "fetch", "--locked", "--target", "x86_64-unknown-linux-gnu"],
            CWD,
            None,
        ),
        (
            "scoped-fix",
            [
                "just",
                "fix",
                "--locked",
                "--offline",
                "-p",
                "codex-hepta-agentd",
                "-p",
                "codex-hepta-contracts",
            ],
            CWD,
            7200,
        ),
        ("helper-build", helper_command(output), ROOT, 3600),
        ("helpers-before", [*helper_command(output), "--verify-only"], ROOT, 120),
        (
            "agentd-test",
            [
                "just",
                "test",
                "--locked",
                "--offline",
                "-p",
                "codex-hepta-agentd",
                "--test-threads",
                "2",
                "--retries",
                "0",
                "--status-level",
                "pass",
                "--success-output",
                "final",
                "--failure-output",
                "final",
            ],
            CWD,
            7200,
        ),
    ]


def execute_stage(common, output, result, before, spec):
    role, argv, cwd, budget = spec
    number = len(result["commands"]) + 1
    os.environ["HEPTA_PHASE_STAGE"] = role
    controls = {
        key: os.environ.get(key)
        for key in (
            "RUSTC_WRAPPER",
            "HEPTA_PHASE_WRAPPER_RECORDS",
            "HEPTA_PHASE_STAGE",
            "CARGO_PROFILE_TEST_DEBUG",
            "CARGO_PROFILE_DEV_DEBUG",
            "CARGO_BIN_EXE_codex",
            "CARGO_BIN_EXE_hepta-joint-propose",
            "CARGO_BIN_EXE_hepta_joint_propose",
        )
    }
    common.save(
        output / f"dispatch-{number}.json",
        {
            "role": role,
            "argv": argv,
            "cwd": str(cwd),
            "diagnosticAndHelperEnvironment": controls,
            "originalBudgetSeconds": budget,
            "budgetObservation": "natural completion only; this runner sends no signal",
        },
    )
    execution = common.command(output, number, argv, cwd)
    execution.update(
        role=role,
        originalBudgetSeconds=budget,
        budgetExceeded=budget is not None and execution["elapsedSeconds"] > budget,
    )
    result["commands"].append(execution)
    if execution["exitCode"] and result["originalCommandExitCode"] is None:
        result["originalCommandExitCode"] = execution["exitCode"]
    common.save(output / "result.json", result)
    if role == "agentd-test":
        try:
            evidence, trace = collect_test(
                common,
                output,
                CWD / "target/nextest/local/junit.xml",
                result["junitBeforeTest"]["notBeforeNs"],
            )
            result.update(testEvidence=evidence, traceEvidence=trace)
        except (OSError, ValueError, ET.ParseError) as error:
            result["testEvidence"] = {"passed": False, "error": str(error)}
    after, receipt = common.snapshot(output, f"source-after-{number}")
    execution.update(sourceAfter=receipt, sourceUnchanged=after == before)
    common.save(output / f"command-{number}.json", execution)
    common.save(output / "result.json", result)
    if after != before:
        common.preserve_source_change(output, before, after, receipt)
        raise ValueError("source changed; later gates were not dispatched")
    return execution


def stage_passed(execution):
    return (
        execution["exitCode"] == 0
        and execution["logComplete"]
        and not execution["budgetExceeded"]
    )


def collect_test(common, output, report, not_before_ns):
    data, identity = common.read_fresh_junit(report, not_before_ns)
    (output / "agentd-junit.xml").write_bytes(data)
    # Retain the complete raw XML before parsing; a failure or malformed XML
    # must not discard the test's actual stdout, stderr, or timeout result.
    cases = common.junit_cases(data)
    common.save(output / "test-cases.json.gz", cases)
    selected = {
        name: [
            row
            for row in cases
            if row["name"] == name and row["classname"] == "codex-hepta-agentd"
        ]
        for name in (EVIDENCE_CASE, MATERIAL_CASE)
    }
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for row in cases:
        outcome = (
            "failed"
            if any(v in {"failure", "error"} for v in row["outcomes"])
            else "skipped"
            if "skipped" in row["outcomes"]
            else "passed"
        )
        counts[outcome] += 1
    evidence = {
        "report": identity,
        "counts": counts,
        "requiredCases": selected,
        "requiredCasesExecuted": all(
            len(rows) == 1 and "skipped" not in rows[0]["outcomes"]
            for rows in selected.values()
        ),
        "passed": counts["passed"] > 0 and counts["failed"] == 0,
    }
    evidence["passed"] = evidence["passed"] and evidence["requiredCasesExecuted"]
    common.save(output / "agentd-test-evidence.json", evidence)
    nodes = [
        case
        for case in ET.fromstring(data).iter("testcase")
        if case.get("name") == EVIDENCE_CASE
        and case.get("classname") == "codex-hepta-agentd"
    ]
    events, footers, errors = [], [], []
    for node in nodes:
        for part in node:
            if part.tag not in {"system-out", "system-err"}:
                continue
            for line in (part.text or "").splitlines():
                if line.startswith("HEPTA_PHASE_EVENT "):
                    try:
                        events.append(
                            json.loads(line.removeprefix("HEPTA_PHASE_EVENT "))
                        )
                    except ValueError as error:
                        errors.append(str(error))
                elif line.startswith("HEPTA_PHASE_TRACE_END "):
                    match = re.fullmatch(
                        r"HEPTA_PHASE_TRACE_END events=(\d+) lost=(\d+) cleanup_complete=(true|false)",
                        line,
                    )
                    if match:
                        footers.append(
                            {
                                "events": int(match[1]),
                                "lost": int(match[2]),
                                "cleanupComplete": match[3] == "true",
                            }
                        )
                    else:
                        errors.append(line)
                elif line.startswith("HEPTA_PHASE_TRACE_INCOMPLETE"):
                    errors.append(line)
    common.save(output / "phase-events.json.gz", events)
    trace = {
        "events": len(events),
        "footers": footers,
        "errors": errors,
        "completeBufferedOutput": not errors
        and len(footers) == 1
        and footers[0]["events"] == len(events)
        and len(events) > 0
        and footers[0]["lost"] == 0,
        "cleanupObserved": len(footers) == 1 and footers[0]["cleanupComplete"],
        "interpretation": "returned means finish/Ready, not Result::Ok; outer or zero request contexts remain possible; stderr flush can block and a killed test may have no footer",
    }
    common.save(output / "phase-trace-evidence.json", trace)
    return evidence, trace


def wrapper_census(common, output):
    wrapper = runpy.run_path(
        str(ROOT / ".github/scripts/agentd_phase_rustc_wrapper.py")
    )
    rows = []
    for path in sorted((output / "compiler-invocations").glob("*.json")):
        record = json.loads(common.read_bounded(path, 1024 * 1024))
        expected = wrapper["transform"](
            record["originalArguments"], Path(record["cwd"])
        )
        if record.get("root") != str(ROOT) or any(
            record.get(key) != value for key, value in expected.items()
        ):
            raise ValueError(
                f"compiler wrapper changed an unapproved argument: {path.name}"
            )
        rows.append(
            {
                "path": path.name,
                "crate": record["crate"],
                "injected": record["injected"],
                "test": "--test" in record["originalArguments"],
                "identity": common.file_identity(path),
            }
        )
    selected = {row["crate"] for row in rows if row["injected"]}
    complete = selected == {"codex_hepta_agentd", "codex_hepta_contracts"} and any(
        row["crate"] == "codex_hepta_agentd" and row["injected"] and row["test"]
        for row in rows
    )
    census = {
        "calls": rows,
        "complete": complete,
        "scope": "pre-exec invocation audit; compiler success comes from the naturally completed Cargo/just command",
    }
    common.save(output / "compiler-wrapper-census.json.gz", census)
    return complete


def finalize(common, output, result):
    try:
        result["unresolvedCommandRecords"] = [
            p.name
            for p in sorted(output.glob("command-*.json"))
            if json.loads(p.read_text()).get("status") == "running"
        ]
        if result["unresolvedCommandRecords"]:
            result.update(
                status="incomplete",
                childState="natural completion not observed; no signal sent",
            )
        result["finishedAt"] = common.now()
        common.save(output / "result.json", result)
        inventory = [
            {"path": p.relative_to(output).as_posix(), **common.file_identity(p)}
            for p in sorted(output.rglob("*"))
            if (p.is_file() or p.is_symlink())
            and not p.is_relative_to(output / "helpers/bin")
            and p != output / "artifact-inventory.json"
        ]
        common.save(
            output / "artifact-inventory.json",
            {
                "schemaVersion": 1,
                "scope": "saved evidence excluding this inventory and helper executables; helper lengths/hashes remain in the original manifest and before/after verification",
                "files": inventory,
            },
        )
    except (OSError, ValueError) as error:
        if result["status"] not in {"interrupted", "incomplete"}:
            result["status"] = "failed"
        result["artifactFinalizationError"] = f"{type(error).__name__}: {error}"
        for name, value in (
            (
                "artifact-finalization-error.json",
                {
                    "error": result["artifactFinalizationError"],
                    "originalCommandExitCode": result["originalCommandExitCode"],
                },
            ),
            ("result.json", result),
        ):
            try:
                common.save(output / name, value)
            except (OSError, ValueError):
                pass
    original = result["originalCommandExitCode"]
    return (
        0
        if result["status"] == "passed"
        else original
        if isinstance(original, int) and 0 < original < 256
        else 1
    )


def main():
    common = load_common()
    output = Path(os.environ["HEPTA_VALIDATION_OUTPUT"])
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("records must be outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "running",
        "startedAt": common.now(),
        "base": BASE,
        "baseTree": BASE_TREE,
        "diagnosticOnly": True,
        "unmodifiedNativeQualification": False,
        "commands": [],
        "originalCommandExitCode": None,
    }
    common.save(output / "result.json", result)
    before = None
    try:
        event_sha = validate_event(common, output)
        before, receipt = source_guard(common, output)
        result.update(
            head=before["head"],
            tree=before["tree"],
            sourceBefore=receipt,
            eventSha256=event_sha,
        )
        environment_guard(common, output)
        report = CWD / "target/nextest/local/junit.xml"
        for spec in commands_for(output):
            role = spec[0]
            if role == "agentd-test":
                fresh = common.require_absent_junit(report)
                result["junitBeforeTest"] = fresh
            common.save(output / "result.json", result)
            execution = execute_stage(common, output, result, before, spec)
            if role == "agentd-test":
                # Verify the pinned helper copies even after an observed test
                # failure. This does not rebuild or repeat any test.
                verification = execute_stage(
                    common,
                    output,
                    result,
                    before,
                    (
                        "helpers-after",
                        [*helper_command(output), "--verify-only"],
                        ROOT,
                        120,
                    ),
                )
                result["compilerWrapperComplete"] = wrapper_census(common, output)
                if (
                    not stage_passed(verification)
                    or not result.get("testEvidence", {}).get("passed")
                    or not result.get("traceEvidence", {}).get("completeBufferedOutput")
                    or not result.get("traceEvidence", {}).get("cleanupObserved")
                    or not result["compilerWrapperComplete"]
                ):
                    raise ValueError(
                        "test, helper, wrapper or diagnostic evidence is failed/incomplete"
                    )
            if not stage_passed(execution):
                raise ValueError(
                    "original command failed, exceeded its recorded budget or lost output"
                )
            if role == "helpers-before":
                values = json.loads(
                    common.read_bounded(output / "helpers/env.json", 1024 * 1024)
                )
                if set(values) != {
                    "CARGO_BIN_EXE_codex",
                    "CARGO_BIN_EXE_hepta-joint-propose",
                    "CARGO_BIN_EXE_hepta_joint_propose",
                } or not all(isinstance(v, str) for v in values.values()):
                    raise ValueError(
                        "verified helper environment has unexpected keys or types"
                    )
                os.environ.update(values)
        final, receipt = common.snapshot(output, "source-final")
        result["sourceFinal"] = receipt
        if (
            final != before
            or hashlib.sha256(
                common.read_bounded(
                    Path(os.environ["GITHUB_EVENT_PATH"]), 2 * 1024 * 1024
                )
            ).hexdigest()
            != event_sha
        ):
            raise ValueError("final source or push event changed")
        result["status"] = "passed"
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        ET.ParseError,
    ) as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    except KeyboardInterrupt:
        result.update(
            status="interrupted", childState="unknown; no signal sent by this runner"
        )
    finally:
        returncode = finalize(common, output, result)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
