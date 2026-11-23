"""Verify the submitted source reduction and original source-guard receipts offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
BASE_ID="801d8663b2a110fd4ec959d5bf08b7aa3911b918"
NEW_ID="84b3342da917dfade86fcf5b73f1f5f358eda113"
FILE="codex-rs/hepta-agentd/src/root_independent_b_client.rs"

def git_id(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def one(source,pattern):
    matches=list(re.finditer(pattern,source,re.MULTILINE|re.DOTALL))
    assert len(matches)==1,(pattern,len(matches))
    return matches[0]

def verify_reduction(base,candidate):
    old=one(base,r"^    pub\(crate\) fn comparison_digest\(&self\) -> Result<Digest32, Error> \{\n(.*?)^    \}\n")
    block=one(candidate,r"^impl CompletedData \{\n    fn comparison_digest\(&self\) -> Result<Digest32, Error> \{\n(.*?)^    \}\n\}\n\n")
    body=block[1].strip()
    assert body==old[1].strip().replace("self.data.","self.")
    assert body=="digest(&self.comparison_digest).map_err(unavailable)"
    call=one(candidate,r"^            data\.comparison_digest\(\)\?;$")
    assert call.start()>block.end()
    expanded=candidate[:call.start()]+"            "+body.replace("self.","data.")+"?;"+candidate[call.end():]
    assert expanded[:block.start()]+expanded[block.end():]==base[:old.start()]+base[old.end():]
    assert "digest(&data.plan_digest).map_err(unavailable)?;\n            digest(&data.execution_digest).map_err(unavailable)?;" in base
    assert candidate.count(".comparison_digest()")==1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,help="optional unmodified 3b138733 checkout")
    args=parser.parse_args()
    hashes=json.loads((HERE/"subject-blobs.json").read_text())
    receipts=json.loads((HERE/"guard-results.json").read_text())
    with ZipFile(HERE/"source-replay.zip") as z:
        base=z.read("base.rs"); candidate=z.read("candidate.rs")
        assert (git_id(base),git_id(candidate))==(BASE_ID,NEW_ID)
        assert hashes[FILE]==BASE_ID
        protocol=z.read("protocol.rs")
        assert git_id(protocol)==hashes["codex-rs/hepta-agentd/src/root_independent_b_protocol.rs"]
        for token in (b"Completed(Box<CompletedData>)",b"pub(crate) comparison_digest: String",b"pub(crate) fn digest(value: &str) -> io::Result<Digest32>",b"result.is_zero() || result.to_string() != value"):
            assert token in protocol
        verify_reduction(base.decode(),candidate.decode())
        for label,mutation in {
            "different input":lambda s:s.replace("digest(&self.comparison_digest)", "digest(&self.plan_digest)"),
            "changed error":lambda s:s.replace("digest(&self.comparison_digest).map_err(unavailable)","digest(&self.comparison_digest).map_err(|_| Error::WrongScope)"),
            "skipped call":lambda s:s.replace("            data.comparison_digest()?;\n",""),
            "changed order":lambda s:s.replace("data.comparison_digest()?;\n            digest(&data.plan_digest).map_err(unavailable)?;","digest(&data.plan_digest).map_err(unavailable)?;\n            data.comparison_digest()?;"),
        }.items():
            try: verify_reduction(base.decode(),mutation(candidate.decode()))
            except AssertionError: continue
            raise AssertionError("negative control accepted: "+label)
        totals={}
        for arm, rows in receipts.items():
            for suite, result in rows.items():
                data=z.read(arm+"-"+suite+".log")
                assert hashlib.sha256(data).hexdigest()==result["sha256"]
                names=[m.decode() for m in re.findall(rb"^(test_[^\n]+?) \.\.\. ok$",data,re.M)]
                assert names==result["tests"]==receipts["base"][suite]["tests"]
                assert len(names)==result["count"] and data.rstrip().endswith(b"OK")
            totals[arm]=sum(r["count"] for r in rows.values())
        assert totals=={"base":11,"candidate":11}
    if args.source:
        for name,oid in hashes.items():
            assert git_id((args.source/name).read_bytes())==oid,name
        files=sorted((args.source/"codex-rs/hepta-agentd").rglob("*.rs"))
        # A module-local callable (and a crate-private old type) suffices here.
        # Inspect all invocation/UFCS spellings, including tests and examples.
        pattern=re.compile(r"(?:\.|::)\s*comparison_digest\s*\(")
        assert not [str(p) for p in files if pattern.search(p.read_text())]
        print("Verified pinned files:",len(hashes),"Agentd Rust source files examined:",len(files))
    print(json.dumps({"base":BASE_ID,"candidate":NEW_ID,"negative_controls":4,"original_source_tests":totals},sort_keys=True))

if __name__=="__main__":
    main()
