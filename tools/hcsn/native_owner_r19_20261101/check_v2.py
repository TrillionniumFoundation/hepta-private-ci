"""Separately frozen seventh case: death after durable allocation, before publish."""
import argparse
import hashlib
import json
from pathlib import Path

import check as original


def campaign(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Re-run all six original contracts unchanged against the new source.
    original.campaign(argparse.Namespace(binary=args.binary, baseline=args.baseline,
                                        output=output / "six_original_cases"))
    d = output / "allocated_before_publish"
    d.mkdir()
    original.job(d / "job")
    c = original.Campaign(output)
    try:
        p = c.start("provider", args.binary, "provider", d / "job", d / "provider.state", d / "mailbox")
        original.await_path(d / "mailbox/READY")
        allocator = c.start("allocator", args.binary, "allocate", d / "job", d / "unused.state",
                            d / "mailbox", "allocated_before_publish")
        original.await_path(d / "allocator.marker")
        assert original.body(d / "mailbox/client-sequence") == "1\n"
        assert list((d / "mailbox").glob("*.req")) == []
        assert list((d / "mailbox").glob("*.resp")) == []
        assert original.verify(d, count=0)["count"] == 0
        assert c.wait(allocator, kill=True) == -9
        owner = c.start("owner", args.binary, "owner", d / "job", d / "owner.state", d / "mailbox")
        assert c.wait(owner) == 0
        result = original.verify(d)
        replies = [x.split("\t")[1] for x in original.body(d / "provider.state").splitlines()
                   if x.startswith("REPLY\t")]
        assert sorted(replies) == [f"0-{i:020}" for i in range(2, 10)]
        assert original.body(d / "mailbox/client-sequence") == "9\n"
        assert list((d / "mailbox").glob("*.req")) == []
        c.wait(p, kill=True)
    finally:
        c.cleanup()
        original.save(output / "SUPPLEMENT_PROCESS_RECORDS.json", c.processes)
    six = json.loads((output / "six_original_cases/RESULT.json").read_text())
    row = dict(name="allocator_sigkill_before_publication", passed=True,
               durable_allocated_id="0-00000000000000000001", first_published_id=replies[0],
               **result)
    summary = dict(cases=six["cases"] + [row], all_passed=six["all_passed"],
                   processes=six["processes"] + len(c.processes),
                   child_cpu_seconds=six["child_cpu_seconds"] + sum(x["cpu_seconds"] for x in c.processes),
                   binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                   baseline_sha256=six["baseline_sha256"])
    original.save(output / "RESULT.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    campaign(p.parse_args())
