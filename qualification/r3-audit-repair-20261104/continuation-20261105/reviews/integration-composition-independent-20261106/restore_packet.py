#!/usr/bin/env python3
"""Restore exact frozen review bytes and verify the separate publication facts."""
import argparse
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def check(data, row):
    assert identity(data) == {key: row[key] for key in ("bytes", "git_blob", "sha256")}


def restore(packet, output):
    assert not output.exists(), "Restore output must be new"
    manifest = json.loads((packet / "manifest.json").read_bytes())
    pieces = []
    for row in manifest["parts"]:
        assert PurePosixPath(row["path"]).name == row["path"]
        data = (packet / row["path"]).read_bytes()
        check(data, row)
        assert len(data) <= 400000
        pieces.append(base64.b64decode(data, validate=True))
    raw = b"".join(pieces)
    check(raw, manifest["archive"])
    members = {row["path"]: row for row in manifest["members"]}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert len(z.infolist()) == len(members) == 22 and set(z.namelist()) == set(members)
        for item in z.infolist():
            name = PurePosixPath(item.filename)
            assert not name.is_absolute() and all(p not in ("", ".", "..") for p in name.parts)
            assert not item.is_dir() and item.external_attr >> 16 == 0o100644
            data = z.read(item)
            check(data, members[item.filename])
            dest = output.joinpath(*name.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    frozen = output / "frozen-review"
    check((frozen / "freeze-manifest.json").read_bytes(), manifest["prior_freeze"])
    check((frozen / "REVIEW.zh-CN.md").read_bytes(), manifest["prior_review"])
    freeze = json.loads((frozen / "freeze-manifest.json").read_bytes())
    assert len(freeze["files"]) == freeze["members"] == 14
    for row in freeze["files"]:
        check((frozen / row["path"]).read_bytes(), row)
    pub = output / "post-publication"
    addendum = json.loads((pub / "ADDENDUM.json").read_bytes())
    check((pub / "ADDENDUM.json").read_bytes(), manifest["separate_addendum"])
    for row in addendum["raw_inputs"]:
        check((pub / row["path"]).read_bytes(), row)

    def get(name):
        result = json.loads((pub / name).read_bytes())
        assert result["isError"] is False
        return json.loads(result["structuredContent"]["content"])

    head, merge, pr = get("head.fresh-GET.original.json"), get("merge.fresh-GET.original.json"), get("pr4936.fresh-GET.original.json")
    for actual, row in ((head, addendum["observed_head"]), (merge, addendum["observed_PR_merge"])):
        assert actual["sha"] == row["sha"] and actual["tree"]["sha"] == row["tree"]
        assert [p["sha"] for p in actual["parents"]] == row["ordered_parents"]
    assert len(head["parents"]) == 5 and head["tree"]["sha"] == merge["tree"]["sha"] == "99a9c0cefa627290c9fc72a9ba90d0485020fe11"
    assert pr["number"] == 4936 and pr["draft"] is True and pr["head"]["sha"] == head["sha"]
    assert pr["merge_commit_sha"] == merge["sha"] and pr["base"]["sha"] == merge["parents"][0]["sha"]
    assert get("target-ref.fresh-GET.original.json")["object"]["sha"] == pr["base"]["sha"]
    assert get("main-ref.fresh-GET.original.json")["object"]["sha"] == "732e934ba496d90fbe042b8d41d479ef901643e5"
    assert pr["changed_files"] == 1561 and get("primary-pr4797.root-original.json")["changed_files"] == 1335
    assert addendum["distinct_change_denominators"]["reviewed_product_delta_relative_to_first_parent67"] == 230
    return {"schema": "integration-composition-independent-packet-restoration-v1", "archive": manifest["archive"],
            "members": len(members), "original_review_14_plus_freeze_byte_equal": True,
            "separate_publication_addendum_and_six_API_originals_byte_equal": True,
            "actual_head_and_merge_trees_equal_reviewed_99a9": True, "actual_five_parent_order_matches_plan": True,
            "change_denominators": {"first_parent_commit_delta": 230, "PR4936_overall": 1561, "primary4797_record": 1335},
            "product_native_CI_or_ref_mutation": False,
            "original_full_composition_verifier_not_reexecuted_by_this_restorer": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.packet.resolve(), args.output.resolve()), indent=2))
