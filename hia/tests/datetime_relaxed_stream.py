"""Bounded original-process batches with complete compressed evidence streams."""
from collections import Counter
import gzip
import hashlib
import json
import struct
import subprocess

from datetime_calendar_oracle.custody import binding, require
from datetime_relaxed_cases import batches


class EvidenceStream:
    def __init__(self, path):
        self.path = path
        self.file = path.open("xb")
        self.stream = gzip.GzipFile(filename="", mode="wb", fileobj=self.file, mtime=0)
        self.digest = hashlib.sha256()
        self.length = 0

    def write(self, data):
        self.stream.write(data)
        self.digest.update(data)
        self.length += len(data)

    def close(self):
        self.stream.close()
        self.file.close()
        return {"raw_bytes": self.length, "raw_sha256": self.digest.hexdigest(),
                "archive": binding(self.path)}


def original_batches(executable, output, report):
    inputs = EvidenceStream(output / "inputs.bin.gz")
    observations = EvidenceStream(output / "original-chrono.bin.gz")
    error_kinds = [Counter(), Counter(), Counter()]
    cases = [0, 0]
    process_count = 0
    report.update(complete=False, normal_cases=0, unicode_cases=0, total_cases=0, processes=0)
    with (output / "original-batches.jsonl").open("x") as receipts, \
            (output / "original-chrono.stderr").open("xb") as errors:
        try:
            for batch in batches():
                raw = b"".join(struct.pack("<2Q", coverage, len(payload)) + payload
                               for coverage, payload in batch)
                inputs.write(raw)
                observed = subprocess.run([str(executable)], input=raw, capture_output=True, timeout=60)
                observations.write(observed.stdout)
                errors.write(observed.stderr)
                process_count += 1
                receipt = {"batch": process_count, "cases": len(batch), "input_bytes": len(raw),
                           "input_sha256": hashlib.sha256(raw).hexdigest(),
                           "output_bytes": len(observed.stdout),
                           "output_sha256": hashlib.sha256(observed.stdout).hexdigest(),
                           "stderr_bytes": len(observed.stderr), "returncode": observed.returncode}
                receipts.write(json.dumps(receipt, separators=(",", ":")) + "\n")
                receipts.flush()
                require(observed.returncode == 0 and len(observed.stdout) == len(batch) * 192,
                        "original three-API observer failed or returned incomplete output in batch "
                        + str(process_count))
                for index, (coverage, payload) in enumerate(batch):
                    require(coverage in (0, 1), "unknown coverage kind")
                    cases[coverage] += 1
                    for mode in range(3):
                        words = struct.unpack_from("<8Q", observed.stdout, index * 192 + mode * 64)
                        require(words[0] == 1 and words[1] in (0, 1) and words[5] <= 7
                                and words[6:] == (0, 0), "malformed original observation")
                        error_kinds[mode][words[5]] += 1
                yield batch, observed.stdout
            report["complete"] = True
        finally:
            report.update(normal_cases=cases[0], unicode_cases=cases[1], total_cases=sum(cases),
                          processes=process_count, inputs=inputs.close(),
                          original_output=observations.close(),
                          original_error_kinds=[{str(k): v for k, v in sorted(c.items())}
                                                for c in error_kinds])
