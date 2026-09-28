"""Check DecisionCell experiment design consistency, never evidence or qualification.

Logical split ordinals do not prove temporal isolation. Registry entries and role
names do not authenticate data, provider terms, consent, or independent observers.
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_strings(values, label):
    require(
        isinstance(values, list) and bool(values), f"{label}: nonempty list required"
    )
    require(
        all(isinstance(v, str) and v.strip() for v in values), f"{label}: invalid ID"
    )
    require(len(values) == len(set(values)), f"{label}: duplicate ID")
    return set(values)


def indexed(rows, label):
    require(
        isinstance(rows, list) and all(isinstance(r, dict) for r in rows),
        f"{label}: object list required",
    )
    unique_strings([r.get("id") for r in rows], label)
    return {r["id"]: r for r in rows}


def validate_decision_cell_design(registry):
    """Validate a planned panel; missing real execution bindings remain unresolved."""
    require(isinstance(registry, dict), "experiment registry must be an object")
    families = indexed(registry.get("families"), "families")
    profiles = indexed(registry.get("quantitativeProfiles"), "profiles")
    design = registry.get("decisionCellBackendDesign")
    require(isinstance(design, dict), "DecisionCell design missing")
    require(
        design.get("status") == "planned_not_executed",
        "design is not execution evidence",
    )
    referenced = unique_strings(design.get("familyIds"), "familyIds")
    require(referenced <= families.keys(), "unknown experiment family")
    for family_id in referenced:
        for field in ("arms", "outcomes"):
            unique_strings(families[family_id].get(field), f"{family_id}.{field}")
    arms = indexed(design.get("candidateArms"), "candidateArms")
    paired = unique_strings(design.get("pairedArmIds"), "pairedArmIds")
    require(set(arms) == paired, "paired panel must cover every backend exactly once")
    require(
        len(arms) >= 2 and "deterministic_existing" in arms,
        "comparison baseline missing",
    )
    require(
        arms["deterministic_existing"].get("backend") == "comparator",
        "deterministic baseline cannot be a learned backend",
    )
    learned_heads = []
    for arm_id, arm in arms.items():
        require(
            arm.get("backend") in ("comparator", "laya", "encoder"),
            "unknown backend role",
        )
        head = arm.get("headProfile")
        require(isinstance(head, str) and bool(head.strip()), "missing head profile")
        if arm_id != "deterministic_existing":
            require(arm["backend"] != "comparator", "duplicate comparator role")
            learned_heads.append(head)
    require(len(set(learned_heads)) == 1, "learned backend heads must match")
    require(
        {arm["backend"] for arm in arms.values()} == {"comparator", "laya", "encoder"},
        "backend panel must include comparator, Laya and encoder roles",
    )
    require(
        unique_strings(design.get("commonInputRoles"), "commonInputRoles")
        == {"question", "options", "state"},
        "paired backends require common complete input roles",
    )
    require(
        design.get("oodThresholdRule") == "multiplicity_adjusted_one_sided_upper_bound",
        "OOD rejection must use the preregistered multiplicity-adjusted upper bound",
    )
    seeds = design.get("seedReplicates")
    require(
        isinstance(seeds, list) and len(seeds) >= 2, "multiple seed replicates required"
    )
    require(
        all(type(s) is int and s >= 0 for s in seeds),
        "seed must be a nonnegative integer",
    )
    require(len(seeds) == len(set(seeds)), "duplicate seed replicate")
    profile_id = design.get("quantitativeProfile")
    require(
        isinstance(profile_id, str) and profile_id in profiles,
        "unknown quantitative profile",
    )
    profile = profiles[profile_id]
    for key in ("confidenceLevelPpm", "familywiseAlphaPpm", "targetPowerPpm"):
        require(
            type(profile.get(key)) is int and 0 < profile[key] < 1000000,
            f"{key}: integer probability must be strictly between zero and one million",
        )
    require(
        profile["confidenceLevelPpm"] >= 950000
        and profile["familywiseAlphaPpm"] <= 50000
        and profile["targetPowerPpm"] >= 800000,
        "weakened statistical confidence, alpha or power",
    )
    require(
        profile["confidenceLevelPpm"] >= 1000000 - profile["familywiseAlphaPpm"],
        "confidence level does not support the familywise alpha",
    )
    require(
        profile.get("candidateRule")
        == "candidate_LCB_strictly_greater_than_baseline_UCB",
        "candidate rule must retain conservative interval superiority",
    )
    for key, floor in (
        ("minimumEffectiveSampleSize", 400),
        ("bootstrapReplicates", 2000),
        ("minimumFutureWindows", 2),
        ("minimumIndependentSnapshots", 3),
    ):
        require(
            type(profile.get(key)) is int and profile[key] >= floor,
            f"{key}: weakened floor",
        )
    for key, ceiling in (
        ("maximumOldTaskDegradationPpm", 20000),
        ("maximumOodFalseAcceptancePpm", 5000),
        ("deletionNonResurrectionCount", 0),
    ):
        require(
            type(profile.get(key)) is int and 0 <= profile[key] <= ceiling,
            f"{key}: weakened ceiling",
        )
    require(
        profile.get("safetyPrivacyRetentionAndSupportFloorsAreNonCompensable") is True,
        "noncompensable constraints required",
    )
    windows = design.get("splitWindowOrder")
    require(isinstance(windows, dict), "splitWindowOrder must be an object")
    future = [f"future_{i + 1}" for i in range(len(windows) - 3)]
    order = ["training", "calibration", "selection", *future]
    require(
        set(windows) == set(order) and len(future) >= profile["minimumFutureWindows"],
        "split windows must cover training, calibration, selection and future windows",
    )
    ordinals = [windows[key] for key in order]
    require(all(type(v) is int and v >= 0 for v in ordinals), "invalid split ordinal")
    require(
        all(a < b for a, b in zip(ordinals, ordinals[1:])),
        "split order leaks future data",
    )
    groups = unique_strings(design.get("disjointGroupKeys"), "disjointGroupKeys")
    require(
        {"principal", "source_root", "episode", "task_template"} <= groups,
        "correlated-group isolation incomplete",
    )
    limits = design.get("resourceLimits")
    require(isinstance(limits, dict), "resource limits missing")
    for key in (
        "maximumBackendCandidates",
        "maximumSearchTrialsPerArm",
        "maximumParallelTrainingJobs",
        "maximumEvaluationRows",
    ):
        require(
            type(limits.get(key)) is int and limits[key] > 0,
            f"{key}: positive integer required",
        )
    require(
        len(arms) <= limits["maximumBackendCandidates"],
        "backend panel exceeds candidate budget",
    )
    require(
        len(seeds) <= limits["maximumSearchTrialsPerArm"],
        "seed panel exceeds per-arm trial budget",
    )
    require(
        limits["maximumParallelTrainingJobs"]
        <= len(learned_heads) * limits["maximumSearchTrialsPerArm"],
        "parallel jobs exceed learned-arm trial budget",
    )
    require(
        len(arms) * len(seeds) <= limits["maximumEvaluationRows"],
        "evaluation budget cannot cover even one row per arm and seed",
    )
    for key in (
        "maximumTotalWallTimeSeconds",
        "maximumDeviceMemoryMiB",
        "maximumTotalLifecycleCostUnits",
    ):
        require(key in limits, f"{key}: explicit binding or null required")
        value = limits[key]
        require(
            value is None or (type(value) is int and value > 0),
            f"{key}: invalid budget",
        )
        if value is None:
            require(
                design.get("unboundResourceDisposition") == "execution_blocked",
                "unbound resource must block execution",
            )
    adaptation = unique_strings(design.get("adaptationArmIds"), "adaptationArmIds")
    require(
        {"head_only", "organ_only", "cell_only", "organ_and_cell"} <= adaptation,
        "adaptation panel omits required comparison roles",
    )
    teacher = design.get("teacher")
    require(isinstance(teacher, dict), "teacher design missing")
    teachers = unique_strings(teacher.get("arms"), "teacher.arms")
    require(
        {"no_teacher", "permitted_local_teacher", "qualified_external_teacher"}
        <= teachers,
        "teacher panel omits required comparison roles",
    )
    for key in ("providerQualification", "dataUseRights"):
        require(
            teacher.get(key) == "unconfirmed", "design cannot confirm teacher evidence"
        )
    require(
        teacher.get("unconfirmedDisposition")
        == "teacher_collection_and_training_blocked",
        "unconfirmed teacher must block collection and training",
    )
    require(design.get("authorityDelta") == "none", "design cannot grant authority")
    for key in (
        "executionCompleted",
        "trainingCompleted",
        "backendSelected",
        "calibratedTrustEstablished",
        "futureWindowEfficacyEstablished",
    ):
        require(
            design.get(key) is False,
            f"{key}: design cannot establish a completed claim",
        )
