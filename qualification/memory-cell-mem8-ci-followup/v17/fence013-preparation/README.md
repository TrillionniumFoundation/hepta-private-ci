# Isolated Fence v0.13 qualification proposal

Status: **prepared, statically reviewed by the author, not admitted and not executed**. No repository ref, workflow run, original CI run, host service or model request was changed by this preparation.

## Exact source and execution scope

The proposed parent is the published MEM source commit `c89540598693697577cda8cba31cb07f6ce65317`, tree `5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae`. The proposed child adds exactly one file, `.github/workflows/hepta-mem-fence013-qualification.yml`, on the dedicated branch `codex/mem8-fence013-qualification-20261111-ed353817`.

The existing `.github/workflows/blob-size-policy.yml` and PR #5935 remain unchanged. The added workflow contains one copy of that original job, using the reviewed complete Action commit `openai/fence@c7675fea986c29f1d655753a7a61fd6b4141be8f` for v0.13.0. Its full job comparison is in [ORIGINAL_JOB_TO_HARNESS.patch](ORIGINAL_JOB_TO_HARNESS.patch). The earlier one-line pin candidate remains a separate, unqualified proposal in the feasibility review.

This is a qualification of the new Fence entry point on the original downstream policy mechanisms. The unchanged push comparison logic will inspect **c895 to this one-file harness child**. It does not re-evaluate the full PR #5935 comparison range and cannot establish that all regular PR CI is green. The product source tree is inherited unchanged from c895, while the actually checked-out commit is the new harness child; both identities are retained.

The original blocking workflow only triggers on pull requests and main pushes. This proposal opens no pull request and makes no main push. The new workflow itself accepts only the exact dedicated branch and checks the push's `before` identity against c895 before launching Fence. Admission should still retain the actual resulting run inventory; no unrelated run may be cancelled or altered.

## Preserved policy

`STATIC_VALIDATION.json` independently parses the two YAML documents and compares all six original step objects after removing only observation IDs and restoring the old Fence pin. They are exactly equal:

1. Fence is still configured with only `mode: audit`. No new allowlist, configuration, artifact compatibility opt-in, platform override, debug override or invocation override is supplied.
2. The same checkout Action, `fetch-depth: 0` and `persist-credentials: false`, runs after Fence.
3. The original comparison-range shell code is unchanged.
4. The original `python3 -B -m unittest discover -s scripts/tests -p test_blob_size_policy.py` command is unchanged.
5. The original checker, `512000` byte limit and `.github/blob-size-allowlist.txt`, are unchanged.
6. The original clean-worktree Action and `always() && !cancelled()` condition are unchanged.

The job remains `ubuntu-24.04`, **30 minutes**, and `contents: read` at both workflow and job scope. There is no `continue-on-error`, retry, permission expansion or new secret input. Fence retains its own original Node main/post entry points and `post-if: always()`. The harness never manually invokes, replaces or suppresses Fence's main or post hook.

## Explicit collection differences

The added workflow contains a standard-library Python collector as a literal shell heredoc. `capture.py` is the byte-identical extracted copy for review. It is written outside the checkout, under the job's runner temporary directory. The collector does not start Fence, issue model requests, launch native tests or query host credentials.

Before Fence, the collector:

- verifies the repository, exact branch, push event and c895 `before` anchor;
- reads only seven fixed files from the already downloaded, commit-pinned Fence Action: `action.yml`, four Action implementation files, the bundle manifest and `action/bin/fence`;
- verifies size, full SHA-256 and Git blob identity for every file, including the actual 2,203,880-byte executable; checks the manifest's source/release and actual executable digest;
- retains these exact public upstream files in the job artifact. This is the first proposed physical executable read: the feasibility review correctly retained its earlier binary-download limitation.

The expected executable SHA-256 is `1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04`, Git blob `77eb796b522a7ae83eb83c42d579f85a41945b3d`. The manifest is bound to reviewed source `64acdc94f531728494efbdf2d8f05faa26e90f7a`. These expectations are preserved in the emitted workflow rather than inferred from a moving release tag. A missing file or digest mismatch fails the new preflight and is not a Fence execution result.

After checkout and before the original policy steps, the collector retains exact HEAD/tree/parent, the complete Git leaf table, the physical clean-worktree result and the original policy files. It requires the checkout to be the event SHA, with c895 as its sole parent and exactly this one added workflow. The existing workflow, checker, unittest module, allowlist and clean Action must match the c895 committed bytes. The same observations are taken after the original checks; identity drift or a dirty source fails collection. Original command stdout/stderr remains in the job's full raw log; no command is swallowed by the collector.

The last regular steps create a manifest and compressed artifact using the already reviewed `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`. This adds one artifact upload under the unchanged audit policy; it adds no allowlist exception. The upload is part of the job observed by Fence. The collector does not copy environment dumps, Action token values, raw system journals or arbitrary host inventory. It captures only fixed source/action files and named Git identity commands. Each added Git observation has a separate 15-second bound inside the unchanged 30-minute job budget; the original policy commands and Fence budgets are unchanged.

## Post-hook and failure boundaries

The artifact is uploaded **before Action post hooks**, because GitHub executes those hooks after regular steps. Its result therefore explicitly says `NOT_FINAL` and `NOT_YET_OBSERVED_REQUIRES_TERMINAL_FULL_JOB_LOG`. It must never be interpreted as a final Fence post PASS.

Once the one admitted run is terminal, the reviewer must collect its original run/job metadata and complete raw job log, including the unmodified Fence preflight, fixed-enum diagnostic lines, original downstream policy output, clean step, checkout post and Fence post. The original Action supplies the bounded diagnostics; this proposal does not issue another inventory scan or parse arbitrary systemd journal messages. Missing source capture after an early Fence failure is recorded as not observed, not clean.

If setup fails again, preserve the new exact diagnostic and all downstream skipped/failure states without rerunning. If the bundle preflight, added Git observations or artifact upload fails, classify that phase independently. A GitHub cancellation or lost raw-log read produces a partial record, not an inferred Fence result. No catch or collector success converts an original failed step into success.

A final acceptance needs the exact one-run identity, matching actual bundle bytes, successful original Fence setup, executed original unittest/checker, unchanged source and successful original clean/post checks. This is still only this fixed Action/job qualification. It is not proof of the historical unavailable subreason, general hosted-runner compatibility, production custody, memory benefit or a complete security audit of the v0.13 release.

## Proposed admission, pending review

1. Read and approve the complete emitted workflow, full original-job diff, collector and static validation. Record the final workflow blob and complete child commit/tree once actually created.
2. Use a new branch anchored at exact c895. If the branch already exists, read its current identity and stop on any unexpected value; do not overwrite another source.
3. Create the one-file child commit with c895 as sole parent and verify the complete tree/parent/file bytes. Do not add this preparation README or other files to that child: the runtime verifies the one-path closure.
4. Advance only that new branch from c895 to the reviewed child with a compare-and-swap. This is the single push admission. Creating the branch directly at the child produces a zero `before` value and is deliberately rejected by the preflight.
5. Bind the resulting exact-head, push-event, attempt-1 run and job. Keep the run ID and any uncertain mutation acknowledgement; query the same identity rather than issuing another push or rerun.
6. Read through the single terminal result, retrieve the complete job raw log and artifact once, and verify ZIP/member/digest/receipt bindings offline. Keep the original c895 failures and this candidate's outcome as separate evidence.

The proposed workflow is not yet an instruction to create a ref or run. The author performed YAML parsing, Python AST parsing, six shell syntax checks and exact original-step comparison only. No executable or GitHub job was run locally as a substitute for the real qualification.
