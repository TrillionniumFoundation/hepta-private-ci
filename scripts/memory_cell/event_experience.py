"""Collect real subprocess receipts from an AUTHORED controlled environment.

These are new observations of a small test program, not production project
history, independent human evidence, random held-out worlds or future windows.
No model-generated code/command is executed. One fixed worker is invoked with
bounded JSON and a fixed argv; its task mode is a constrained selector check.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from native import Document, Question, digest
from event_projection import PROFILE, EventProjection, Lookup

SEED = "hepta-event-organization-development-v1"
KINDS = ("new_fact", "correction", "composition", "procedure")


def write(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(
            value, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
        f.write("\n")
        f.flush()
        import os

        os.fsync(f.fileno())


def call_worker(request):
    started = time.perf_counter()
    payload = json.dumps(request, sort_keys=True)
    if len(payload.encode()) > 16384:
        raise ValueError("worker input bound")
    output = subprocess.run(
        [sys.executable, "-I", "-S", str(Path(__file__).with_name("event_probe.py"))],
        input=payload,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if len(output.stdout.encode()) + len(output.stderr.encode()) > 16384:
        raise ValueError("worker output bound")
    return dict(
        request=request,
        stdout=output.stdout,
        stderr=output.stderr,
        exit_code=output.returncode,
        seconds=time.perf_counter() - started,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


def collect(output):
    output.mkdir()
    started, docs, specs, receipts = time.perf_counter(), [], [], []
    for i in range(16):
        kind = KINDS[i % 4]
        suffix = digest((SEED, i))[:8]
        entity, component = "service_" + suffix, "component_" + suffix
        scope = "controlled_" + suffix
        rows, recipe = [], None

        def emit(subject, attribute, value, revision, supersedes=()):
            event_id = f"event_{suffix}_{len(rows)}"
            row = dict(
                schema=PROFILE,
                id=event_id,
                entity=subject,
                attribute=attribute,
                value=value,
                revision=revision,
                supersedes=list(supersedes),
            )
            observed = call_worker(dict(operation="observe", event=row))
            if observed["exit_code"] != 0 or json.loads(observed["stdout"]) != row:
                raise ValueError("actual worker observation mismatch")
            rows.append(row)
            receipts.append(observed)
            docs.append(
                Document(
                    event_id,
                    "root_" + digest(observed["stdout"])[:24],
                    scope,
                    scope,
                    observed["observed_at"],
                    observed["stdout"].strip(),
                )
            )
            return event_id

        # A shared schema, not a hand-selected hard-negative corpus. Both methods
        # receive every original source including distractors and corrections.
        emit("neighbor_" + suffix, "location", "site_" + digest((i, 0))[:8], 1)
        if kind in ("new_fact", "correction"):
            old = emit(entity, "location", "site_" + digest((i, 1))[:8], 1)
            value = (
                "site_" + digest((i, 2))[:8]
                if kind == "correction"
                else rows[-1]["value"]
            )
            support = (
                [emit(entity, "location", value, 2, (old,))]
                if kind == "correction"
                else [old]
            )
            path = ("location",)
        else:
            bridge = emit(entity, "component", component, 1)
            attribute = "successful_mode" if kind == "procedure" else "location"
            value = ("mode_" if kind == "procedure" else "site_") + digest((i, 3))[:8]
            if kind == "procedure":
                # Actually exercise a wrong and a correct invocation BEFORE using
                # the successful observation as evidence. Not just a string label.
                recipe = dict(
                    values=[4, 1, 3, 2],
                    modes={value: "sort", "mode_wrong": "reverse"},
                    target=[1, 2, 3, 4],
                )
                wrong = call_worker(
                    dict(operation="execute", recipe=recipe, supplied="mode_wrong")
                )
                passed = call_worker(
                    dict(operation="execute", recipe=recipe, supplied=value)
                )
                receipts.extend((wrong, passed))
                if wrong["exit_code"] != 2 or passed["exit_code"] != 0:
                    raise ValueError("controlled procedure probe failed")
            end = emit(component, attribute, value, 1)
            support, path = [bridge, end], ("component", attribute)
        emit(entity, "owner", "person_" + digest((i, 4))[:8], 1)
        emit("neighbor_" + suffix, "component", "component_other", 2)
        emit("component_other", "location", "site_" + digest((i, 5))[:8], 2)
        # Already observed, but not effective at the question's logical revision.
        emit(entity, path[0], "future_" + suffix, 3)
        specs.append(
            dict(
                id=scope,
                phase="calibration" if i < 8 else "test",
                kind=kind,
                entity=entity,
                path=list(path),
                revision=2,
                expected=value,
                support=support,
                procedure=recipe,
            )
        )
    for scope in {d.scope for d in docs}:
        EventProjection(tuple(d for d in docs if d.scope == scope))
    write(output / "sources.json", [asdict(d) for d in docs])
    write(output / "worker-receipts.json", receipts)
    write(output / "labels.json", specs)
    write(
        output / "questions.json",
        [
            {
                k: v
                for k, v in s.items()
                if k not in ("expected", "support", "procedure")
            }
            for s in specs
        ],
    )
    manifest = {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in (
            "sources.json",
            "worker-receipts.json",
            "labels.json",
            "questions.json",
        )
    }
    write(
        output / "collection.json",
        dict(
            profile=SEED,
            collector_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            worker_sha256=hashlib.sha256(
                Path(__file__).with_name("event_probe.py").read_bytes()
            ).hexdigest(),
            python=sys.version,
            files=manifest,
            cases=16,
            source_events=len(docs),
            subprocess_calls=len(receipts),
            extraction_seconds=time.perf_counter() - started,
            measured_worker_seconds=sum(r["seconds"] for r in receipts),
            original_source_bytes=sum(len(d.content.encode()) for d in docs),
            source_kind="authored-controlled-program-actual-process-observations",
            independent_human_review=False,
            production_accepted=False,
            future_windows=0,
        ),
    )


def question(spec, observed_at):
    lookup = Lookup(spec["entity"], tuple(spec["path"]), spec["revision"])
    lookup.validate()
    relation = (
        "the location"
        if lookup.path == ("location",)
        else "the location of the assigned component"
        if lookup.path[-1] == "location"
        else "the mode that actually succeeded for the assigned component"
    )
    query = Question(
        spec["id"],
        spec["id"],
        spec["id"],
        f"For {lookup.entity} at logical revision {lookup.revision}, what is {relation}? "
        "Reply with only the single recorded site_ or mode_ identifier followed by supporting "
        "[E1], [E2] labels, without other words. "
        "Respect explicit supersedes events; later effective revisions do not apply.",
        observed_at,
    )
    return query, lookup


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "collect":
        collect(Path(sys.argv[2]))
    else:
        raise SystemExit("usage: event_experience.py collect NEW_OUTPUT")
