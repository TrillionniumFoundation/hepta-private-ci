"""Source-owner adapter for committing enrollment events from its original intake stream."""

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from . import data, paired_intake


def observe(
    inbox,
    study,
    freeze,
    sequence,
    *,
    arrival=None,
    record=None,
    delivery=None,
    principal=None,
    source_retention=None,
):
    """Called by the registered source owner with the sequence from its durable original event."""
    root = inbox.lstat()
    paired_intake.require(
        inbox.is_dir()
        and not inbox.is_symlink()
        and root.st_uid == os.geteuid()
        and root.st_mode & 0o022 == 0,
        "only the original inbox owner can append",
    )
    paired_intake.require(
        type(sequence) is int and 0 < sequence < 2**63, "invalid source sequence"
    )
    event = dict(
        study_sha256=paired_intake.digest_field(study),
        freeze_sha256=paired_intake.digest_field(freeze),
        sequence=sequence,
    )
    if arrival is None:
        paired_intake.require(
            record is None and delivery is None and principal is None,
            "unexpected arrival fields",
        )
        name = "freeze"
        event["schema"] = "hepta.paired-intake.freeze-observation.v1"
        if source_retention is not None:
            from . import paired_source_dispatch

            event["source_retention_sha256"] = paired_source_dispatch.verify_originals(
                Path(source_retention), study, freeze
            )
    else:
        paired_intake.require(
            source_retention is None,
            "the source retention belongs to the freeze observation",
        )
        name = paired_intake.digest_field(arrival)
        original = inbox / "freeze.json"
        paired_intake.require(
            original.is_file() and not original.is_symlink(),
            "original freeze observation required",
        )
        anchor = json.loads(original.read_bytes())
        paired_intake.require(
            anchor["schema"] == "hepta.paired-intake.freeze-observation.v1"
            and anchor["study_sha256"] == study
            and anchor["freeze_sha256"] == freeze
            and sequence > anchor["sequence"],
            "arrival must follow this study freeze",
        )
        event.update(
            schema="hepta.paired-intake.first-observation.v1",
            arrival_id=name,
            record_sha256=paired_intake.digest_field(record),
            consent_delivery_id=paired_intake.digest_field(delivery),
            study_principal_sha256=paired_intake.digest_field(principal),
        )
    target = inbox / (name + ".json")
    raw = data.canonical(event)
    with TemporaryDirectory(dir=inbox) as temp:
        staged = Path(temp) / "event"
        with staged.open("xb") as f:
            os.fchmod(f.fileno(), 0o640)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(staged, target)
        except FileExistsError:
            paired_intake.require(
                not target.is_symlink() and target.read_bytes() == raw,
                "original event already exists with different contents",
            )
        paired_intake.sync_dir(inbox)
    return data.digest(event)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inbox", type=Path)
    p.add_argument("study")
    p.add_argument("freeze")
    p.add_argument("sequence", type=int)
    commands = p.add_subparsers(dest="op", required=True)
    freezer = commands.add_parser("freeze")
    freezer.add_argument(
        "--source-retention",
        type=Path,
        help="verify original source retention and bind its digest before task arrival",
    )
    b = commands.add_parser("arrival")
    for label in ("arrival", "record", "delivery", "principal"):
        b.add_argument(label)
    a = p.parse_args()
    fields = (
        {key: getattr(a, key) for key in ("arrival", "record", "delivery", "principal")}
        if a.op == "arrival"
        else {"source_retention": a.source_retention}
    )
    print(observe(a.inbox, a.study, a.freeze, a.sequence, **fields))


if __name__ == "__main__":
    main()
