//! Paired fixture-only intervention; original legacy baseline is unchanged.
//! Current-user DELETE grants are not a production repair or sandbox qualification.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn legacy_current_user_delete_intervention_preserves_capability_gate() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        // Keep writable roots out of USERPROFILE exclusions such as AppData.
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create legacy delete test root");
        let codex_home = sandbox_home("legacy-user-delete-control");
        let workspace = test_root.path().join("workspace");
        let temp_root = test_root.path().join("temp");
        let tmp_root = test_root.path().join("tmp");
        let outside_root = test_root.path().join("outside");
        for directory in [&workspace, &temp_root, &tmp_root, &outside_root] {
            fs::create_dir_all(directory).expect("create legacy delete test directory");
        }
        let protected_git_dir = workspace.join(".git");
        fs::create_dir(&protected_git_dir).expect("create protected .git directory");

        let workspace_file = workspace.join("workspace-delete.txt");
        let temp_file = temp_root.join("temp-delete.txt");
        let tmp_file = tmp_root.join("tmp-delete.txt");
        let outside_file = outside_root.join("outside-delete.txt");
        fs::write(&workspace_file, "workspace").expect("seed workspace file");
        fs::write(&temp_file, "temp").expect("seed TEMP file");
        fs::write(&tmp_file, "tmp").expect("seed TMP file");
        fs::write(&outside_file, "outside").expect("seed outside file");

        let script = workspace.join("delete-fixtures.cmd");
        fs::write(
            &script,
            concat!(
                "@echo off\r\n",
                // Diagnostic-only stdin barrier. The actual legacy cmd deletes remain unchanged.
                "set /p HEPTA_DELETE_PROBE_READY=\r\n",
                "del /f /q \"%WORKSPACE_DELETE%\"\r\n",
                "del /f /q \"%TEMP_DELETE%\"\r\n",
                "del /f /q \"%TMP_DELETE%\"\r\n",
                "del /f /q \"%OUTSIDE_DELETE%\"\r\n",
                "rmdir \"%PROTECTED_GIT_DIR%\"\r\n",
                "exit /b 0\r\n",
            ),
        )
        .expect("write delete script");

        let env_map = HashMap::from([
            ("TEMP".to_string(), temp_root.to_string_lossy().into_owned()),
            ("TMP".to_string(), tmp_root.to_string_lossy().into_owned()),
            (
                "WORKSPACE_DELETE".to_string(),
                workspace_file.to_string_lossy().into_owned(),
            ),
            (
                "TEMP_DELETE".to_string(),
                temp_file.to_string_lossy().into_owned(),
            ),
            (
                "TMP_DELETE".to_string(),
                tmp_file.to_string_lossy().into_owned(),
            ),
            (
                "OUTSIDE_DELETE".to_string(),
                outside_file.to_string_lossy().into_owned(),
            ),
            (
                "PROTECTED_GIT_DIR".to_string(),
                protected_git_dir.to_string_lossy().into_owned(),
            ),
        ]);

        // Causal intervention is confined to these new TempDir-owned roots.
        // The original baseline test remains untouched and runs separately.
        let grants = legacy_user_delete_control::grant_user_delete(
            test_root.path(),
            &[workspace.as_path(), temp_root.as_path(), tmp_root.as_path()],
        )
        .expect("grant additive fixture-only current-user DELETE");
        let negatives = legacy_user_delete_control::negative_controls(test_root.path())
            .expect("native current-user DELETE without matching capability must fail");
        let permission_profile = PermissionProfile::workspace_write();
        let spawned = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(workspace.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                script.display().to_string(),
            ],
            workspace.as_path(),
            env_map,
            /*timeout_ms*/ Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ true,
            /*use_private_desktop*/ true,
        )
        .await
        .expect("spawn legacy delete session");
        let mut spawned = spawned;
        // Keep this diagnostic confined to the real child and test-owned paths.
        // Drop releases stdin on any probe error; no unrelated process is touched.
        struct ReleaseBarrier<'a> {
            sender: mpsc::Sender<Vec<u8>>,
            owned_session: &'a codex_utils_pty::ProcessHandle,
        }
        impl Drop for ReleaseBarrier<'_> {
            fn drop(&mut self) {
                if self.sender.try_send(b"\r\n".to_vec()).is_err() {
                    // This is the session owned by this fixture, never an enumerated PID.
                    self.owned_session.request_terminate();
                }
            }
        }
        let release = ReleaseBarrier {
            sender: spawned.session.writer_sender(),
            owned_session: &spawned.session,
        };
        let diagnostic_paths = [
            ("workspace_root", workspace.clone()),
            ("workspace_file", workspace_file.clone()),
            ("temp_root", temp_root.clone()),
            ("temp_file", temp_file.clone()),
            ("tmp_root", tmp_root.clone()),
            ("tmp_file", tmp_file.clone()),
            ("outside_root", outside_root.clone()),
            ("outside_file", outside_file.clone()),
            ("protected_git_dir", protected_git_dir.clone()),
        ];
        // Win32 reads run off this current-thread runtime so the two-second
        // observation limit and the existing five-second session timeout work.
        let probe = tokio::task::spawn_blocking(move || {
            let paths: Vec<_> = diagnostic_paths
                .iter()
                .map(|(role, path)| (*role, path.as_path()))
                .collect();
            legacy_delete_probe::observe(&paths)
        });
        let observation = match timeout(Duration::from_secs(2), probe).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err(anyhow::anyhow!("child diagnostic worker failed")),
            Err(_) => Err(anyhow::anyhow!("child diagnostic deadline")),
        };
        // A timed-out read-only worker may finish later; its result is dropped.
        drop(release);
        let (_, unused_stderr_rx) = mpsc::channel(/*buffer*/ 1);
        let mut stderr_rx = std::mem::replace(&mut spawned.stderr_rx, unused_stderr_rx);
        let stderr_task = tokio::spawn(async move {
            let mut stderr = Vec::new();
            while let Some(chunk) = stderr_rx.recv().await {
                stderr.extend(chunk);
            }
            stderr
        });
        let (stdout, exit_code) =
            collect_stdout_and_exit(spawned, codex_home.path(), Duration::from_secs(/*secs*/ 10))
                .await;
        let stdout = String::from_utf8_lossy(&stdout);
        let stderr = timeout(Duration::from_secs(/*secs*/ 10), stderr_task)
            .await
            .expect("timed out waiting for legacy delete stderr")
            .expect("legacy delete stderr task join");
        let stderr = String::from_utf8_lossy(&stderr);
        eprintln!("legacy delete stderr={stderr:?}");

        let observation = observation.expect("actual intervention child observation required");
        let actual = (
            exit_code,
            workspace_file.exists(),
            temp_file.exists(),
            tmp_file.exists(),
            fs::read_to_string(&outside_file).ok(),
            protected_git_dir.is_dir(),
        );
        let user = &observation["child_token"]["user_sid_alias"];
        let restricting = observation["child_token"]["restricting_sids"]
            .as_array()
            .expect("child restricting SIDs");
        let user_not_restricting = !restricting.iter().any(|sid| &sid["sid_alias"] == user);
        let objects = observation["objects"]
            .as_array()
            .expect("child object receipts");
        let allowed_user_grants = ["workspace_file", "temp_file", "tmp_file"]
            .iter()
            .all(|role| {
                let object = objects
                    .iter()
                    .find(|o| o["role"] == *role)
                    .expect("allowed leaf receipt");
                object["security"]["aces"]
                    .as_array()
                    .expect("leaf ACEs")
                    .iter()
                    .any(|ace| {
                        ace["kind"] == "allow"
                            && &ace["sid_alias"] == user
                            && ace["mask"].as_u64().is_some_and(|mask| {
                                mask & 0x10000 != 0 && mask & (0x40 | 0x10000000) == 0
                            })
                    })
            });
        let allowed_capability_grants =
            ["workspace_file", "temp_file", "tmp_file"]
                .iter()
                .all(|role| {
                    let object = objects
                        .iter()
                        .find(|o| o["role"] == *role)
                        .expect("allowed leaf capability receipt");
                    object["security"]["aces"]
                        .as_array()
                        .expect("leaf capability ACEs")
                        .iter()
                        .any(|ace| {
                            ace["kind"] == "allow"
                                && restricting
                                    .iter()
                                    .any(|sid| sid["sid_alias"] == ace["sid_alias"])
                                && ace["mask"].as_u64().is_some_and(|mask| {
                                    mask & 0x10000 != 0 && mask & (0x40 | 0x10000000) == 0
                                })
                        })
                });
        let same_user = observation["base_token"]["user_sid_alias"] == *user;
        let outside = objects
            .iter()
            .find(|o| o["role"] == "outside_file")
            .expect("outside receipt");
        let outside_user_delete_absent = !outside["security"]["aces"]
            .as_array()
            .expect("outside ACEs")
            .iter()
            .any(|ace| {
                ace["kind"] == "allow"
                    && &ace["sid_alias"] == user
                    && ace["mask"]
                        .as_u64()
                        .is_some_and(|mask| mask & (0x10000 | 0x10000000) != 0)
            });
        eprintln!(
            "HEPTA_LEGACY_USER_DELETE_CONTROL {}",
            serde_json::json!({
                "schema": "hepta.windows-legacy-user-delete-control.v1",
                "intervention": "fixture_only_additive_current_user_DELETE_on_three_owned_roots",
                "baseline_test_unchanged": true,
                "stdin_barrier": true,
                "grant_receipt": grants,
                "negative_controls": negatives,
                "child_observation": observation,
                "user_absent_from_restricting_sids": user_not_restricting,
                "base_and_child_same_user": same_user,
                "outside_user_DELETE_absent": outside_user_delete_absent,
                "allowed_leaf_user_DELETE_without_DELETE_CHILD": allowed_user_grants,
                "allowed_leaf_matching_cap_DELETE_without_DELETE_CHILD": allowed_capability_grants,
                "actual": actual,
                "production_policy_modified": false,
                "sandbox_qualified": false,
            })
        );
        assert!(
            allowed_capability_grants,
            "matching capability DELETE grant missing or broad"
        );
        assert!(same_user, "intervention must target actual child user");
        assert!(
            outside_user_delete_absent,
            "grant escaped explicitly writable roots"
        );
        assert!(
            user_not_restricting,
            "user must not satisfy capability pass"
        );
        assert!(
            allowed_user_grants,
            "observed additive user DELETE missing or broad"
        );
        assert_eq!(
            actual,
            (0, false, false, false, Some("outside".to_string()), true),
            "actual legacy child intervention outcomes differ; stdout={stdout:?} stderr={stderr:?}"
        );
    });
}
