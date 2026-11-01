"""Read only the counters actually visible now; never reconstruct old energy."""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess


def probe():
    counters, errors, candidates = [], [], set()
    roots = (Path("/sys/class/powercap"), Path("/sys/devices/virtual/powercap"),
             Path("/sys/class/hwmon"))
    for root in roots:
        if root.exists():
            for pattern in ("**/energy_uj", "*/energy_uj", "*/energy*_input",
                            "*/power*_input", "*/power*_average"):
                candidates.update(root.glob(pattern))
    seen = set()
    for path in sorted(candidates):
        identity = str(path.resolve())
        if identity in seen:
            continue
        seen.add(identity)
        try:
            value = float(path.read_text().strip())
            counters.append(dict(path=str(path), resolved_path=identity, value=value,
                unit="microjoule" if path.name.startswith("energy") else "microwatt",
                kind="cumulative_energy" if path.name.startswith("energy") else "power_sample"))
        except (OSError, ValueError) as error:
            errors.append(dict(path=str(path), error=type(error).__name__))
    executable = shutil.which("nvidia-smi")
    gpu = dict(executable=executable, attempted=bool(executable))
    if executable:
        try:
            result = subprocess.run(
                [executable, "--query-gpu=index,name,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10, check=False)
            gpu.update(returncode=result.returncode, output=result.stdout.strip()[:4096],
                       error=result.stderr.strip()[:2048])
        except (OSError, subprocess.TimeoutExpired) as error:
            gpu["error"] = type(error).__name__
    gpu_power = gpu.get("returncode") == 0 and bool(gpu.get("output"))
    return dict(observed_at_utc=datetime.now(timezone.utc).isoformat(),
        probe_roots=[dict(path=str(p), exists=p.exists()) for p in roots],
        readable_counters=counters, counter_errors=errors, nvidia_smi=gpu,
        visible_telemetry=bool(counters) or gpu_power, historical_energy_joules=None,
        historical_measurement_status="R12 did not integrate or retain physical energy",
        scope="Read-only current container visibility; not a claim about the physical host or original run",
        attribution="A readable host counter does not isolate this job from other tenants",
        inference="No historical joules, power integration, CPU-to-energy conversion or energy advantage inferred")
