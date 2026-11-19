"""Observed compiler outcomes for a controlled multi-source memory diagnostic.

Programs and questions are authored controls, not production build history or
independent human observations. Only bounded, locally generated Rust is compiled;
no model output is ever executed. No signing, serving, or learning owner changes.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from native import Document, digest

SCHEMA = "hepta.observed-procedure-corpus.v1"
DOMAINS = {"transport": ("tcp", "udp"), "format": ("json", "cbor")}
RECIPES = ("cedar", "lumen", "vireo", "solis")
MAX_FILE = 262144


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os

        os.fsync(stream.fileno())
    return sha(raw)


def code(required):
    if not required or any(k not in DOMAINS or v not in DOMAINS[k] for k, v in required.items()):
        raise ValueError("only registered compiler constraints")
    return "\n".join(
        f'#[cfg(not({key} = "{value}"))]\ncompile_error!("{key} constraint failed");'
        for key, value in sorted(required.items())
    ) + "\npub fn probe() -> u8 { 1 }\n"


def invoke(root, compiler, identity, source, flags):
    """A fixed compiler command; timeout reaps the child and retains a failure."""
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", identity):
        raise ValueError("bounded invocation identity")
    if len(source.encode()) > 8192 or any(k not in DOMAINS or v not in DOMAINS[k] for k, v in flags.items()):
        raise ValueError("unregistered compiler input")
    folder = root / identity
    folder.mkdir()
    (folder / "source.rs").write_text(source, encoding="utf-8")
    argv = [compiler, "--edition=2021", "--crate-type=lib", "--crate-name=memory_probe", "--emit=metadata", "source.rs", "-o", "output.rmeta"]
    for key, value in sorted(flags.items()):
        argv.extend(["--cfg", f'{key}="{value}"'])
    started = time.time_ns()
    with (folder / "stdout.txt").open("xb") as stdout, (folder / "stderr.txt").open("xb") as stderr:
        try:
            result = subprocess.run(argv, cwd=folder, stdout=stdout, stderr=stderr, timeout=20, check=False)
            status, returncode = "completed", result.returncode
        except subprocess.TimeoutExpired:
            status, returncode = "timeout", None
    files = {}
    for name in ("source.rs", "stdout.txt", "stderr.txt"):
        path = folder / name
        if path.stat().st_size > MAX_FILE:
            raise ValueError("compiler diagnostic byte budget")
        files[name] = sha(path.read_bytes())
    record = dict(identity=identity, command=argv, flags=flags, source=source,
                  started_unix_ns=started, ended_unix_ns=time.time_ns(),
                  observed_at=utc_now(), status=status, returncode=returncode, files=files)
    save(folder / "result.json", record)
    if status != "completed" or returncode not in (0, 1):
        raise ValueError("compiler execution failed; retained result is not an outcome label")
    return record


def checked_outcomes(records, recipe, revision):
    """Check a complete two-factor experiment, not a hard-coded expected answer."""
    expected = {(kind, tuple(sorted(flags.items()))) for kind in (*DOMAINS, "joint")
                for flags in ([{kind: value} for value in DOMAINS[kind]] if kind in DOMAINS else
                              [dict(zip(DOMAINS, values)) for values in itertools.product(*DOMAINS.values())])}
    observed = {}
    for row in records:
        if row.get("recipe") != recipe or row.get("revision") != revision:
            raise ValueError("compiler record from another task/revision")
        key = (row["kind"], tuple(sorted(row["flags"].items())))
        if key not in expected or key in observed or row["status"] != "completed" or type(row["returncode"]) is not int or row["returncode"] not in (0, 1):
            raise ValueError("incomplete, repeated, or failed compiler experiment")
        observed[key] = row["returncode"] == 0
    if set(observed) != expected:
        raise ValueError("missing compiler outcome cannot become failure")
    passing = {}
    for kind in DOMAINS:
        values = [v for v in DOMAINS[kind] if observed[(kind, ((kind, v),))]]
        if len(values) != 1:
            raise ValueError("component requires a unique observed passing value")
        passing[kind] = values[0]
    for values in itertools.product(*DOMAINS.values()):
        flags = dict(zip(DOMAINS, values))
        if observed[("joint", tuple(sorted(flags.items())))] != (flags == passing):
            raise ValueError("independent components do not explain joint compilation")
    return passing


def projected_documents(recipe, revision, records):
    """Natural-language view of exact component exit codes, not model-written facts."""
    result = []
    for kind in DOMAINS:
        relevant = [r for r in records if r["kind"] == kind]
        content = f"Compiler observations for recipe {recipe}, revision {revision}. "
        content += " ".join(
            f"{kind}={r['flags'][kind]}: compilation "
            f"{'passed' if r['returncode'] == 0 else 'failed'} (exit {r['returncode']})."
            for r in relevant
        )
        result.append(Document(
            f"{recipe}/{revision}/{kind}", f"compiler:{recipe}:{revision}",
            f"compiler:{recipe}", revision,
            max(r["observed_at"] for r in relevant), content,
        ))
    return tuple(result)


def capture(output, *, count=4, compiler="rustc"):
    if type(count) is not int or not 1 <= count <= len(RECIPES):
        raise ValueError("registered bounded controlled task count")
    executable = shutil.which(compiler)
    if executable is None:
        raise ValueError("rustc is required for observed outcomes, not a test substitute")
    version = subprocess.run([executable, "--version", "--verbose"], capture_output=True, timeout=10, check=True)
    if len(version.stdout) > 16384 or not version.stdout.startswith(b"rustc "):
        raise ValueError("expected actual Rust compiler identity")
    output.mkdir()
    (output / "compiler.txt").write_bytes(version.stdout)
    observations = output / "observations"
    observations.mkdir()
    save(output / "protocol.json", dict(
        source_kind="authored-programs-observed-compiler", count=count,
        recipe_order=RECIPES[:count], domains=DOMAINS, revisions=["A", "B"],
        compiler_sha256=sha(version.stdout), compiler_invocations_per_case=16,
        producer_source_sha256=sha(Path(__file__).read_bytes()),
        model_outputs_are_never_commands=True, production_accepted=False,
    ))
    started = time.time_ns()
    cases, all_records = [], []
    for number, recipe in enumerate(RECIPES[:count]):
        documents, revisions = [], {}
        for revision in ("A", "B"):
            required = {k: values[((number >> i) & 1) ^ (revision == "A")] for i, (k, values) in enumerate(DOMAINS.items())}
            records = []
            for kind in (*DOMAINS, "joint"):
                combinations = ([{kind: v} for v in DOMAINS[kind]] if kind in DOMAINS else
                                [dict(zip(DOMAINS, values)) for values in itertools.product(*DOMAINS.values())])
                for index, flags in enumerate(combinations):
                    identity = f"{recipe}-{revision.lower()}-{kind}-{index}"
                    row = invoke(observations, executable, identity, code(required if kind == "joint" else {kind: required[kind]}), flags)
                    row.update(recipe=recipe, revision=revision, kind=kind)
                    records.append(row)
            passing = checked_outcomes(records, recipe, revision)
            revisions[revision] = dict(records=records, passing=passing)
            documents.extend(projected_documents(recipe, revision, records))
            all_records.extend(records)
        # Persist actual experience before constructing any question in planning.
        cases.append(dict(recipe=recipe, documents=[asdict(d) for d in documents],
                          through=utc_now(), revisions=revisions))
    corpus = dict(schema=SCHEMA, cases=cases, compiler_sha256=sha(version.stdout),
                  compiler_invocations=len(all_records), started_unix_ns=started,
                  completed_unix_ns=time.time_ns(), authored_programs=True,
                  actual_compiler_outcomes=True, independent_observations=False,
                  production_accepted=False)
    corpus_sha = save(output / "corpus.json", corpus)
    files = {str(p.relative_to(output)): sha(p.read_bytes()) for p in sorted(output.rglob("*")) if p.is_file()}
    save(output / "READY.json", dict(corpus_sha256=corpus_sha, files=files, production_accepted=False))
    return corpus


def load_observations(root, *, expected_corpus_sha):
    from reviewed_bundle import strict_read

    value = strict_read(root / "corpus.json", expected_corpus_sha, 16 * 1024 * 1024)
    if value["schema"] != SCHEMA or not 1 <= len(value["cases"]) <= 4 or len({c["recipe"] for c in value["cases"]}) != len(value["cases"]):
        raise ValueError("unknown observed corpus")
    if sha((root / "compiler.txt").read_bytes()) != value["compiler_sha256"]:
        raise ValueError("compiler identity drift")
    if type(value["compiler_invocations"]) is not int or value["compiler_invocations"] != len(value["cases"]) * 16:
        raise ValueError("compiler work count drift")
    for case in value["cases"]:
        projected = []
        if set(case["revisions"]) != {"A", "B"}:
            raise ValueError("missing task revision")
        for revision, group in case["revisions"].items():
            if checked_outcomes(group["records"], case["recipe"], revision) != group["passing"]:
                raise ValueError("reported outcomes drifted")
            projected.extend(projected_documents(case["recipe"], revision, group["records"]))
            for record in group["records"]:
                required = group["passing"] if record["kind"] == "joint" else {record["kind"]: group["passing"][record["kind"]]}
                if record["source"] != code(required) or set(record["files"]) != {"source.rs", "stdout.txt", "stderr.txt"}:
                    raise ValueError("unexpected program or incomplete evidence files")
                if not re.fullmatch(r"[a-z0-9_-]{1,80}", record["identity"]):
                    raise ValueError("unsafe recorded path")
                folder = root / "observations" / record["identity"]
                for name, expected in record["files"].items():
                    if name not in ("source.rs", "stdout.txt", "stderr.txt"):
                        raise ValueError("unknown record file")
                    strict_read_bytes = folder / name
                    if any(p.is_symlink() for p in (strict_read_bytes, *strict_read_bytes.parents)) or strict_read_bytes.stat().st_size > MAX_FILE or sha(strict_read_bytes.read_bytes()) != expected:
                        raise ValueError("observed input/output changed")
                if sha(record["source"].encode()) != record["files"]["source.rs"]:
                    raise ValueError("source is not the executed program")
                stored = json.loads((folder / "result.json").read_text())
                if stored != {k: v for k, v in record.items() if k not in ("recipe", "revision", "kind")}:
                    raise ValueError("completed process result detached from corpus")
        if digest([asdict(d) for d in projected]) != digest(case["documents"]):
            raise ValueError("source projection does not reproduce compiler observations")
    return value
