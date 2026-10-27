set pagination off
set confirm off
set print thread-events off
set debuginfod enabled off
set logging file /workspace/scratch/95988d8d3ab1/ndu-matrix-reopen-diagnosis-v4-001/execution-005/restored-mode-0600/debugger.log
set logging overwrite on
set logging enabled on
break 'codex_hepta_matrix_sdk::sdk::MatrixSdkClient::login_or_restore::{{closure}}::{{closure}}'
commands
silent
echo HEPTA_DIAG_BUILD_TIMEOUT_ERROR_BRANCH\n
bt 8
continue
end
break 'codex_hepta_matrix_sdk::sdk::load_session'
commands
silent
echo HEPTA_DIAG_LOAD_SESSION_REACHED\n
continue
end
run
quit $_exitcode
