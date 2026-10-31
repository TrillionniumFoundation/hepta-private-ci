"""Reproducible synthetic transport checks; never opens scientific outcomes."""

import argparse
import copy
import hashlib
import io
import json
import lzma
from pathlib import Path
import random
import shutil
import tarfile
import tempfile
import time

from experiments.hcsn_blocker_closure_v1.audits import selective_restore as helper
from experiments.hcsn_free_boundary_v1 import archive as frozen


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()


def index_manifest(directory, manifest):
    descriptor = {key:value for key,value in manifest.items() if key != "members"}
    descriptor.update(schema="hcsn-bounded-member-index.v1",
        original_manifest_sha256=hashlib.sha256(encoded(manifest)).hexdigest(),
        original_member_count=len(manifest["members"]), member_shards=[])
    for start in range(0, len(manifest["members"]), 2):
        rows = manifest["members"][start:start+2]
        path = directory/f"members_{start//2:04d}.json"
        path.write_bytes(encoded(rows))
        descriptor["member_shards"].append(dict(path=path.name, bytes=path.stat().st_size,
            sha256=helper.sha(path), members=len(rows)))
    index = directory/"INDEX.json"
    index.write_bytes(encoded(descriptor))
    return index, helper.sha(index)


def custom_publication(directory, records, expected, raw_transform=lambda raw:raw,
                       compressed_transform=lambda raw:raw):
    """Build self-consistently hashed malformed archives to test the inner checks."""
    directory.mkdir()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data, kind in records:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(data) if kind in (tarfile.REGTYPE, tarfile.AREGTYPE) else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = "a.txt"
            archive.addfile(info, io.BytesIO(data) if info.size else None)
    payload = compressed_transform(lzma.compress(raw_transform(stream.getvalue())))
    parts = []
    for offset in range(0, len(payload), 4096):
        path = directory/f"synthetic.tar.xz.part{offset//4096:04d}"
        block = payload[offset:offset+4096]
        path.write_bytes(block)
        parts.append(dict(path=path.name, bytes=len(block), sha256=helper.sha(path)))
    manifest = dict(schema="hcsn-evidence-bundle.v1", name="synthetic",
        format="deterministic POSIX tar, xz, concatenated parts in declared order",
        archive_sha256=hashlib.sha256(payload).hexdigest(), parts=parts,
        members=expected, compressed_bytes=len(payload),
        uncompressed_file_bytes=sum(row["bytes"] for row in expected))
    return index_manifest(directory, manifest)


def row(name, data):
    return dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def run(output):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    checks, receipts = [], []
    cpu, wall = time.process_time(), time.perf_counter()
    source_hashes = {name:helper.sha(Path(module.__file__)) for name,module in
        (("selective_restore.py",helper),("frozen_archive.py",frozen))}
    source_hashes["selective_restore_preflight.py"] = helper.sha(Path(__file__))

    def check(name, passed, details=None):
        checks.append(dict(name=name, passed=bool(passed), details=details))

    with tempfile.TemporaryDirectory(prefix="hcsn-selective-synthetic-") as temporary:
        root = Path(temporary)
        source, publication = root/"source", root/"publication"
        source.mkdir()
        generator = random.Random(302671)
        long_name = "long/"+"z"*120+".bin"
        payloads = {"a.txt":b"synthetic selected payload\n", "nested/one.bin":generator.randbytes(45000),
            "nested/two.bin":generator.randbytes(30000), "ignored.npz":b"SYNTHETIC ONLY: no model outcomes",
            long_name:generator.randbytes(2048), "empty.bin":b""}
        for name,data in payloads.items():
            target = source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest = frozen.pack(source, publication, "synthetic", part_bytes=4096)
        index, pinned = index_manifest(publication, manifest)

        def attempt(name, case_index=index, pin=pinned, names=("a.txt",), patterns=(), destination=None):
            destination = destination or root/("restored_"+name)
            receipt_path = output/(name+".json")
            try:
                result = helper.restore_selected(case_index,pin,case_index.parent,destination,
                    receipt_path,names,patterns,reserve_bytes=0)
            except Exception as error:
                result = dict(passed=False,error=dict(type=type(error).__name__,message=str(error)),
                    precondition_exception=True)
                helper.write_new(receipt_path,result)
            receipts.append(dict(path=receipt_path.name,sha256=helper.sha(receipt_path)))
            return result,destination

        result,destination = attempt("partial_union",names=("a.txt",long_name,"empty.bin"),patterns=("nested/one.*",))
        chosen = {"a.txt",long_name,"empty.bin","nested/one.bin"}
        actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        check("partial union restores exact requested files",result["passed"] and actual==chosen
            and all((destination/name).read_bytes()==payloads[name] for name in chosen))
        check("all selected and unselected members verified",result.get("all_members_verified")
            and result.get("member_files_verified")==len(payloads)
            and result.get("member_bytes_verified")==sum(map(len,payloads.values()))
            and result.get("part_files_verified")==len(manifest["parts"]))
        check("selective status and exact restored byte count",not result.get("full_restoration_claim")
            and not result.get("all_members_selected") and result.get("restored_bytes")==sum(len(payloads[k]) for k in chosen))
        shards = [entry for descriptor in result.get("selection_shards",[])
            for entry in json.loads((output/descriptor["path"]).read_bytes())]
        check("selection manifest records actual committed hashes",{entry["path"] for entry in shards}==chosen
            and all(entry["sha256"]==hashlib.sha256(payloads[entry["path"]]).hexdigest()
                and entry["disposition"]=="restored_after_complete_verification" for entry in shards))
        again,_ = attempt("identical_reuse",names=tuple(chosen),destination=destination)
        check("existing identical selection reused without payload copies",again["passed"]
            and again["restored_files"]==0 and again["staged_payload_bytes"]==0
            and again["existing_identical_files"]==len(chosen))

        result,_ = attempt("wrong_external_pin",pin="0"*64)
        check("wrong external INDEX pin rejected",not result["passed"] and result.get("member_files_verified",0)==0)
        result,_ = attempt("unmatched_pattern",patterns=("absent/*.bin",))
        check("unmatched explicit selection rejected",not result["passed"])
        mismatch = root/"different_existing"
        mismatch.mkdir(); (mismatch/"a.txt").write_bytes(b"preserve this existing content")
        result,_ = attempt("different_existing",destination=mismatch)
        check("different existing file refused and preserved",not result["passed"]
            and (mismatch/"a.txt").read_bytes()==b"preserve this existing content")
        for label,target_name in (("shard_corruption","members_0000.json"),
                                  ("part_corruption",manifest["parts"][0]["path"])):
            corrupted = root/label
            shutil.copytree(publication,corrupted)
            target = corrupted/target_name
            data = bytearray(target.read_bytes());data[len(data)//2]^=1;target.write_bytes(data)
            result,_ = attempt(label,case_index=corrupted/"INDEX.json")
            check(label+" rejected before any restored payload",not result["passed"]
                and result.get("restored_bytes",0)==0)

        regular = [("a.txt",b"a",tarfile.REGTYPE),("unselected.txt",b"u",tarfile.REGTYPE)]
        expected = [row("a.txt",b"a"),row("unselected.txt",b"u")]
        cases = []
        bad_hash = copy.deepcopy(expected);bad_hash[1]["sha256"]="0"*64
        cases.append(("unselected_wrong_member_hash",regular,bad_hash,{}))
        cases.append(("duplicate_member",regular+[regular[0]],expected,{}))
        cases.append(("unexpected_member",regular+[("extra",b"x",tarfile.REGTYPE)],expected,{}))
        cases.append(("path_traversal",regular+[("../escape",b"x",tarfile.REGTYPE)],expected,{}))
        for label,kind in (("symlink",tarfile.SYMTYPE),("hardlink",tarfile.LNKTYPE),("directory",tarfile.DIRTYPE)):
            cases.append((label,regular+[("unsafe",b"",kind)],expected,{}))
        cases.append(("truncated_tar_payload",regular,expected,dict(raw_transform=lambda raw:raw[:1536])))
        cases.append(("missing_tar_end_markers",regular,expected,dict(raw_transform=lambda raw:raw[:2048])))
        cases.append(("truncated_xz_footer",regular,expected,dict(compressed_transform=lambda raw:raw[:-8])))
        cases.append(("trailing_tar_garbage",regular,expected,dict(raw_transform=lambda raw:raw[:3072]+b"bad"+raw[3075:])))
        cases.append(("trailing_compressed_garbage",regular,expected,dict(compressed_transform=lambda raw:raw+b"bad")))
        for label,records,declared,options in cases:
            case_index,pin = custom_publication(root/label,records,declared,**options)
            result,target = attempt(label,case_index=case_index,pin=pin)
            check(label+" rejected with no final-path writes",not result["passed"]
                and not target.exists() and result.get("restored_bytes",0)==0,result.get("error"))
        alias = root/"alias"
        alias.symlink_to(destination, target_is_directory=True)
        result,_ = attempt("symlink_destination",destination=alias/"child")
        check("symlinked destination ancestor rejected",not result["passed"])
        detour = root/"detour"
        detour.mkdir()
        before = {path.name:helper.sha(path) for path in publication.iterdir() if path.is_file()}
        result,_ = attempt("parent_traversal_destination",destination=detour/".."/"publication")
        after = {path.name:helper.sha(path) for path in publication.iterdir() if path.is_file()}
        check("parent traversal cannot bypass immutable publication exclusion",not result["passed"]
            and before==after and "Parent-traversal" in result.get("error",{}).get("message",""))
        escaped_index,pin = custom_publication(root/"unsafe_declared_member",regular,
            expected+[row("../escape",b"x")])
        result,_ = attempt("unsafe_declared_member",case_index=escaped_index,pin=pin)
        check("unsafe declared member rejected before decompression",not result["passed"]
            and result.get("member_files_verified",0)==0)
    result = dict(schema="hcsn-selective-restore-synthetic-preflight.v1",passed=all(x["passed"] for x in checks),
        checks=checks,checks_passed=sum(x["passed"] for x in checks),checks_total=len(checks),
        source_sha256=source_hashes,case_receipts=receipts,science_data_opened=False,
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,
        invocation="PYTHONDONTWRITEBYTECODE=1 python3 -m experiments.hcsn_blocker_closure_v1.audits.selective_restore_preflight --output "+str(output))
    helper.write_new(output/"RESULT.json",result)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    arguments=parser.parse_args()
    result=run(arguments.output)
    print(json.dumps({key:result[key] for key in ("passed","checks_passed","checks_total","cpu_seconds","wall_seconds")}))
    if not result["passed"]:
        raise SystemExit(1)
