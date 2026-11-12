import faulthandler
import hashlib
import json
from pathlib import Path
import runpy
import signal
import sys
import time

started = time.monotonic()
def snapshot(_signum, frame):
    frames = []
    boundary = None
    relative = None
    boundaries = None
    source_index = None
    while frame is not None:
        filename = frame.f_code.co_filename
        if filename.endswith(("verify_hepta_callers.py", "hepta_typed_callers.py")):
            values = frame.f_locals
            record = {"file": filename, "line": frame.f_lineno, "function": frame.f_code.co_name}
            for key in ("relative", "source_path", "target", "method", "name", "pattern", "index", "length"):
                value = values.get(key)
                if isinstance(value, (str, int, Path)):
                    record[key] = str(value)[:500] if isinstance(value, Path) else (value[:500] if isinstance(value, str) else value)
            if isinstance(values.get("code"), str):
                record["code_length"] = len(values["code"])
            names = values.get("type_names")
            if isinstance(names, set):
                ordered_names = sorted(names)
                record["type_names_count"] = len(ordered_names)
                record["type_names_first10"] = ordered_names[:10]
                record["type_names_sha256"] = hashlib.sha256("\n".join(ordered_names).encode()).hexdigest()
            candidate = values.get("boundary")
            if candidate is not None and hasattr(candidate, "identifier"):
                boundary = candidate
                record["boundary_identifier"] = candidate.identifier
            if isinstance(values.get("relative"), str):
                relative = values["relative"]
            if isinstance(values.get("boundaries"), (tuple, list)):
                boundaries = values["boundaries"]
            if isinstance(values.get("source_index"), dict):
                source_index = values["source_index"]
            frames.append(record)
        frame = frame.f_back
    progress = {"diagnostic_elapsed_seconds": round(time.monotonic()-started, 3), "frames": frames}
    if boundary is not None and boundaries is not None:
        progress["boundary_identifier"] = boundary.identifier
        progress["boundary_ordinal"] = boundaries.index(boundary)+1
        progress["boundaries_total"] = len(boundaries)
    if relative is not None and source_index is not None:
        progress["source_relative"] = relative
        progress["source_ordinal"] = list(source_index).index(relative)+1
        progress["sources_total"] = len(source_index)
    print(json.dumps(progress, sort_keys=True), file=sys.stderr, flush=True)

faulthandler.enable()
faulthandler.dump_traceback_later(60, repeat=True)
signal.signal(signal.SIGALRM, snapshot)
signal.setitimer(signal.ITIMER_REAL, 20, 20)
sys.argv = ["scripts/verify_hepta_callers.py", "verify"]
try:
    runpy.run_path("scripts/verify_hepta_callers.py", run_name="__main__")
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
    faulthandler.cancel_dump_traceback_later()
