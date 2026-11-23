"""Verify the archived immutable Agentd qualification evidence using Python 3.10+."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "evidence.tar.gz"

def main():
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        members = tar.getmembers()
        assert all(m.isfile() for m in members)
        assert len(set(m.name for m in members)) == len(members)
        data = {m.name:tar.extractfile(m).read() for m in members}
    manifest = json.loads(data["integrity.json"])
    assert set(manifest) == set(data) - {"integrity.json"}
    for name, digest in manifest.items():
        assert hashlib.sha256(data[name]).hexdigest() == digest, name

    def doc(name):
        return json.loads(data[name])
    def text(name):
        return data[name].decode()

    q = doc("qualification.json")
    baseline, candidate = q["base_elf_sha256"], q["candidate_elf_sha256"]
    assert baseline != candidate and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in (baseline,candidate))
    for filename in ("hosted/cebd-pair.txt","hosted/a059-root.txt"):
        raw = text(filename)
        assert f"{baseline}  /home/runner/work/_temp/agentd-private-base" in raw
        assert f"{candidate}  /home/runner/work/_temp/agentd-private-candidate" in raw
    ordinary = text("hosted/cebd-pair.txt")
    ids = re.findall(r"^test (\S+) \.\.\. ok$", ordinary, re.M)
    assert len(ids) == 18 and ids[:9] == ids[9:] and len(set(ids)) == 9
    assert sum("deferred_training_" in n for n in set(ids)) == 8
    assert ordinary.count("9 passed; 0 failed; 1 ignored;") == 2
    assert ordinary.count("ignored, actual UID0 and Root-owned original directory required") == 2
    paid = text("hosted/a059-root.txt")
    root_name = "root_publication_grant_retains_actual_signature_and_reopen_never_issues"
    assert len(re.findall(re.escape(root_name) + r" \.\.\. ok$", paid, re.M)) == 2
    assert paid.count('"actual_uid": 0') == paid.count("1 passed; 0 failed; 0 ignored;") == 2

    partial = text("hosted/5cb-failed-tests.txt")
    assert "grant_store_tests.rs:139" in partial and "candidate_tests.rs:258" in partial
    assert partial.count("error[E0308]") >= 2
    strict = doc("hosted/5cb-strict-pair.json")
    assert [strict["before"],strict["after"]] == [138,128] and strict["new"] == []
    assert len(strict["resolved"]) == 10 and sum(s[1] == "large size difference between variants" for s in strict["resolved"]) == 7
    result = doc("remaining-128.json"); rows = result["rows"]
    assert len(rows) == 128 and len({r["path"] for r in rows}) == 99
    assert sum(r["donor_file_changed"] for r in rows) == 127
    count = Counter((r["path"],r["diagnostic"]) for r in rows)
    repeated = doc("hosted/cebd-strict.json")
    assert repeated["source"] == q["candidate_with_six_protected_records"]
    assert count == Counter((p.removeprefix("hepta-agentd/"), d) for p,d in repeated["rows"])
    for key, expected in (("large_enum_variant",{"pub":6,"pub(scope)":17,"unqualified":17}),
                          ("too_many_arguments",{"pub":14,"pub(scope)":38,"unqualified":19})):
        assert Counter(r["declaration_visibility"] for r in rows if r["rule"]==key) == expected
    assert all(re.fullmatch("[0-9a-f]{40}",r["source_blob"]) for r in rows)
    actual = doc("public-v1/observed.json")
    assert text("public-v1/current.consumer.stderr") == "" and actual["current_consumer_exit"] == 0
    for key,n in (("current",312),("donor",16)):
        assert f"size of {n}" in text("public-v1/"+key+".layout.stderr")
    assert "expected `Box<LongitudinalTimeEvidenceV1>`" in text("public-v1/donor.consumer.stderr")
    assert "OriginalCellQ24EvaluationTimingV1::SystemLongitudinal" in text("public-v1/consumer.rs")
    assert len(doc("protected-826.json")["protected_files"]) == 826
    assert len(doc("marker-negatives.json")) == 16 and len(doc("root-store-probes.json")["rejected"]) == 5
    assert len(set(text("source-closure-roster.tsv").splitlines()[1:])) == 265
    lexical = doc("lexical.json")
    assert lexical.get("status") in ("qualified","pending")
    if lexical.get("status") == "qualified":
        assert lexical["boundaries"] == 1652 and lexical["protected_files"] == 826 and lexical["rust_files"] == 9141
        assert not lexical["authority_granted"]
        raw = gzip.decompress(data[lexical["raw_receipt"]])
        assert len(raw) == lexical["raw_bytes"]
        assert hashlib.sha256(raw).hexdigest() == lexical["raw_sha256"]
        receipt = json.loads(raw)
        assert receipt["schema"] == "hepta.caller-proof-receipt.v2"
        assert receipt["status"] == lexical["status_code"] == "PASS_HEPTA_CALLER_CLOSED_SET"
        assert len(receipt["boundaries"]) == len({b["id"] for b in receipt["boundaries"]}) == 1652
        assert len(receipt["protectedFiles"]) == len(set(receipt["protectedFiles"])) == 826
        assert receipt["rustFilesScanned"] == 9141 and receipt["authorityGranted"] is False
    print(json.dumps({"ordinary_cases_per_arm":9,"uid0_cases_per_arm":1,"total_per_arm":10,
                      "strict":[138,128],"donor_paths_with_diagnostics":98,"lexical":lexical},indent=2))

if __name__ == "__main__":
    main()
