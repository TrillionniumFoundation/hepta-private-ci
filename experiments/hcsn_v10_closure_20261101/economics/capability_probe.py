"""Read hardware exposure and try one private child cgroup without host changes."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cgroup = Path("/sys/fs/cgroup")
    test = cgroup / ("hcsn-v10-private-probe-" + str(os.getpid()))
    result = {"mkdir_succeeded": False, "memory_peak_bytes": None}
    try:
        test.mkdir()
        result["mkdir_succeeded"] = True
        result["visible_files"] = sorted(p.name for p in test.iterdir())
        test.rmdir()
        result["removed_empty_test_group"] = True
    except OSError as error:
        result["error_number"] = error.errno
        result["reason"] = str(error)
    paths = ["/sys/class/powercap", "/sys/class/hwmon", "/sys/class/drm",
             "/dev/dri", "/dev/nvidia0", "/var/run/docker.sock"]
    report = {"schema": "hcsn-v10-hardware-capabilities.v1",
              "self_cgroup": Path("/proc/self/cgroup").read_text(),
              "cgroup_mountinfo": [x for x in Path("/proc/self/mountinfo").read_text().splitlines()
                                   if " - cgroup2 " in x],
              "private_cgroup_test": result,
              "visible_devices_and_counter_directories": {p: Path(p).exists() for p in paths},
              "identity_manifest_configured": bool(os.environ.get("OIC_MANIFEST_PATH")),
              "energy_joules": None, "attributable_energy_counter_available": False,
              "external_authorized_runner": None,
              "external_runner_status": "No external execution capability was exposed in this task's tool registry; no runner inferred from prior sessions",
              "conclusion": "Exact independent cgroup memory and attributable energy require external capability; sampling cannot close this blocker"}
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
