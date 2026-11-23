"""Save the exact local engineering originals of two fictional decisions."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

from cell_experiments import data
from cell_experiments.test_paired_consumer import LocalUseTests, put


def main(out):
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    case = LocalUseTests()
    case.setUp()
    try:
        launch = ("fixture-pid", "unused", case.route)
        records = []
        for decision, prompt in (("accepted", "train later"), ("rejected", "later later")):
            task = {"input": prompt}
            task_sha = data.digest(task)
            put(case.inbox / f"consumer-task-{task_sha}.json", task)
            request = case.local("request-scope", task_sha)
            delivery = data.digest(["fixture later request", decision])
            case.event(request, delivery)
            shutil.copyfile(case.route, out / f"{decision}-request-fixture-event.json")
            run = case.local("run", task_sha, delivery, *launch)
            request_check = case.local("verify-request", task_sha, *launch)
            evidence = ("Fictional downstream decision " + decision).encode()
            effect = hashlib.sha256(evidence).hexdigest()
            (case.inbox / f"consumer-effect-{effect}.bin").write_bytes(evidence)
            report = case.local("outcome-scope", task_sha, effect, decision)
            report_delivery = data.digest(["fixture outcome report", decision])
            case.event(report, report_delivery)
            shutil.copyfile(case.route, out / f"{decision}-report-fixture-event.json")
            recorded = case.local("report", task_sha, effect, decision, report_delivery, *launch)
            checked = case.local("verify", task_sha, *launch)
            assert recorded == checked and request_check["run_receipt"] == run["run_receipt"]
            records.append(dict(run=run, checked_request=request_check, checked_outcome=checked))
        shutil.copytree(case.root, out / "original")
        summary = dict(schema="hepta.paired-consumer.engineering-observations.v1",
                       real_participants=0, enrolled_real_pairs=0, remote_execution_proofs=0,
                       external_effects_verified=0, payments=0, decisions=records)
        put(out / "SUMMARY.json", summary)
    finally:
        case.doCleanups()
    archive = out.parent / "CONSUMER_ENGINEERING_ORIGINALS.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(out))
    print(hashlib.sha256(archive.read_bytes()).hexdigest(), archive.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
