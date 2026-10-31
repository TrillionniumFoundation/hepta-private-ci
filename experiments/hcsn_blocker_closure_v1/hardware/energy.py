"""Read actual NVML device energy with exact CUDA UUID binding; no estimates."""

import ctypes
import math
import time


def energy_delta(start, end, elapsed, minimum):
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        return dict(joules=None, reason="Counter missing, regressed, or has no resolved increment")
    if not math.isfinite(elapsed) or elapsed <= 0 or elapsed < minimum:
        return dict(joules=None, reason="Counter window shorter than the registered minimum")
    return dict(joules=(end-start)/1000., reason=None)


class NvmlEnergy:
    """Only use a whole-GPU handle with the exact UUID exposed by PyTorch."""

    def __init__(self, cuda_uuid):
        self.lib, self.handle, self.error = None, None, None
        self.identity = dict(cuda_uuid=str(cuda_uuid) if cuda_uuid is not None else None,
                             nvml_uuid=None, device_match=False)
        try:
            identity = str(cuda_uuid)
            if not identity.startswith("GPU-"):
                raise ValueError("A full-GPU CUDA UUID is required; MIG or unknown UUID rejected")
            lib = ctypes.CDLL("libnvidia-ml.so.1")
            functions = {
                "nvmlInit_v2": [], "nvmlShutdown": [],
                "nvmlDeviceGetHandleByUUID": [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)],
                "nvmlDeviceGetUUID": [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint],
                "nvmlDeviceGetTotalEnergyConsumption": [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)],
            }
            for name, arguments in functions.items():
                function = getattr(lib, name)
                function.argtypes, function.restype = arguments, ctypes.c_int
            if lib.nvmlInit_v2() != 0:
                raise RuntimeError("NVML initialization unavailable")
            self.lib = lib
            handle = ctypes.c_void_p()
            code = lib.nvmlDeviceGetHandleByUUID(identity.encode(), ctypes.byref(handle))
            if code != 0:
                raise RuntimeError("NVML UUID lookup failed: "+str(code))
            buffer = ctypes.create_string_buffer(96)
            code = lib.nvmlDeviceGetUUID(handle, buffer, len(buffer))
            actual = buffer.value.decode("ascii")
            self.identity["nvml_uuid"] = actual
            if code != 0 or actual.lower() != identity.lower() or not actual.startswith("GPU-"):
                raise ValueError("CUDA/NVML UUID mismatch or shared MIG identity")
            self.handle = handle
            self.identity["device_match"] = True
            self.read()
        except Exception as error:
            self.error = repr(error)

    def read(self):
        if self.lib is None or self.handle is None:
            raise RuntimeError("No matched NVML energy handle")
        value = ctypes.c_ulonglong()
        code = self.lib.nvmlDeviceGetTotalEnergyConsumption(self.handle, ctypes.byref(value))
        if code != 0:
            raise RuntimeError("NVML energy counter unsupported or unavailable: "+str(code))
        return int(value.value)

    def close(self):
        if self.lib is not None:
            self.lib.nvmlShutdown()
            self.lib = None


def measure_energy(counter, invoke, synchronize, design, batch):
    result = dict(identity=counter.identity, joules=None, error=counter.error,
                  process_exclusivity_established=False, idle_subtracted=False)
    if counter.error is not None:
        return result
    try:
        def idle_window():
            synchronize()
            before = counter.read()
            tick = time.perf_counter()
            time.sleep(design["idle_seconds"])
            after = counter.read()
            seconds = time.perf_counter()-tick
            return dict(start_millijoules=before, end_millijoules=after, seconds=seconds,
                        **energy_delta(before, after, seconds, design["idle_seconds"]))

        result["idle_before"] = idle_window()
        synchronize()
        before = counter.read()
        tick, iterations = time.perf_counter(), 0
        while iterations < design["maximum_iterations"]:
            invoke()
            synchronize()
            iterations += 1
            if time.perf_counter()-tick >= design["minimum_active_seconds"]:
                break
        after = counter.read()
        seconds = time.perf_counter()-tick
        reading = energy_delta(before, after, seconds, design["minimum_active_seconds"])
        result.update(reading, start_millijoules=before, end_millijoules=after,
                      seconds=seconds, iterations=iterations)
        result["joules_per_sequence_batch"] = None if reading["joules"] is None else reading["joules"]/iterations
        result["joules_per_example"] = None if reading["joules"] is None else reading["joules"]/(iterations*batch)
        result["idle_after"] = idle_window()
        if (result["idle_before"]["end_millijoules"] < result["idle_before"]["start_millijoules"]
                or result["idle_after"]["end_millijoules"] < result["idle_after"]["start_millijoules"]
                or before < result["idle_before"]["end_millijoules"]
                or result["idle_after"]["start_millijoules"] < after):
            raise ValueError("Counter regressed within or between idle and active windows")
        result["scope"] = "Gross device-wide resident full-sequence energy; excludes host copies and CPU energy; idle/background activity is included"
    except Exception as error:
        result.update(joules=None, joules_per_sequence_batch=None, joules_per_example=None, error=repr(error))
    return result
