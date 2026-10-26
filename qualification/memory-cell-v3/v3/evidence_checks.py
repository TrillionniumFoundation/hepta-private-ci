"""Validate nested experiment membership; byte integrity alone is insufficient."""

import json

from v2.evidence import checked_path


def same_file(directory, relative, expected):
    if json.loads(checked_path(directory, relative).read_text()) != expected:
        raise ValueError(f"nested summary differs from retained artifact: {relative}")


def unique_members(rows, key, expected, label):
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"empty or invalid {label} member list")
    found = [key(row) for row in rows]
    if len(found) != len(set(found)) or set(found) != set(expected):
        raise ValueError(f"missing, duplicate, or unexpected {label} members")


def verify_stage_data(stage, data, directory, protocol, identity, seeds, development):
    if not isinstance(data, dict):
        raise ValueError("completed stage is missing its actual experiment data")
    if stage in {"capacity", "structure", "native"}:
        if (
            data.get("seeds") != seeds
            or data.get("source_commit") != identity["commit"]
            or data.get("development") is not development
        ):
            raise ValueError(f"nested source, seed, or mode mismatch: {stage}")
        summary_path = {
            "capacity": "capacity/capacity-summary.json",
            "structure": "structure/structure.json",
            "native": "native/native.json",
        }[stage]
        same_file(directory, summary_path, data)
    if stage == "capacity":
        settings = protocol["capacity"]
        if data.get("settings") != settings:
            raise ValueError("capacity settings differ from frozen protocol")
        expected_data = {name: seeds for name in settings["numeric_domains"]}
        if settings["include_digits"]:
            expected_data["digits-pixels"] = seeds
        for seed in seeds:
            for mixture in settings["random_mix"]:
                expected_data[
                    f"synthetic-mix-{str(mixture).replace('.', 'p')}-seed-{seed}"
                ] = [seed]
        unique_members(
            data.get("datasets"),
            lambda row: row["name"],
            expected_data,
            "capacity dataset",
        )
        families = (
            "global_svd",
            "predeclared_cells",
            "random_cells",
            "learned_cells",
            "learned_vq",
        )
        members = set()
        for dataset in data["datasets"]:
            rows, columns = dataset["shape"]
            if (
                type(rows) is not int
                or type(columns) is not int
                or min(rows, columns) <= 0
            ):
                raise ValueError("invalid capacity dataset shape")
            budgets = {
                max(1, int(rows * columns * 4 * fraction))
                for fraction in settings["budget_fractions_int32"]
            }
            members.update(
                (dataset["name"], seed, budget, family)
                for seed in expected_data[dataset["name"]]
                for budget in budgets
                for family in families
            )
        unique_members(
            data.get("records"),
            lambda row: (
                row["dataset"],
                row["seed"],
                row["budget_bytes"],
                row["family"],
            ),
            members,
            "capacity experiment",
        )
        if not any(record.get("feasible") for record in data["records"]):
            raise ValueError("capacity stage executed no feasible memory reads")
        for record in data["records"]:
            if (
                record.get("feasible")
                and record.get("hidden", {}).get("queries", 0) <= 0
            ):
                raise ValueError("feasible capacity model has no hidden read evidence")
    elif stage == "routing_graph":
        unique_members(data.get("runs"), lambda row: row["seed"], seeds, "routing seed")
        expected_domains = protocol["routing_graph"][
            "development_domains" if development else "formal_domains"
        ]
        for run in data["runs"]:
            if (
                run.get("source_commit") != identity["commit"]
                or run.get("development") is not development
                or set(run.get("domains", {})) != set(expected_domains)
            ):
                raise ValueError("routing source/mode/domain inventory differs")
            same_file(directory, f"routing-graph/seed-{run['seed']}/summary.json", run)
            for domain, result in run["domains"].items():
                if (
                    not result.get("arms")
                    or result.get("new_domain_policy_updates") != 0
                ):
                    raise ValueError(
                        "routing evaluation lacks arms or changed transferred policy"
                    )
                same_file(
                    directory,
                    f"routing-graph/seed-{run['seed']}/evaluation/{domain}/summary.json",
                    result,
                )
    elif stage == "lifecycle":
        if (
            data.get("source_commit") != identity["commit"]
            or data.get("development_only") is not development
        ):
            raise ValueError("lifecycle nested source or mode differs")
        unique_members(
            data.get("runs"), lambda row: row["seed"], seeds, "lifecycle seed"
        )
        same_file(directory, "lifecycle/summary.json", data)
        for run in data["runs"]:
            unique_members(
                run.get("domains"),
                lambda row: row["domain"],
                protocol["lifecycle"]["domains"],
                "lifecycle domain",
            )
            for domain in run["domains"]:
                stages = domain.get("stages", [])
                if (
                    domain.get("seed") != run["seed"]
                    or [row["stage"] for row in stages]
                    != protocol["lifecycle"]["stages"]
                    or [row["generation"] for row in stages]
                    != list(range(1, len(stages) + 1))
                ):
                    raise ValueError("lifecycle update membership differs")
                if domain.get("fresh_process", {}).get("queries", 0) <= 0:
                    raise ValueError("lifecycle lacks fresh-process queries")
                same_file(
                    directory,
                    f"lifecycle/seed-{run['seed']}/{domain['domain']}/summary.json",
                    domain,
                )
    elif stage == "structure":
        unique_members(
            data.get("results"),
            lambda row: (row["seed"], row["name"]),
            {(seed, flow) for seed in seeds for flow in protocol["structure"]["flows"]},
            "structural flow",
        )
        if any(
            data.get("protocol", {}).get(key) != value
            for key, value in protocol["structure"].items()
        ):
            raise ValueError("structural settings differ from frozen protocol")
        for result in data["results"]:
            episodes = result.get("episodes", [])
            count = 2 if result["name"] == "convergent" else 1
            if len(episodes) != count or [row["index"] for row in episodes] != list(
                range(count)
            ):
                raise ValueError("structural episode membership differs")
            if set(result.get("totals", {})) != {
                "adaptive",
                "fixed_1",
                "fixed_2",
                "fixed_4",
                "efficient_fixed_1",
                "efficient_fixed_2",
                "efficient_fixed_4",
            }:
                raise ValueError(
                    "structure is missing a natural or equal-work fixed control"
                )
    elif stage == "native":
        unique_members(
            data.get("results"), lambda row: row["seed"], seeds, "native training seed"
        )
        if any(
            data.get("protocol", {}).get(key) != value
            for key, value in protocol["native"].items()
        ):
            raise ValueError("native training settings differ from frozen protocol")
        for row in data["results"]:
            if row.get("native", {}).get("queries") != protocol["native"]["rows"]:
                raise ValueError(
                    "native read count differs from trained fact inventory"
                )
            same_file(
                directory,
                f"native/seed-{row['seed']}/native/native-receipt.json",
                row["native"],
            )
    else:
        raise ValueError("unknown completed experiment stage")
