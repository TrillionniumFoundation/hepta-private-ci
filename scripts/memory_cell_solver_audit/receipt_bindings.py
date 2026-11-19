"""Offline bindings between independently expected source and retained receipts."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


RECIPE = "scripts/memory_cell_solver/recipe.json"
EVALUATION = "scripts/memory_cell_evaluation"
DOCUMENT_BYTES = 8 * 1024 * 1024


def require(passed, message):
    if not passed:
        raise ValueError(message)


def unique(pairs):
    value = dict(pairs)
    require(len(value) == len(pairs), "duplicate JSON field")
    return value


def raw_identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def valid_identity(value):
    require(
        isinstance(value, dict)
        and set(value) == {"bytes", "sha256"}
        and type(value["bytes"]) is int
        and value["bytes"] >= 0
        and isinstance(value["sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None,
        "invalid byte identity",
    )
    return value


def read_raw(path, limit=DOCUMENT_BYTES):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "regular retained file required")
    require(type(limit) is int and limit >= 0, "nonnegative byte bound required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "retained file exceeds fixed byte bound")
    return raw


def document(path, pin):
    require(
        isinstance(pin, dict) and set(pin) == {"path", "bytes", "sha256"},
        "closed frozen document identity required",
    )
    logical_path(pin["path"])
    identity = valid_identity({key: pin[key] for key in ("bytes", "sha256")})
    require(0 < identity["bytes"] <= DOCUMENT_BYTES, "bounded frozen document required")
    raw = read_raw(path, identity["bytes"])
    require(raw_identity(raw) == identity, "frozen document bytes changed")
    return json.loads(raw, object_pairs_hook=unique)


def logical_path(value):
    require(isinstance(value, str) and "\0" not in value, "logical path text required")
    path = PurePosixPath(value)
    require(
        path.is_absolute() and ".." not in path.parts and str(path) == value,
        "normalized absolute logical path required",
    )
    return path


def relative_path(value):
    require(isinstance(value, str) and "\0" not in value, "relative path text required")
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and str(path) == value
        and value not in ("", "."),
        "normalized relative path required",
    )
    return path


def verify_recipe(protocol, expected):
    source = expected["recipe_source_utf8"]
    require(isinstance(source, str), "independent recipe source text required")
    raw = source.encode("utf-8")
    pin = valid_identity(expected["files"][RECIPE])
    require(raw_identity(raw) == pin, "independent recipe source bytes differ from pin")
    recipe = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(recipe, dict), "independent recipe object required")
    require(
        all(
            key in protocol and protocol[key] == value for key, value in recipe.items()
        ),
        "protocol differs from independently pinned recipe",
    )
    logical_path(expected["source_root"])
    require(
        expected["files"]["scripts/memory_cell_solver/model_manifest.json"]["sha256"]
        == recipe["model_manifest_sha256"],
        "independent recipe model-manifest pin differs",
    )
    return recipe


def evaluation_sources(expected):
    prefix = EVALUATION + "/"
    sources = {}
    for name, pin in expected["files"].items():
        relative_path(name)
        valid_identity(pin)
        if name.startswith(prefix):
            relative = name[len(prefix) :]
            relative_path(relative)
            sources[relative] = pin
    require(bool(sources), "independent executor source inventory required")
    return sources


def qualification_python(expected, registered):
    if "qualification_python" not in expected:
        return registered
    binding = expected["qualification_python"]
    require(
        isinstance(binding, dict) and set(binding) == {"argv0", "resolved"},
        "closed independent qualification Python alias required",
    )
    logical_path(binding["argv0"])
    logical_path(binding["resolved"])
    require(
        binding["resolved"] == registered,
        "independent Python alias differs from the frozen runtime tool",
    )
    return binding["argv0"]


def verify_qualification(directory, task, frozen, expected):
    directory = Path(directory)
    spec = expected["contracts"][task]
    contract_sha = expected["contract_hashes"][task]
    profile_pin = frozen["runtime_profile"]
    require(
        set(profile_pin) == {"path", "sha256", "tools"},
        "closed frozen runtime profile required",
    )
    task_root = logical_path(frozen["input"]["path"]).parent
    require(
        str(task_root / "task-input.json") == frozen["input"]["path"]
        and str(task_root / "fixture") == frozen["fixture"]
        and str(task_root / "runtime-profile.json") == profile_pin["path"]
        and str(task_root / "qualification/qualification.json")
        == frozen["qualification"]["path"]
        and str(task_root / "qualification-command.json")
        == frozen["qualification_command"]["path"],
        "frozen task paths disagree",
    )
    raw = read_raw(directory / "runtime-profile.json", 16384)
    require(
        hashlib.sha256(raw).hexdigest() == profile_pin["sha256"],
        "frozen runtime profile bytes changed",
    )
    profile = json.loads(raw, object_pairs_hook=unique)
    require(
        set(profile) == {"schema", "task_contract_sha256", "tools"}
        and profile["schema"] == "hepta.memory-cell.runtime-profile.v1"
        and profile["task_contract_sha256"] == contract_sha
        and set(profile["tools"]) == set(spec["tools"]) == set(profile_pin["tools"]),
        "runtime profile contract or tool set differs",
    )
    for name, pin in profile["tools"].items():
        valid_identity(pin)
        require(pin["bytes"] > 0, "empty runtime executable identity")
        logical_path(profile_pin["tools"][name])
    runtime = {
        "sha256": profile_pin["sha256"],
        "tools": profile["tools"],
        "mode": "controller_supplied",
        "qualification_proven_by_profile_alone": False,
    }
    qualified = document(
        directory / "qualification/qualification.json", frozen["qualification"]
    )
    command = document(
        directory / "qualification-command.json", frozen["qualification_command"]
    )
    require(
        qualified.get("accepted") is True
        and qualified.get("tests_run") == {"ruff": 9, "codec": 6}[task]
        and all(qualified.get(key) == 0 for key in ("failures", "errors", "skips"))
        and type(command.get("returncode")) is int
        and command["returncode"] == 0
        and command.get("runtime_profile_sha256") == profile_pin["sha256"],
        "matching frozen runtime qualification did not succeed",
    )
    require(
        qualified.get("runtime_profile_sha256") == profile_pin["sha256"]
        if task == "ruff"
        else qualified.get("contract_sha256") == contract_sha
        and qualified.get("runtime") == runtime,
        "qualification receipt belongs to another runtime or task",
    )
    harness = (
        EVALUATION
        + "/"
        + ("test_ruff_executor.py" if task == "ruff" else "test_codec_executor_v2.py")
    )
    require(harness in expected["files"], "qualification harness missing source pin")
    argv = command.get("argv", [])
    require(
        isinstance(argv, list)
        and all(isinstance(value, str) for value in argv)
        and len(argv) >= 3
        and argv[:3]
        == [
            qualification_python(expected, profile_pin["tools"]["python"]),
            "-B",
            str(logical_path(expected["source_root"]) / harness),
        ]
        and len(argv[3:]) % 2 == 0,
        "qualification command is not the independently registered harness",
    )
    flags = dict(zip(argv[3::2], argv[4::2]))
    wanted = {
        "--fixture": frozen["fixture"],
        "--output": str(logical_path(frozen["qualification"]["path"]).parent),
        "--runtime-profile": profile_pin["path"],
        "--runtime-profile-sha256": profile_pin["sha256"],
        **{"--" + name: path for name, path in profile_pin["tools"].items()},
    }
    require(
        len(flags) * 2 == len(argv[3:])
        and set(flags) == set(wanted) | {"--known-fix"}
        and all(flags.get(key) == value for key, value in wanted.items()),
        "qualification argv differs from frozen runtime or source",
    )
    return runtime


def exact_inventory(root, expected):
    root = Path(root)
    require(
        not root.is_symlink() and root.is_dir(), "regular retained directory required"
    )
    files = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "retained inventory contains a symlink")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
        else:
            require(path.is_dir(), "retained inventory contains a special file")
    require(set(files) == set(expected), "retained inventory file set differs")
    for name, pin in expected.items():
        relative_path(name)
        valid_identity(pin)
        require(
            raw_identity(read_raw(files[name], pin["bytes"])) == pin,
            "retained inventory bytes differ: " + name,
        )


def apply_model_edits(text, current, allowed):
    require(
        isinstance(text, str) and 0 < len(text.encode()) <= 131072,
        "bounded generated edit JSON required",
    )
    require(set(current) == set(allowed), "closed candidate source map required")
    for name in allowed:
        relative_path(name)
    value = json.loads(text, object_pairs_hook=unique)
    require(
        isinstance(value, dict)
        and set(value) == {"schema", "edits"}
        and value["schema"] == "hepta.memory-cell.code-edits.v1"
        and isinstance(value["edits"], list)
        and 1 <= len(value["edits"]) <= 8,
        "closed generated edit schema required",
    )
    proposed = dict(current)
    for edit in value["edits"]:
        require(
            isinstance(edit, dict) and set(edit) == {"path", "old", "new"},
            "closed generated edit fields required",
        )
        name, old, new = edit["path"], edit["old"], edit["new"]
        require(
            name in allowed and isinstance(new, str) and "\0" not in new,
            "out-of-scope generated edit",
        )
        if old is None:
            require(proposed[name] is None, "create requires an absent admitted file")
            proposed[name] = new
        else:
            require(
                isinstance(old, str)
                and bool(old)
                and proposed[name] is not None
                and proposed[name].count(old) == 1,
                "generated old span must match exactly once",
            )
            proposed[name] = proposed[name].replace(old, new, 1)
        require(len(proposed[name].encode()) <= 65536, "candidate file exceeds 64 KiB")
    require(proposed != current, "proposal made no change")
    return proposed


def verify_gate(
    gate_root, candidate_path, task, arm, number, frozen, expected, runtime
):
    gate_root, candidate_path = Path(gate_root), Path(candidate_path)
    require(
        type(number) is int and number > 0, "positive actual attempt number required"
    )
    spec = expected["contracts"][task]
    raw = read_raw(candidate_path, spec["limits"]["candidate_bytes"])
    require(
        read_raw(gate_root / "candidate.raw", spec["limits"]["candidate_bytes"]) == raw,
        "gate candidate bytes differ from model candidate",
    )
    candidate = json.loads(raw, object_pairs_hook=unique)
    require(
        isinstance(candidate, dict)
        and set(candidate) == {"schema", "files"}
        and candidate["schema"] == "hepta.memory-cell.implementation-candidate.v1"
        and isinstance(candidate["files"], list),
        "closed implementation candidate required",
    )
    allowed = [spec["target"]] if task == "ruff" else spec["allowed_paths"]
    require(
        0 < len(candidate["files"]) <= len(allowed), "bounded changed file set required"
    )
    changed, seen = {}, set()
    for item in candidate["files"]:
        require(
            isinstance(item, dict) and set(item) == {"path", "content"},
            "closed candidate file required",
        )
        name, content = item["path"], item["content"]
        relative_path(name)
        require(
            name in allowed
            and name not in seen
            and isinstance(content, str)
            and "\0" not in content
            and len(content.encode()) <= spec["limits"]["content_bytes"],
            "candidate file differs from original admitted scope",
        )
        seen.add(name)
        changed[name] = raw_identity(content.encode())
    fixture_pin = spec["files"]
    workspace_pin = dict(fixture_pin)
    workspace_pin.update(changed)
    task_root = logical_path(frozen["input"]["path"]).parent
    run_root = task_root.parent.parent
    original_gate = (
        run_root
        / "trajectories"
        / (task + "-" + arm)
        / (f"attempt-{number:02d}")
        / "gate"
    )
    sources = evaluation_sources(expected)
    source_root = logical_path(expected["source_root"]) / EVALUATION
    request = json.loads(read_raw(gate_root / "request.json"), object_pairs_hook=unique)
    require(
        request["fixture"] == frozen["fixture"]
        and request["candidate"] == str(original_gate.parent / "candidate.json")
        and request["contract_sha256"] == expected["contract_hashes"][task]
        and request["runtime"] == runtime
        and request["executor_sources" if task == "ruff" else "source_code"] == sources,
        "gate request differs from candidate, runtime, contract or source",
    )
    inventories = {
        str(source_root): sources,
        frozen["fixture"]: fixture_pin,
    }
    if task == "ruff":
        judge_pin = {}
        for name, pin in fixture_pin.items():
            basename = PurePosixPath(name).name
            if basename.startswith("test_"):
                require(basename not in judge_pin, "ambiguous original judge basename")
                judge_pin[basename] = pin
        roots = {
            "baseline": fixture_pin,
            "workspace": workspace_pin,
            "judge": judge_pin,
        }
    else:
        roots = {profile + "/workspace": workspace_pin for profile in spec["profiles"]}
    for name, pin in roots.items():
        inventories[str(original_gate / name)] = pin
        exact_inventory(gate_root / name, pin)
    observed = json.loads(
        read_raw(gate_root / "observed-inventories.json"), object_pairs_hook=unique
    )
    require(
        observed == inventories, "gate observed inventories differ from derived source"
    )
    if task == "ruff":
        declared = json.loads(
            read_raw(gate_root / "expected-inventories.json"), object_pairs_hook=unique
        )
        require(
            declared == inventories,
            "gate expected inventories differ from independently derived source",
        )
    return True


def retained_identity(path):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), "regular retained file required")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
            count += len(chunk)
    return {"bytes": count, "sha256": digest.hexdigest()}


def verify_format(evidence, expected):
    evidence = Path(evidence)
    argv = expected["format_argv"]
    require(
        isinstance(argv, list)
        and argv
        and all(isinstance(value, str) and "\0" not in value for value in argv),
        "independent formatter argv required",
    )
    receipt = json.loads(
        read_raw(evidence / "final-format-result.json"), object_pairs_hook=unique
    )
    require(
        isinstance(receipt, dict)
        and set(receipt)
        == {"schema", "argv", "command_returncode", "log_returncode", "log"}
        and receipt["schema"] == "hepta.memory-cell.final-format.v1"
        and receipt["argv"] == argv
        and type(receipt["command_returncode"]) is int
        and receipt["command_returncode"] == 0
        and type(receipt["log_returncode"]) is int
        and receipt["log_returncode"] == 0,
        "explicit formatter or log pipeline did not succeed",
    )
    pin = valid_identity(receipt["log"])
    require(
        retained_identity(evidence / "final-format.log") == pin,
        "formatter receipt differs from retained log",
    )
    return True
