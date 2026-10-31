"""Run the complete learned-document cell lifecycle without a target lookup on reads."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import resource
import select
import shutil
import signal
import subprocess
import sys
import time

from corpus import build_corpus
from document_cell import DocumentCell, Refused, field_values
from learned import canonical


def save(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def denied(checks, label, operation):
    try:
        operation()
    except Refused as error:
        checks.append(dict(check=label, passed=True, reason=str(error)))
    else:
        raise AssertionError(label + " was accepted")


def crash_child(root, artifact, mode):
    cell = DocumentCell(root)
    if mode == "before_commit":
        cell.db.execute("BEGIN IMMEDIATE")
        cell.db.execute("UPDATE releases SET artifact=?,epoch=999 WHERE cell='document-fields'", (artifact,))
    else:
        cell.publish("document-fields", artifact)
    print("ready", flush=True)
    signal.pause()


def kill(root, artifact, mode):
    child = subprocess.Popen([sys.executable, __file__, "--crash", mode, "--out", str(root),
                              "--artifact", artifact], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([child.stdout], [], [], 15)[0] or child.stdout.readline().strip() != "ready":
            raise RuntimeError("child did not reach the transaction boundary")
        child.kill()
        stdout, stderr = child.communicate(timeout=10)
        if child.returncode != -signal.SIGKILL:
            raise AssertionError("child was not killed by SIGKILL")
        return dict(mode=mode, exit_code=child.returncode, signal="SIGKILL", stdout=stdout, stderr=stderr)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


def run(repo, output):
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    package = Path(__file__).parent
    names = ("document_cell.py", "document_cell_experiment.py", "DOCUMENT_CELL_PROTOCOL.json",
             "content_experiment.py", "learned.py", "corpus.py")
    hashes = {name: hash_file(package / name) for name in names}
    frozen = output / "EXECUTED_SOURCE"
    frozen.mkdir()
    for name in names:
        shutil.copyfile(package / name, frozen / name)
    protocol = json.loads((package / "DOCUMENT_CELL_PROTOCOL.json").read_text())
    corpus = build_corpus(repo)
    selected = sorted(corpus["metadata"], key=lambda row: row["module"])
    modules = [row["module"] for row in selected[:10]]
    targets = {row["module"]: row["fields"] for row in selected[:10]}
    save(output / "PLAN.json", dict(protocol=protocol, source_hashes=hashes,
                                    corpus_sha256=corpus["corpus_sha256"], frozen_before_training=True))
    checks, predictions, receipts = [], [], []
    owner = DocumentCell(output / "cell")
    for row in selected[:11]:
        owner.put((repo / row["path"]).read_text(), dict(git_commit=corpus["source_commit"],
                                                       path=row["path"], source_sha256=row["source_id"]))
    initial = owner.fit(modules, seed=protocol["seed"], steps=protocol["steps_per_fit"])
    first = owner.stage(initial)
    assert owner.publish("document-fields", first) == 1
    receipts.append(initial["training_receipt"])
    for module in modules:
        for template in protocol["unfamiliar_queries"]:
            text = template.format(module=module)
            answer = owner.read("document-fields", text)
            assert answer["fields"] == targets[module]
            predictions.append(dict(stage="initial-unfamiliar-wording", text=text, result=answer,
                                    expected=targets[module], exact=True))
        for template in protocol["unknown_queries"]:
            denied(checks, "unknown:" + module, lambda template=template, module=module:
                   owner.read("document-fields", template.format(module=module)))
    query = protocol["unfamiliar_queries"][0].format(module=modules[0])
    baseline = owner.read("document-fields", query)
    owner.close()
    owner = DocumentCell(output / "cell")
    assert owner.read("document-fields", query) == baseline
    restored = owner.load(first)
    assert restored["checkpoint.json"]["optimizer"] == initial["checkpoint"]["optimizer"]
    checks.append(dict(check="cold-reopen-and-complete-optimizer", passed=True))
    outside = selected[10]["module"]
    old = owner.source(outside)
    owner.put(old["body"] + "\nControlled unrelated-source lifecycle test.\n",
              dict(controlled_test=True, parent_source=old["body_sha"]), expected_revision=1)
    assert owner.read("document-fields", query)["parameter_sha256"] == baseline["parameter_sha256"]
    checks.append(dict(check="unrelated-write-preserves-parameters", passed=True))
    counts = Counter(values["owner"] for values in targets.values())
    corrected_module = next(module for module in modules if counts[targets[module]["owner"]] > 1)
    changed_owner = next(value for value in sorted(counts) if value != targets[corrected_module]["owner"])
    old = owner.source(corrected_module)
    body = re.sub(r"(\*\*Owner:\*\*\s*)`[^`]+`", lambda match: match.group(1) + "`" + changed_owner + "`", old["body"], count=1)
    owner.put(body, dict(controlled_test=True, parent_source=old["body_sha"]), expected_revision=1)
    targets[corrected_module] = dict(targets[corrected_module], owner=changed_owner)
    denied(checks, "related-correction-fences-all-old-reads", lambda: owner.read("document-fields", query))
    denied(checks, "stale-candidate-cannot-publish", lambda: owner.publish("document-fields", first))
    corrected = owner.fit(modules, seed=protocol["seed"] + 1, steps=protocol["steps_per_fit"], initial=initial)
    assert corrected["continuation"]
    assert corrected["training_receipt"]["initial_parameter_sha256"] == initial["serving"]["parameter_sha256"]
    assert corrected["training_receipt"]["initial_optimizer_step"] == initial["checkpoint"]["optimizer"]["step"]
    second = owner.stage(corrected)
    receipts.append(corrected["training_receipt"])
    owner.close()
    crashes = [kill(output / "cell", second, "before_commit")]
    owner = DocumentCell(output / "cell")
    assert owner.db.execute("SELECT epoch FROM releases").fetchone()[0] == 1
    denied(checks, "crash-before-commit-does-not-release-stale-model", lambda: owner.read("document-fields", query))
    owner.close()
    crashes.append(kill(output / "cell", second, "after_commit"))
    owner = DocumentCell(output / "cell")
    for module in modules:
        for template in protocol["unfamiliar_queries"]:
            text = template.format(module=module)
            answer = owner.read("document-fields", text)
            assert answer["epoch"] == 2 and answer["fields"] == targets[module]
            predictions.append(dict(stage="corrected-after-commit-crash", text=text, result=answer,
                                    expected=targets[module], exact=True))
    checks.append(dict(check="corrected-answer-and-other-nine-addresses-survive-lost-ack", passed=True))
    clone = output / "corrupt-copy"
    owner.close()
    shutil.copytree(output / "cell", clone)
    damaged = clone / "artifacts" / second / "serving.json"
    raw = bytearray(damaged.read_bytes())
    raw[len(raw) // 2] ^= 1
    damaged.write_bytes(raw)
    bad = DocumentCell(clone)
    denied(checks, "changed-artifact-is-refused", lambda: bad.read("document-fields", query))
    bad.close()
    owner = DocumentCell(output / "cell")
    revoked = next(module for module in modules if module != modules[0] and module != corrected_module)
    row = owner.source(revoked)
    owner.put(row["body"], dict(controlled_test=True, revocation=True, parent_source=row["body_sha"]),
              expected_revision=row["revision"], active=False)
    denied(checks, "unqueried-fitted-dependency-revocation", lambda: owner.read("document-fields", query))
    denied(checks, "revoked-checkpoint-cannot-reactivate", lambda: owner.publish("document-fields", second))
    owner.close()
    assert hashes == {name: hash_file(package / name) for name in names}
    save(output / "PREDICTIONS.json", predictions)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = ((children_after.ru_utime + children_after.ru_stime) -
                 (children_before.ru_utime + children_before.ru_stime))
    save(output / "RESULTS.json", dict(source_hashes=hashes, source_stable=True, checks=checks, crashes=crashes,
                                      unfamiliar_queries=len(predictions), exact_answers=len(predictions),
                                      training=receipts, source_correction=dict(module=corrected_module, new_owner=changed_owner,
                                                                              controlled_test_not_repository_history=True),
                                      revoked_module=revoked, limits=protocol["limits"],
                                      total_wall_seconds=time.perf_counter() - wall,
                                      parent_cpu_seconds=time.process_time() - cpu,
                                      child_cpu_seconds=child_cpu,
                                      total_cpu_seconds=time.process_time() - cpu + child_cpu))
    inventory = {path.relative_to(output).as_posix(): dict(bytes=path.stat().st_size, sha256=hash_file(path))
                 for path in sorted(output.rglob("*")) if path.is_file()}
    save(output / "INVENTORY.json", dict(files=inventory, total_bytes=sum(row["bytes"] for row in inventory.values())))
    print(json.dumps(dict(unfamiliar_queries=len(predictions), exact_answers=len(predictions), checks=len(checks),
                          actual_sigkills=len(crashes), complete_evidence_bytes=sum(row["bytes"] for row in inventory.values()))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("evidence") / "document-cell")
    parser.add_argument("--crash", choices=("before_commit", "after_commit"))
    parser.add_argument("--artifact")
    args = parser.parse_args()
    if args.crash:
        crash_child(args.out, args.artifact, args.crash)
    else:
        run(args.repo, args.out)
