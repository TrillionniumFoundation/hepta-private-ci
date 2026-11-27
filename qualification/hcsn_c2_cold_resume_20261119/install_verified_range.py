"""Install the final official byte range only after its bounded transfer verifies."""
import hashlib
import json
import os
from recover_runtime import EXPECTED, NAME, ROOT, TOTAL, URL

chunk = ROOT / "wheels/missing-range-102680576.bin"
data = chunk.read_bytes()
if len(data) != 2097152 or hashlib.sha256(data).hexdigest() != "acc26c109fbf938298fce2c6cc0dccc87687174018eef5b93f1be4a4a93a60f0":
    raise ValueError("transferred official range identity")
partial = ROOT / "wheels" / (NAME + ".partial")
final = ROOT / "wheels" / NAME
if final.exists() or partial.is_symlink() or partial.stat().st_size != TOTAL:
    raise ValueError("exact prior incomplete wheel required")
fd = os.open(partial, os.O_RDWR)
try:
    if os.pwrite(fd, data, 102680576) != len(data):
        raise ValueError("short final range write")
    os.fsync(fd)
finally:
    os.close(fd)
digest = hashlib.sha256()
with partial.open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
actual = digest.hexdigest()
if actual != EXPECTED:
    raise ValueError("entire official wheel SHA256 mismatch: " + actual)
os.replace(partial, final)
receipt = {
    "official_index_sha256": EXPECTED, "verified_sha256": actual, "bytes": TOTAL,
    "initial_official_url": URL,
    "final_range_official_url": "https://download.pytorch.org/whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl",
    "final_range": [102680576, 104777727], "final_range_sha256": hashlib.sha256(data).hexdigest(),
    "prior_failed_jobs": ["1a1f24892ee-ffbe-aba", "1a1f253ff32-ffbe-adc", "1a1f25ec4c6-ffbe-af9"],
    "all_retained_bytes_verified_by_complete_sha256": True,
    "wheel": str(final), "optimizer_calls": 0,
}
with (ROOT / "WHEEL_RECOVERY.json").open("x") as stream:
    json.dump(receipt, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps(receipt), flush=True)
