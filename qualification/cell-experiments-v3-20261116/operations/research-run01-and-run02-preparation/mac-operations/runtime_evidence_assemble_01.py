import pathlib, hashlib, json, zipfile, io
root = pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
manifest = json.loads("{\"archive\":\"publication-runtime-evidence-input-01.zip\",\"bytes\":4065367,\"sha256\":\"0826b1b04d181fa86b4f29b846275789132a4d611ac81a609442c99bfa570a4c\",\"plan_sha256\":\"af66104fd8b0c55aa01c6d261a6ed2fcc53cc6a8ff0790680b741da0abfe2a02\",\"parts\":[{\"name\":\"publication-runtime-evidence-part-00.bin\",\"bytes\":322560,\"sha256\":\"9c8d55d321e2f747727dcd0865f9e8fa67032b6d19c9021aff7c15c6151e60e8\"},{\"name\":\"publication-runtime-evidence-part-01.bin\",\"bytes\":322560,\"sha256\":\"229314171160eaafc700260a714a2ea116b7608ff66bf6dadc67685e5a21624b\"},{\"name\":\"publication-runtime-evidence-part-02.bin\",\"bytes\":322560,\"sha256\":\"3580e8d1c3a42a193dc34bf43de7dbfd4df76d4b8bbe3f1a336de7388f848774\"},{\"name\":\"publication-runtime-evidence-part-03.bin\",\"bytes\":322560,\"sha256\":\"0e56d3cf8b5009a734f27a28c325d8c3b81038b7967fb6bafd69d04d3470f427\"},{\"name\":\"publication-runtime-evidence-part-04.bin\",\"bytes\":322560,\"sha256\":\"c5a65258858542acfb245238606e78517b42b2283e58fbdbe68ed1f9bb2b0511\"},{\"name\":\"publication-runtime-evidence-part-05.bin\",\"bytes\":322560,\"sha256\":\"9df300842e053bca851512f80c80d5456d4b10d42089b796128b9832a3ff80a0\"},{\"name\":\"publication-runtime-evidence-part-06.bin\",\"bytes\":322560,\"sha256\":\"3c1214928cf9791bcb570da774dd55982006b628eee27246ba065f5c7d7a2b9c\"},{\"name\":\"publication-runtime-evidence-part-07.bin\",\"bytes\":322560,\"sha256\":\"ee31612371f98a5b5b3219ee04f488b28aac0f273cf1715f22473f2c241701a6\"},{\"name\":\"publication-runtime-evidence-part-08.bin\",\"bytes\":322560,\"sha256\":\"cd0952fa3d109e8ce38d7c5e6948b3f708c06802317930c19b1dd6b10a5e5332\"},{\"name\":\"publication-runtime-evidence-part-09.bin\",\"bytes\":322560,\"sha256\":\"3a31623af4680d23cd4215e7040d596294a858a6024706213dfdffd0cc97ce9a\"},{\"name\":\"publication-runtime-evidence-part-10.bin\",\"bytes\":322560,\"sha256\":\"92d5171023557a0a71fb83cdcf62ab44b0cc41cc22e865e67bea7c9ea617c29e\"},{\"name\":\"publication-runtime-evidence-part-11.bin\",\"bytes\":322560,\"sha256\":\"19b873284316a05c5bfb7bdfb701e03825a533a9a7113b51d87786ef327c31d8\"},{\"name\":\"publication-runtime-evidence-part-12.bin\",\"bytes\":194647,\"sha256\":\"0eff6ae8ca62f19d2acfac16b4e9b4514ee114b2e0be6bcf4ad18fb44d2ce61d\"}]}")
chunks = []
for part in manifest["parts"]:
    path = root / part["name"]
    assert path.is_file() and not path.is_symlink()
    data = path.read_bytes()
    assert len(data) == part["bytes"] and hashlib.sha256(data).hexdigest() == part["sha256"]
    chunks.append(data)
data = b"".join(chunks)
assert len(data) == manifest["bytes"] and hashlib.sha256(data).hexdigest() == manifest["sha256"]
path = root / manifest["archive"]
if path.exists():
    assert not path.is_symlink() and path.read_bytes() == data
else:
    with path.open("xb") as stream:
        stream.write(data)
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    assert archive.testzip() is None
    raw = archive.read("NATIVE_FINAL_PLAN_01.json")
    assert hashlib.sha256(raw).hexdigest() == manifest["plan_sha256"]
    plan = json.loads(raw)
    expected = {"NATIVE_FINAL_PLAN_01.json", *plan["files"]}
    assert len(archive.namelist()) == len(expected) == 57
    assert set(archive.namelist()) == expected
    for name, item in plan["files"].items():
        payload = archive.read(name)
        assert len(payload) == item["bytes"] < 512000
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
result = {"schema":"hepta.runtime-evidence-assembly.v3","status":"ASSEMBLED_VERIFIED","archive":manifest["archive"],"archive_sha256":manifest["sha256"],"archive_bytes":manifest["bytes"],"plan_sha256":manifest["plan_sha256"],"payload_files":len(plan["files"]),"stages":len(plan["stages"]),"git_worktree_changed":False}
receipt = root / "PUBLICATION_RUNTIME_ASSEMBLED_01.json"
if receipt.exists():
    assert not receipt.is_symlink() and json.loads(receipt.read_text()) == result
else:
    with receipt.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
print(json.dumps(result))
