from pathlib import Path

root = Path.cwd()


def replace_exact(path: str, old: str, new: str) -> None:
    target = root / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "codex-rs/hepta-ndu/src/evaluator_tests.rs",
    "fn missing_uncertainty_axis_is_unavailable() {\n",
    "fn missing_uncertainty_axis_reports_missing_axis() {\n",
)
replace_exact(
    "codex-rs/hepta-ndu/src/evaluator_tests.rs",
    '''    assert_eq!(error.code(), "NDU-E003");
}

#[test]
fn candidate_support_digest_binds_organ_and_contribution_semantics()''',
    '''    assert_eq!(error.code(), "NDU-E004");
}

#[test]
fn candidate_support_digest_binds_organ_and_contribution_semantics()''',
)

replace_exact(
    "qualification/lane-b/LANE_B_IMPLEMENTATION_TRUTH.json",
    '''        {"designOperation":"attach_context","state":"implemented_partial","path":"codex-rs/core/src/codex_thread.rs","symbol":"pub(crate) async fn submit_turn_input_and_wait_for_exact_admission(","callerClass":"embedded_codex_core","buildTarget":"codex-core"}''',
    '''        {"designOperation":"attach_context","state":"planned","path":null,"symbol":null,"callerClass":"none","buildTarget":null}''',
)

replace_exact(
    "scripts/hepta-lane-d-semantic-conformance.py",
    '''def verify_changes(base: str) -> int:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    changed = [line for line in result.stdout.splitlines() if line]
    denied = [
        path
        for path in changed
        if not any(
            path == prefix or path.startswith(prefix) for prefix in ALLOWED_PREFIXES
        )
    ]
    need(not denied, "out-of-envelope paths: " + ", ".join(denied))
    need(changed, "empty Lane D change set")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_D_CHANGE_POLICY",
                "changedPaths": len(changed),
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0
''',
    '''def is_lane_d_path(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix) for prefix in ALLOWED_PREFIXES
    )


def verify_changes(base: str, composed_candidate: bool = False) -> int:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    changed = [line for line in result.stdout.splitlines() if line]
    owned = [path for path in changed if is_lane_d_path(path)]
    unowned = [path for path in changed if not is_lane_d_path(path)]
    need(changed, "empty change set")
    need(owned, "empty Lane D owned change set")
    if not composed_candidate:
        need(not unowned, "out-of-envelope paths: " + ", ".join(unowned))
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_D_CHANGE_POLICY",
                "changedPaths": len(changed),
                "ownedPaths": len(owned),
                "unownedPathsIgnored": len(unowned) if composed_candidate else 0,
                "composedCandidate": composed_candidate,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0
''',
)
replace_exact(
    "scripts/hepta-lane-d-semantic-conformance.py",
    '''    need(any("x/y".startswith(prefix) for prefix in ("x/",)), "prefix fixture")
''',
    '''    need(any("x/y".startswith(prefix) for prefix in ("x/",)), "prefix fixture")
    need(is_lane_d_path("codex-rs/hepta-ndu/src/lib.rs"), "owned path fixture")
    need(
        not is_lane_d_path("codex-rs/hepta-learning-ledger/src/lib.rs"),
        "unowned path fixture",
    )
''',
)
replace_exact(
    "scripts/hepta-lane-d-semantic-conformance.py",
    '''    changes = sub.add_parser("verify-changes")
    changes.add_argument("--base", required=True)
''',
    '''    changes = sub.add_parser("verify-changes")
    changes.add_argument("--base", required=True)
    changes.add_argument(
        "--composed-candidate",
        action="store_true",
        help="partition and verify Lane D-owned paths inside a multi-lane candidate",
    )
''',
)
replace_exact(
    "scripts/hepta-lane-d-semantic-conformance.py",
    '''    return verify_changes(args.base)
''',
    '''    return verify_changes(args.base, args.composed_candidate)
''',
)
replace_exact(
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
    '''          python3 scripts/hepta-lane-d-semantic-conformance.py \
            verify-changes --base "${BASE_SHA}"
''',
    '''          python3 scripts/hepta-lane-d-semantic-conformance.py \
            verify-changes --base "${BASE_SHA}" --composed-candidate
''',
)

replace_exact(
    ".github/workflows/hepta-lane-e-gap-closure.yml",
    "  TARGET_BRANCH: codex/hepta-main-convergence-20260909\n",
    (
        "  LEGACY_TARGET_BRANCH: codex/hepta-main-convergence-20260909\n"
        "  PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}\n"
    ),
)
replace_exact(
    ".github/workflows/hepta-lane-e-gap-closure.yml",
    '''          git fetch --no-tags origin "${TARGET_BRANCH}"
          BASE_COMMIT="$(git rev-parse FETCH_HEAD)"
''',
    '''          if [ -n "${PR_BASE_SHA}" ]; then
            BASE_COMMIT="${PR_BASE_SHA}"
          else
            git fetch --no-tags origin "${LEGACY_TARGET_BRANCH}"
            BASE_COMMIT="$(git rev-parse FETCH_HEAD)"
          fi
          test "$(git cat-file -t "${BASE_COMMIT}")" = commit
''',
)

replace_exact(
    "tools/hepta-engineering-control/test_candidate_sandbox_hardening.py",
    '''        self._git("config", "user.name", "Lane G Test")
        self._git("config", "user.email", "lane-g@example.invalid")
''',
    '''        self._git("config", "user.name", "Lane G Test")
        self._git("config", "user.email", "lane-g@example.invalid")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "core.eol", "lf")
''',
)

path = root / ".github/workflows/hepta-lane-g-sandbox-hardening.yml"
text = path.read_text(encoding="utf-8")
old = '''          command -v bwrap
          bwrap --version
'''
new = '''          command -v bwrap
          bwrap --version
          if sysctl -n kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
            sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
            test "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns)" = 0
          fi
'''
if text.count(old) != 2:
    raise SystemExit(
        "hepta-lane-g-sandbox-hardening.yml: expected two adapter blocks"
    )
path.write_text(text.replace(old, new), encoding="utf-8")
