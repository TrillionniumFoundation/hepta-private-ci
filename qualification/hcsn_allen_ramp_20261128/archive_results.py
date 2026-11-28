"""Store native current waveforms, exact event times, donor metadata and all held score streams."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
from forecast import ROOT,sha,put
def pack(path,inputs):
    with path.open("wb") as file,gzip.GzipFile(filename="",mode="wb",fileobj=file,mtime=0,compresslevel=4) as gz,tarfile.open(fileobj=gz,mode="w") as tar:
        for name,data in sorted(inputs.items()):
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o444;tar.addfile(info,io.BytesIO(data))
def run():
    src=ROOT/"source";cohort=json.loads((src/"cohort.json").read_text());out=ROOT/"deliver";out.mkdir(exist_ok=True);manifest={}
    reports=["PROTOCOL.md","HARD_LIF.md","source/cohort.json","joint_receipt.json","results/seal.json","results/terminal.json","results/cold_verification.json","hard-lif/seal.json","hard-lif/terminal.json","hard-lif/verification.json","numeric_qualification.json","voltage_alignment.json","excluded_specimens.json"]
    assert json.loads((ROOT/"results/cold_verification.json").read_text())["terminal_sha256"]==sha(ROOT/"results/terminal.json")
    assert json.loads((ROOT/"hard-lif/verification.json").read_text())["terminal_sha256"]==sha(ROOT/"hard-lif/terminal.json")
    def save_bundle(name,files):
        b={f:(ROOT/f).read_bytes() for f in sorted(files)};path=out/name;pack(path,b)
        manifest[name]=dict(bytes=path.stat().st_size,sha256=sha(path),members={n:hashlib.sha256(v).hexdigest() for n,v in b.items()})
    for sid in cohort["train"]+cohort["dev"]+cohort["held"]:
        names=[f"source/{sid}/"+n for n in ("signals-v2.npz","attempt-v2.json","specimen.json")]
        names.extend(p.relative_to(ROOT).as_posix() for p in (ROOT/"results").glob(f"*-{sid}-*.npz"))
        names.extend(p.relative_to(ROOT).as_posix() for p in (ROOT/"hard-lif").glob(f"{sid}-*.npz"))
        if sid in cohort["held"]:
            rec=json.loads((src/str(sid)/"attempt-v2.json").read_text())
            assert len(names)==3+8*len(rec["sweeps"])
        save_bundle("specimen-"+str(sid)+".tar.gz",names)
    save_bundle("metadata-and-reports.tar.gz",reports+["source/ranked_specimens.json","law4.npz"]+sorted(p.relative_to(ROOT).as_posix() for p in src.glob("page-*.json")))
    put(out/"original_manifest.json",manifest);print("bundles",len(manifest),"total native compressed bytes",sum(p.stat().st_size for p in out.iterdir()),flush=True)
if __name__=="__main__":run()
