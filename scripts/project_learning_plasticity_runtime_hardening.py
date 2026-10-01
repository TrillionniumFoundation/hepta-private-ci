#!/usr/bin/env python3
"""Project plasticity runtime hardening into an isolated Git worktree.

This authoring helper never mutates the qualification checkout and never commits or
pushes. It performs exact reviewed replacements, runs rustfmt/check/tests in the
provided detached worktree, and exports only ordinary source files plus logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_FILES = {
    "codex-rs/hepta-agentd/src/plasticity_runtime.rs",
    "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
    "codex-rs/hepta-agentd/src/state.rs",
    "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs",
    "codex-rs/hepta-agentd/src/plasticity_topology_iteration_coordinator.rs",
}


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one match, observed {count}")
    return text.replace(old, new, 1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], cwd: Path, log: Path) -> int:
    with log.open("wb") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    return result.returncode


def patch_runtime(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    WorkerFailed,\n",
        "    /// The request crossed the bounded queue boundary, so durable work may\n"
        "    /// have started. Reconcile the original idempotency identity before retry.\n"
        "    Indeterminate(&'static str),\n",
        "runtime indeterminate error",
    )
    wait_block = """        tokio::select! {
            _ = cancellation.cancelled() => Err(PlasticityRuntimeCallErrorV1::Cancelled),
            _ = wait_until_unix(deadline) => Err(PlasticityRuntimeCallErrorV1::DeadlineExceeded),
            result = receive => result.map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?,
        }
"""
    parameter_wait = """        await_enqueued_response(
            receive,
            cancellation,
            deadline,
            "parameter outcome requires idempotency-key reconciliation",
        )
        .await
"""
    topology_wait = """        await_enqueued_response(
            receive,
            cancellation,
            deadline,
            "topology outcome requires idempotency-key reconciliation",
        )
        .await
"""
    text = replace_once(text, wait_block, parameter_wait, "parameter post-queue wait")
    text = replace_once(text, wait_block, topology_wait, "topology post-queue wait")
    text = replace_once(
        text,
        "                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::WorkerFailed));\n",
        "                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Indeterminate(\n"
        "                    \"parameter blocking worker failed after queue admission\",\n"
        "                )));\n",
        "parameter worker failure",
    )
    text = replace_once(
        text,
        "                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::WorkerFailed));\n",
        "                let _ = response.send(Err(PlasticityRuntimeCallErrorV1::Indeterminate(\n"
        "                    \"topology blocking worker failed after queue admission\",\n"
        "                )));\n",
        "topology worker failure",
    )
    helper_anchor = """fn default_context(
    evidence_time_unix_seconds: u64,
    budget: PlasticityRuntimeBudgetV1,
) -> Result<PlasticityRuntimeRequestContextV1, PlasticityRuntimeCallErrorV1> {
"""
    helper = """async fn await_enqueued_response<T>(
    receive: oneshot::Receiver<
        Result<PlasticityRuntimeOutcomeV1<T>, PlasticityRuntimeCallErrorV1>,
    >,
    cancellation: CancellationToken,
    deadline_unix_seconds: u64,
    indeterminate_reason: &'static str,
) -> Result<PlasticityRuntimeOutcomeV1<T>, PlasticityRuntimeCallErrorV1> {
    tokio::select! {
        _ = cancellation.cancelled() => {
            Err(PlasticityRuntimeCallErrorV1::Indeterminate(indeterminate_reason))
        }
        _ = wait_until_unix(deadline_unix_seconds) => {
            Err(PlasticityRuntimeCallErrorV1::Indeterminate(indeterminate_reason))
        }
        result = receive => {
            result.map_err(|_| PlasticityRuntimeCallErrorV1::Indeterminate(indeterminate_reason))?
        }
    }
}

"""
    text = replace_once(text, helper_anchor, helper + helper_anchor, "post-queue helper")
    test_anchor = """    #[test]
    fn plasticity_aggregate_quota_spans_parameter_and_topology_work() {
"""
    tests = """    #[tokio::test]
    async fn plasticity_post_queue_cancellation_is_indeterminate() {
        let (response, receive) = oneshot::channel();
        let cancellation = CancellationToken::new();
        cancellation.cancel();
        let result: Result<PlasticityRuntimeOutcomeV1<()>, PlasticityRuntimeCallErrorV1> =
            await_enqueued_response(
                receive,
                cancellation,
                unix_now().saturating_add(30),
                "reconcile cancellation",
            )
            .await;
        drop(response);
        assert!(matches!(
            result,
            Err(PlasticityRuntimeCallErrorV1::Indeterminate(
                "reconcile cancellation"
            ))
        ));
    }

    #[tokio::test]
    async fn plasticity_post_queue_closed_response_is_indeterminate() {
        let (response, receive) = oneshot::channel::<
            Result<PlasticityRuntimeOutcomeV1<()>, PlasticityRuntimeCallErrorV1>,
        >();
        drop(response);
        let result = await_enqueued_response(
            receive,
            CancellationToken::new(),
            unix_now().saturating_add(30),
            "reconcile closed response",
        )
        .await;
        assert!(matches!(
            result,
            Err(PlasticityRuntimeCallErrorV1::Indeterminate(
                "reconcile closed response"
            ))
        ));
    }

"""
    text = replace_once(text, test_anchor, tests + test_anchor, "post-queue tests")
    path.write_text(text, encoding="utf-8")


def patch_producer(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use crate::PlasticityRuntimeCallErrorV1;\nuse crate::PlasticityRuntimeHandleV1;\n",
        "use crate::PlasticityRuntimeCallErrorV1;\n"
        "use crate::PlasticityRuntimeHandleV1;\n"
        "use crate::PlasticityRuntimeOutcomeV1;\n"
        "use crate::PlasticityRuntimeRequestContextV1;\n",
        "producer imports",
    )
    parameter_anchor = """    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
"""
    parameter_method = """    pub(crate) async fn submit_parameter_with_context(
        &self,
        request: ParameterPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<ParameterPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        self.handle
            .propose_parameter_with_context(request, context)
            .await
    }

"""
    text = replace_once(text, parameter_anchor, parameter_method + parameter_anchor, "producer parameter context")
    topology_end = """    pub(crate) async fn submit_topology(
        &self,
        request: TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<TopologyPlasticityProductReceiptV1, PlasticityRuntimeCallErrorV1> {
        self.handle.propose_topology(request, now).await
    }
"""
    topology_replacement = topology_end + """

    pub(crate) async fn submit_topology_with_context(
        &self,
        request: TopologyPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
    ) -> Result<
        PlasticityRuntimeOutcomeV1<TopologyPlasticityProductReceiptV1>,
        PlasticityRuntimeCallErrorV1,
    > {
        self.handle.propose_topology_with_context(request, context).await
    }
"""
    text = replace_once(text, topology_end, topology_replacement, "producer topology context")
    path.write_text(text, encoding="utf-8")


def patch_state(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    parameter_method = """    pub(crate) async fn submit_parameter_plasticity_v1(
        &self,
        request: codex_hepta_intelligence::ParameterPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::ParameterPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_parameter(request, now).await
    }
"""
    parameter_replacement = parameter_method + """

    /// Explicit execution-control boundary used by the production self-iteration
    /// coordinator. The caller supplies one bounded deadline/cancellation/budget
    /// context and receives phase timing with the proposal receipt.
    pub(crate) async fn submit_parameter_plasticity_with_context_v1(
        &self,
        request: codex_hepta_intelligence::ParameterPlasticityProductRequestV1,
        context: crate::PlasticityRuntimeRequestContextV1,
    ) -> Result<
        crate::PlasticityRuntimeOutcomeV1<
            codex_hepta_intelligence::ParameterPlasticityProductReceiptV1,
        >,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_parameter_with_context(request, context).await
    }
"""
    text = replace_once(text, parameter_method, parameter_replacement, "state parameter context")
    topology_method = """    pub(crate) async fn submit_topology_plasticity_v1(
        &self,
        request: codex_hepta_intelligence::TopologyPlasticityProductRequestV1,
        now: u64,
    ) -> Result<
        codex_hepta_intelligence::TopologyPlasticityProductReceiptV1,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_topology(request, now).await
    }
"""
    topology_replacement = topology_method + """

    /// Explicit execution-control boundary for governed topology self-iteration.
    pub(crate) async fn submit_topology_plasticity_with_context_v1(
        &self,
        request: codex_hepta_intelligence::TopologyPlasticityProductRequestV1,
        context: crate::PlasticityRuntimeRequestContextV1,
    ) -> Result<
        crate::PlasticityRuntimeOutcomeV1<
            codex_hepta_intelligence::TopologyPlasticityProductReceiptV1,
        >,
        crate::PlasticityRuntimeCallErrorV1,
    > {
        let producer = self
            .plasticity_runtime
            .get()
            .ok_or(crate::PlasticityRuntimeCallErrorV1::Closed)?;
        producer.submit_topology_with_context(request, context).await
    }
"""
    text = replace_once(text, topology_method, topology_replacement, "state topology context")
    path.write_text(text, encoding="utf-8")


def patch_parameter_coordinator(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use crate::PlasticityRuntimeCallErrorV1;\n",
        "use crate::PlasticityRuntimeCallErrorV1;\nuse crate::PlasticityRuntimeRequestContextV1;\n",
        "parameter coordinator imports",
    )
    old_trait = """    fn submit_parameter<'a>(
        &'a self,
        request: ParameterPlasticityProductRequestV1,
        now_unix_seconds: u64,
"""
    new_trait = """    fn submit_parameter<'a>(
        &'a self,
        request: ParameterPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
"""
    if text.count(old_trait) != 2:
        raise ValueError("parameter submission trait/impl signatures drifted")
    text = text.replace(old_trait, new_trait)
    text = replace_once(
        text,
        "                .submit_parameter_plasticity_v1(request, now_unix_seconds)\n"
        "                .await\n",
        "                .submit_parameter_plasticity_with_context_v1(request, context)\n"
        "                .await\n"
        "                .map(|outcome| outcome.receipt)\n",
        "parameter state submission",
    )
    old_method = """    pub async fn submit_parameter_iteration(
        &self,
        request: ControlEngineeringParameterIterationRequestV1,
        now_unix_seconds: u64,
    ) -> Result<ControlEngineeringParameterIterationReceiptV1, ControlEngineeringIterationErrorV1>
    {
        request
            .envelope
            .validate_at(now_unix_seconds)
            .map_err(ControlEngineeringIterationErrorV1::Envelope)?;
"""
    new_method = """    pub async fn submit_parameter_iteration(
        &self,
        request: ControlEngineeringParameterIterationRequestV1,
        runtime_context: PlasticityRuntimeRequestContextV1,
    ) -> Result<ControlEngineeringParameterIterationReceiptV1, ControlEngineeringIterationErrorV1>
    {
        let now_unix_seconds = runtime_context.evidence_time_unix_seconds;
        request
            .envelope
            .validate_at(now_unix_seconds)
            .map_err(ControlEngineeringIterationErrorV1::Envelope)?;
        if runtime_context.deadline_unix_seconds > request.envelope.expiry_unix_seconds {
            return Err(ControlEngineeringIterationErrorV1::Binding(
                "runtime deadline exceeds frozen envelope expiry",
            ));
        }
"""
    text = replace_once(text, old_method, new_method, "parameter coordinator context")
    text = replace_once(
        text,
        "            .submit_parameter(request.product_request, now_unix_seconds)\n",
        "            .submit_parameter(request.product_request, runtime_context)\n",
        "parameter coordinator explicit submission",
    )
    path.write_text(text, encoding="utf-8")


def patch_topology_coordinator(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use crate::PlasticityRuntimeCallErrorV1;\n",
        "use crate::PlasticityRuntimeCallErrorV1;\nuse crate::PlasticityRuntimeRequestContextV1;\n",
        "topology coordinator imports",
    )
    old_trait = """    fn submit_topology<'a>(
        &'a self,
        request: TopologyPlasticityProductRequestV1,
        now_unix_seconds: u64,
"""
    new_trait = """    fn submit_topology<'a>(
        &'a self,
        request: TopologyPlasticityProductRequestV1,
        context: PlasticityRuntimeRequestContextV1,
"""
    if text.count(old_trait) != 2:
        raise ValueError("topology submission trait/impl signatures drifted")
    text = text.replace(old_trait, new_trait)
    text = replace_once(
        text,
        "                .submit_topology_plasticity_v1(request, now_unix_seconds)\n"
        "                .await\n",
        "                .submit_topology_plasticity_with_context_v1(request, context)\n"
        "                .await\n"
        "                .map(|outcome| outcome.receipt)\n",
        "topology state submission",
    )
    old_method = """    pub async fn submit_topology_iteration(
        &self,
        request: ControlEngineeringTopologyIterationRequestV1,
        now_unix_seconds: u64,
    ) -> Result<
        ControlEngineeringTopologyIterationReceiptV1,
        ControlEngineeringTopologyIterationErrorV1,
    > {
        request
            .envelope
            .validate_at(now_unix_seconds)
            .map_err(ControlEngineeringTopologyIterationErrorV1::Envelope)?;
"""
    new_method = """    pub async fn submit_topology_iteration(
        &self,
        request: ControlEngineeringTopologyIterationRequestV1,
        runtime_context: PlasticityRuntimeRequestContextV1,
    ) -> Result<
        ControlEngineeringTopologyIterationReceiptV1,
        ControlEngineeringTopologyIterationErrorV1,
    > {
        let now_unix_seconds = runtime_context.evidence_time_unix_seconds;
        request
            .envelope
            .validate_at(now_unix_seconds)
            .map_err(ControlEngineeringTopologyIterationErrorV1::Envelope)?;
        if runtime_context.deadline_unix_seconds > request.envelope.expiry_unix_seconds {
            return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
                "runtime deadline exceeds frozen envelope expiry",
            ));
        }
"""
    text = replace_once(text, old_method, new_method, "topology coordinator context")
    text = replace_once(
        text,
        "            .submit_topology(request.product_request, now_unix_seconds)\n",
        "            .submit_topology(request.product_request, runtime_context)\n",
        "topology coordinator explicit submission",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    output = args.output.resolve()
    if worktree == output or worktree in output.parents or output in worktree.parents:
        parser.error("worktree and output must be separate")
    if not (worktree / ".git").exists():
        parser.error("--worktree must be a detached Git worktree")
    if subprocess.check_output(["git", "-C", str(worktree), "status", "--porcelain"], text=True).strip():
        raise SystemExit("authoring worktree must start clean")

    patch_runtime(worktree / "codex-rs/hepta-agentd/src/plasticity_runtime.rs")
    patch_producer(worktree / "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs")
    patch_state(worktree / "codex-rs/hepta-agentd/src/state.rs")
    patch_parameter_coordinator(
        worktree / "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs"
    )
    patch_topology_coordinator(
        worktree / "codex-rs/hepta-agentd/src/plasticity_topology_iteration_coordinator.rs"
    )

    output.mkdir(parents=True, exist_ok=True)
    logs = output / "logs"
    logs.mkdir(exist_ok=True)
    codex = worktree / "codex-rs"
    commands = [
        (
            "fmt",
            [
                "cargo",
                "fmt",
                "--manifest-path",
                "Cargo.toml",
                "--package",
                "codex-hepta-agentd",
            ],
        ),
        (
            "check",
            [
                "cargo",
                "check",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--all-targets",
            ],
        ),
        (
            "runtime-tests",
            [
                "cargo",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "plasticity_post_queue_",
                "--",
                "--test-threads=1",
            ],
        ),
    ]
    results: list[dict[str, Any]] = []
    failed = False
    for name, command in commands:
        code = run(command, codex, logs / f"{name}.log")
        results.append({"name": name, "command": command, "exitCode": code})
        failed |= code != 0
        if name == "fmt" and code != 0:
            break

    changed = set(
        subprocess.check_output(
            ["git", "-C", str(worktree), "diff", "--name-only"], text=True
        ).splitlines()
    )
    unexpected = changed.difference(EXPECTED_FILES)
    missing = EXPECTED_FILES.difference(changed)
    if unexpected:
        raise SystemExit("unexpected projected files: " + ", ".join(sorted(unexpected)))
    if missing:
        raise SystemExit("expected projected files unchanged/missing: " + ", ".join(sorted(missing)))

    files_root = output / "files"
    file_rows = []
    for relative in sorted(changed):
        source = worktree / relative
        destination = files_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        file_rows.append(
            {
                "path": relative,
                "sha256": sha256(destination),
                "bytes": destination.stat().st_size,
            }
        )
    patch = subprocess.check_output(
        ["git", "-C", str(worktree), "diff", "--binary", "--", *sorted(changed)],
        text=True,
    )
    (output / "authoring.patch").write_text(patch, encoding="utf-8")
    manifest = {
        "schema": "hepta.learning-plasticity-runtime-hardening-projection.v1",
        "sourceCommit": subprocess.check_output(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "files": file_rows,
        "commands": results,
        "checksPassed": not failed,
        "claimBoundary": {
            "productionImplementation": False,
            "productExecutionProved": False,
            "targetHostEvidence": False,
            "independentAcceptance": False,
            "activation": False,
            "release": False,
        },
    }
    (output / "projection.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
