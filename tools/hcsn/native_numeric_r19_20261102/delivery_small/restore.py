"""Verify ASCII parts and restore raw evidence into a new directory."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

def restore(destination):
    here=Path(__file__).resolve().parent
    manifest=json.loads((here/"MANIFEST.json").read_text())
    decoded=[]
    for part in manifest["parts"]:
        encoded=(here/part["path"]).read_bytes()
        assert len(encoded)==part["encoded_bytes"]<=80000
        assert hashlib.sha256(encoded).hexdigest()==part["encoded_sha256"]
        raw=base64.b64decode(encoded.strip(),validate=True)
        assert len(raw)==part["raw_bytes"]and hashlib.sha256(raw).hexdigest()==part["raw_sha256"]
        decoded.append(raw)
    archive=b"".join(decoded)
    assert len(archive)==manifest["archive_bytes"]and hashlib.sha256(archive).hexdigest()==manifest["archive_sha256"]
    destination.mkdir(parents=True,exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(archive),mode="r:gz")as bundle:
        for member in bundle.getmembers():
            path=PurePosixPath(member.name)
            assert member.isfile()and not path.is_absolute()and ".."not in path.parts
        bundle.extractall(destination,filter="data")
    index_raw=(destination/"RAW_EVIDENCE_INDEX.json").read_bytes()
    assert hashlib.sha256(index_raw).hexdigest()==manifest["raw_file_index_sha256"]
    index=json.loads(index_raw)
    assert len(index)==manifest["raw_file_count"]
    for name,record in index.items():
        data=(destination/name).read_bytes()
        assert len(data)==record["bytes"]and hashlib.sha256(data).hexdigest()==record["sha256"],name
    print(f"Verified {len(index)} files in {destination}; archive SHA256 {manifest['archive_sha256']}")

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("destination",type=Path);args=parser.parse_args();restore(args.destination)
