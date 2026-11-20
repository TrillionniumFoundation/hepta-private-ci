import ctypes, ctypes.util, json, os, pathlib, subprocess, time
root = pathlib.Path(__file__).resolve().parent
report = {"schema": "hepta.cost-counter-capability.v1", "observed_unix_ns": str(time.time_ns()), "purpose": "Prospective read-only capability check; no model or verifier execution", "past_experiment_energy_backfilled": False, "host_energy_is_process_energy": False, "system_configuration_changed": False}
rapl = []
bases = sorted(pathlib.Path("/sys/class/powercap").glob("intel-rapl:*"))
for base in bases:
    if not (base / "energy_uj").exists():
        continue
    paths = [base] + sorted(base.glob("intel-rapl:*"))
    for path in paths:
        if not (path / "energy_uj").exists():
            continue
        row = {"path": str(path), "name": (path / "name").read_text().strip(), "max_energy_range_uj": (path / "max_energy_range_uj").read_text().strip()}
        try:
            row["unprivileged_energy_uj"] = (path / "energy_uj").read_text().strip()
        except OSError as error:
            row["unprivileged_errno"] = error.errno
        start = time.monotonic_ns()
        result = subprocess.run(["sudo", "-n", "/usr/bin/cat", str(path / "energy_uj")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        row["existing_sudo_read"] = {"exit_code": result.returncode, "wall_nanoseconds": str(time.monotonic_ns() - start), "energy_uj": result.stdout.decode().strip() if result.returncode == 0 else None, "error": result.stderr.decode(errors="replace").strip()[:1000] if result.returncode else None}
        rapl.append(row)
report["rapl"] = rapl
nvml = {"library": ctypes.util.find_library("nvidia-ml")}
try:
    lib = ctypes.CDLL(nvml["library"] or "libnvidia-ml.so.1")
    lib.nvmlInit_v2.restype = ctypes.c_int
    lib.nvmlErrorString.argtypes = [ctypes.c_int]
    lib.nvmlErrorString.restype = ctypes.c_char_p
    code = lib.nvmlInit_v2()
    nvml["initialization_return"] = code
    if code == 0:
        try:
            lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
            lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
            device = ctypes.c_void_p()
            code = lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(device))
            nvml["device_handle_return"] = code
            if code == 0:
                lib.nvmlDeviceGetTotalEnergyConsumption.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]
                lib.nvmlDeviceGetTotalEnergyConsumption.restype = ctypes.c_int
                energy = ctypes.c_ulonglong()
                code = lib.nvmlDeviceGetTotalEnergyConsumption(device, ctypes.byref(energy))
                nvml["total_energy_return"] = code
                nvml["total_energy_api_value"] = str(energy.value) if code == 0 else None
                nvml["total_energy_return_description"] = lib.nvmlErrorString(code).decode()
        finally:
            lib.nvmlShutdown()
except (OSError, AttributeError) as error:
    nvml["error"] = str(error)
report["nvml"] = nvml
report["finished_unix_ns"] = str(time.time_ns())
(root / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
