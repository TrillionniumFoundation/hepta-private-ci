"""Plot archived delay-law costs and errors; no model or reference is executed."""

import ast
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, LogFormatterMathtext, NullLocator


HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1]
REPO = KERNEL.parents[1]
RATIOS = (1, 4, 16, 32, 64)
SERIES = ("deterministic", "erlang_2", "erlang_8", "erlang_32", "erlang_128")
LABELS = ("Deterministic delay", "Erlang K=2", "Erlang K=8", "Erlang K=32", "Erlang K=128")
COLORS = ("#173042", "#d2932b", "#aa7796", "#50916c", "#288ca8")
MARKERS = ("s", "o", "v", "^", "D")
PHYSICS_FIELDS = ("generator", "lower", "upper", "reset", "reward",
                  "escape_reward", "spike_reward", "discount")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    identities, points, references, sources = {}, [], {}, {}

    def record(path):
        identities[str(path.relative_to(REPO))] = {"sha256": sha(path), "bytes": path.stat().st_size}

    # Each of the eight tensor fields has one FP64 element in the archived
    # one-state Physics constructor. Its rational delay is not tensor payload.
    tree = ast.parse((KERNEL / "differentiable.py").read_text())
    physics = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Physics")
    fields = tuple(node.target.id for node in physics.body if isinstance(node, ast.AnnAssign)
                   and isinstance(node.annotation, ast.Attribute) and node.annotation.attr == "Tensor")
    if fields != PHYSICS_FIELDS:
        raise ValueError("archived deterministic Physics field declaration changed")

    for law, directory in (("deterministic", HERE.parent / "longtime-20261119"), ("erlang", HERE)):
        report_path = directory / "attempt001/REPORT.json"
        report = json.loads(report_path.read_text())
        record(report_path)
        frozen = report["source_sha256"] if law == "deterministic" else report["source_sha256_before"]
        if frozen != report["source_sha256_after"]:
            raise ValueError("campaign source changed during execution")
        sources[law] = frozen
        for name, expected in frozen.items():
            path = KERNEL / name
            if sha(path) != expected:
                raise ValueError(f"source hash differs: {path}")
            record(path)
        record(directory / "REVIEW.json")
        for receipt in report["cases"]:
            path = report_path.parent / receipt["child_result"]
            if sha(path) != receipt["child_result_sha256"]:
                raise ValueError(f"child receipt hash differs: {path}")
            record(path)
            row = json.loads(path.read_text())
            if (receipt["status"] != "completed" or receipt["returncode"] != 0
                    or row["status"] != "completed" or not row["all_values_and_gradients_finite"]
                    or row["source_sha256_before"] != frozen or row["source_sha256_after"] != frozen):
                raise ValueError("incomplete or source-mismatched observation")
            target = Fraction(row["target"])
            ratio = target / Fraction(1, 5)
            if ratio.denominator != 1 or int(ratio) not in RATIOS:
                raise ValueError("unexpected observed horizon")
            if row["quantity_order"] != ["hit_count", "active", "refractory"]:
                raise ValueError("observable order differs")
            reference = row["reference_80_digits" if law == "deterministic" else "deterministic_reference_80_digits"]
            if law == "deterministic":
                references[str(target)] = reference
                stages, series = None, "deterministic"
                physics_fields = dict.fromkeys(PHYSICS_FIELDS, 8)
                if row["initial_channels"] != [1., -.3] or row["delay"] != "1/5":
                    raise ValueError("deterministic configuration differs")
            else:
                if reference != references[str(target)]:
                    raise ValueError("the saved deterministic Gamma reference differs between laws")
                stages, series = row["stages"], f"erlang_{row['stages']}"
                physics_fields = row["physics_tensor_bytes_by_field"]
                if sum(physics_fields.values()) != row["physics_tensor_bytes"]:
                    raise ValueError("physics payload sum differs")
                if row["delay_mean_fraction"] != "1/5" or row["original_complete_kernel_imported"]:
                    raise ValueError("Erlang law or execution scope differs")
            if row["rate_fp64_hex"] != float(1.7).hex() or row["dtype"] != "float64":
                raise ValueError("rate or precision differs")
            errors = [[value - float(ref) for value, ref in zip(values, reference[key])]
                      for values, key in zip(row["values"], ("values_probability", "values_content"))]
            maximum = max(abs(value) for values in errors for value in values)
            if maximum != row["maximum_value_absolute_error"] or not math.isfinite(maximum) or maximum <= 0:
                raise ValueError("error arithmetic differs or a log observation is nonpositive")
            points.append({"series": series, "stages": stages, "target_fraction": str(target),
                           "time_over_mean_delay": int(ratio), "dynamic_tensor_bytes": row["state_tensor_bytes"],
                           "physics_tensor_bytes": sum(physics_fields.values()),
                           "physics_tensor_bytes_by_field": physics_fields,
                           "persistent_tensor_bytes": row["state_tensor_bytes"] + sum(physics_fields.values()),
                           "max_value_absolute_error": maximum, "value_signed_errors": errors,
                           "max_lambda_gradient_absolute_error": row["maximum_gradient_absolute_error"],
                           "raw_case": str(path.relative_to(REPO)), "raw_case_sha256": sha(path),
                           "controller_receipt": receipt, "controller_report": str(report_path.relative_to(REPO))})
    expected = {(series, ratio) for series in SERIES for ratio in RATIOS}
    observed = [(point["series"], point["time_over_mean_delay"]) for point in points]
    if len(observed) != 25 or len(set(observed)) != 25 or set(observed) != expected:
        raise ValueError("the complete five-law, five-horizon matrix is required")
    record(KERNEL / "ERLANG_FREEZE.json")
    record(Path(__file__))
    return {"schema": "hepta.delay-state-cost-error-figure.v1", "points": points,
            "input_identities": identities, "frozen_execution_source_sha256": sources,
            "quantity_order": ["hit_count", "active", "refractory"], "channels": [1., -.3],
            "rate_fp64_hex": float(1.7).hex(), "mean_delay_fraction": "1/5",
            "reference": "Saved common 80-digit finite Gamma renewal reference, rounded to FP64 for the recorded error.",
            "deterministic_physics_provenance": "Eight one-element FP64 Physics tensor fields in the hash-bound one-state study_longtime.py constructor; fixed rational delay excluded.",
            "cost_scope": "Dynamic state plus all Physics tensor payload, counting repeated references; excludes Python, autograd, allocator, and temporary matrices.",
            "interpretation": "Erlang uses a different delay law; costs were observed in separate batches. No paired timing or speedup claim.",
            "rendering": "All 25 measured points; line segments connect observations only. No fit, extrapolation, smoothing, clipping, or omitted points.",
            "new_model_calls": 0, "new_reference_calculations": 0, "matplotlib_version": matplotlib.__version__}


def main():
    data = collect()
    prefix = HERE / "state-cost-error-comparison"
    data_path = prefix.with_name(prefix.name + "-data.json")
    data_path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "hepta-delay-state-cost-error-v1"})
    figure, axes = plt.subplots(1, 2, figsize=(14.4, 8.0))
    figure.subplots_adjust(left=.075, right=.98, bottom=.245, top=.79, wspace=.28)
    figure.suptitle("Refractory delay: state cost versus law error", x=.075, y=.968,
                   ha="left", fontsize=21, fontweight="bold", color="#173042")
    figure.text(.075, .908, "One active state · rate 1.7 · mean delay 0.2 · probability and signed-content channels · FP64 CPU",
                ha="left", fontsize=11, color="#536474")
    for series, label, color, marker in zip(SERIES, LABELS, COLORS, MARKERS):
        points = sorted((p for p in data["points"] if p["series"] == series), key=lambda p: p["time_over_mean_delay"])
        x = [p["time_over_mean_delay"] for p in points]
        for axis, key in zip(axes, ("persistent_tensor_bytes", "max_value_absolute_error")):
            axis.plot(x, [p[key] for p in points], color=color, marker=marker, label=label,
                      linewidth=2.0 if series == "deterministic" else 1.65,
                      markersize=6.4, markeredgecolor="white", markeredgewidth=.6, zorder=4)
    for axis in axes:
        axis.set_xscale("log", base=2)
        axis.set_yscale("log")
        axis.set_xlim(.85, 78)
        axis.set_xticks(RATIOS, [str(x) for x in RATIOS])
        axis.xaxis.set_minor_locator(NullLocator())
        axis.yaxis.set_minor_locator(NullLocator())
        axis.grid(axis="y", which="major", color="#e5e9ed", linewidth=.8)
        axis.set_axisbelow(True)
        axis.tick_params(colors="#536474", labelsize=10)
        axis.set_xlabel("Elapsed time / mean delay  (T/d)", fontsize=10.5, labelpad=11)
    axes[0].set_ylim(160, 300000)
    axes[0].set_yticks((1000, 10000, 100000))
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    axes[0].set_ylabel("Dynamic state + Physics · bytes", fontsize=11, labelpad=9)
    axes[1].set_ylim(8e-18, .3)
    axes[1].set_yticks((1e-16, 1e-12, 1e-8, 1e-4, 1e-2))
    axes[1].yaxis.set_major_formatter(LogFormatterMathtext(base=10))
    axes[1].set_ylabel("Maximum absolute observable error", fontsize=11, labelpad=9)
    for axis, title in zip(axes, ("A   Complete persistent tensor cost", "B   Error against deterministic Gamma reference")):
        axis.set_title(title, loc="left", fontsize=12, fontweight="bold", color="#173042", pad=14)
    last = {p["series"]: p for p in data["points"] if p["time_over_mean_delay"] == 64}
    last_erlang = last["erlang_128"]["persistent_tensor_bytes"]
    last_deterministic = last["deterministic"]["persistent_tensor_bytes"]
    axes[0].annotate(f"At T/d = 64\nK=128: {last_erlang:,} B\nDeterministic: {last_deterministic:,} B",
                     xy=(64, last_erlang), xytext=(.28, .72), textcoords="axes fraction",
                     ha="left", va="center", fontsize=10, color="#173042",
                     bbox=dict(boxstyle="round,pad=.45", facecolor="white", edgecolor="#d8e1e7"),
                     arrowprops=dict(arrowstyle="->", color="#536474", lw=1.0), zorder=6)
    first = next(p for p in data["points"] if p["series"] == "erlang_128" and p["time_over_mean_delay"] == 1)
    active_error = abs(first["value_signed_errors"][0][1])
    axes[1].annotate(f"K=128 at first release (T=d)\n|active-mass error| = {active_error:.5f}",
                     xy=(1, first["max_value_absolute_error"]), xytext=(.12, .63), textcoords="axes fraction",
                     ha="left", va="center", fontsize=10, color="#237c95",
                     bbox=dict(boxstyle="round,pad=.45", facecolor="white", edgecolor="#d8e1e7"),
                     arrowprops=dict(arrowstyle="->", color="#288ca8", lw=1.0), zorder=6)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper left", bbox_to_anchor=(.068, .875),
                  ncol=5, frameon=False, fontsize=10.2, columnspacing=2.0, handlelength=2.0)
    footer = ["25 archived observations; five measured horizons per law. Lines connect measured points only; both y axes are logarithmic.",
              "Tensor payload excludes autograd, allocator and Python storage. Deterministic Physics: 64 B; Erlang Physics from each original receipt.",
              "Erlang changes the delay law. Cost observations are from separate batches; no paired speedup claim or extrapolation.",
              "Error covers hit count, active mass and refractory mass across both channels; the saved 80-digit reference is compared in FP64."]
    for index, text in enumerate(footer):
        figure.text(.075, .142 - index * .026, text, ha="left", fontsize=9.0, color="#536474")
    for suffix in (".png", ".svg"):
        destination = prefix.with_suffix(suffix)
        metadata = {"Creator": "Hepta current-state qualification", "Date": None} if suffix == ".svg" else None
        figure.savefig(destination, dpi=200, facecolor="white", metadata=metadata)
        if suffix == ".svg":
            destination.write_text("\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n")
    plt.close(figure)
    print(json.dumps({"points": len(data["points"]), "source_and_receipt_files": len(data["input_identities"]),
                      "data": str(data_path), "png": str(prefix.with_suffix('.png')), "svg": str(prefix.with_suffix('.svg'))}))


if __name__ == "__main__":
    main()
