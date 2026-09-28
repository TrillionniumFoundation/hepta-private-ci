#!/usr/bin/env python3
"""Apply the reviewed memory.retrieval completion increment.

The transformer is deliberately exact: every edit has one source preimage and
must occur exactly once. It is run only after the assertion/delivery closure
materializer. It does not alter release or activation claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FILES = (
    "codex-rs/hepta-agentd/src/retrieval_executor.rs",
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "codex-rs/hepta-agentd/src/cognitive_retrieval_bootstrap.rs",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    expected_count = 2 if label in {
        "final sqlite publication fence",
        "ranker final fence bounded",
    } else 1
    count = text.count(old)
    if count != expected_count:
        raise ValueError(
            f"{label}: expected {expected_count} preimages, found {count}"
        )
    return text.replace(old, new, expected_count)


def update(path: Path, edits: list[tuple[str, str, str]]) -> dict[str, str]:
    before = path.read_text()
    after = before
    for label, old, new in edits:
        after = replace_once(after, old, new, label)
    if after == before:
        raise ValueError(f"{path}: transformation was empty")
    path.write_text(after)
    return {
        "path": path.as_posix(),
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
    }


def apply(root: Path) -> list[dict[str, str]]:
    executor = root / FILES[0]
    context = root / FILES[1]
    bootstrap = root / FILES[2]

    receipts: list[dict[str, str]] = []
    receipts.append(
        update(
            executor,
            [
                (
                    "executor future import",
                    "use std::sync::Arc;\nuse std::time::Duration;\n",
                    "use std::future::Future;\nuse std::sync::Arc;\nuse std::time::Duration;\n",
                ),
                (
                    "executor profile v2",
                    '            b"hepta.retrieval.executor.v1:delivery=2,800ms;shadow=1,40ms;work=250000;queue=0",\n',
                    '            b"hepta.retrieval.executor.v2:delivery=2,800ms;shadow=1,40ms;work=250000;queue=0;async=absolute-deadline",\n',
                ),
                (
                    "executor async deadline",
                    "    pub(crate) async fn run<T, F>(\n",
                    "    pub(crate) async fn run_async<T, F>(\n"
                    "        &self,\n"
                    "        request: &RetrievalRequestWork,\n"
                    "        operation: F,\n"
                    "    ) -> Result<T, String>\n"
                    "    where\n"
                    "        F: Future<Output = T>,\n"
                    "    {\n"
                    "        request.checkpoint()?;\n"
                    "        let value = tokio::time::timeout_at(\n"
                    "            tokio::time::Instant::from_std(request.deadline),\n"
                    "            operation,\n"
                    "        )\n"
                    "        .await\n"
                    "        .map_err(|_| {\n"
                    "            request.control.cancel();\n"
                    "            \"retrieval request deadline exceeded\".to_string()\n"
                    "        })?;\n"
                    "        request.checkpoint()?;\n"
                    "        Ok(value)\n"
                    "    }\n\n"
                    "    pub(crate) async fn run<T, F>(\n",
                ),
                (
                    "request checkpoint",
                    "impl Drop for RetrievalRequestWork {\n",
                    "impl RetrievalRequestWork {\n"
                    "    pub(crate) fn checkpoint(&self) -> Result<(), String> {\n"
                    "        if Instant::now() >= self.deadline {\n"
                    "            self.control.cancel();\n"
                    "            return Err(\"retrieval request deadline exceeded\".to_string());\n"
                    "        }\n"
                    "        self.control\n"
                    "            .checkpoint()\n"
                    "            .map_err(|error| error.to_string())\n"
                    "    }\n"
                    "}\n\n"
                    "impl Drop for RetrievalRequestWork {\n",
                ),
            ],
        )
    )

    receipts.append(
        update(
            context,
            [
                (
                    "sqlite snapshot deadline",
                    "    let cut = store.lane_c_snapshot(&access, &scope, now).await?;\n"
                    "    let observation = store\n"
                    "        .observe_memory_retrieval(&access, &RetrievalRequest::new(query, now))\n"
                    "        .await?;\n",
                    "    let cut = executor\n"
                    "        .run_async(&request_work, store.lane_c_snapshot(&access, &scope, now))\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;\n"
                    "    let observation = executor\n"
                    "        .run_async(\n"
                    "            &request_work,\n"
                    "            store.observe_memory_retrieval(\n"
                    "                &access,\n"
                    "                &RetrievalRequest::new(query, now),\n"
                    "            ),\n"
                    "        )\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;\n",
                ),
                (
                    "admission checkpoint",
                    "    let admission_read = cut\n"
                    "        .read_ids(ReadIdsRequestV1 {\n",
                    "    request_work\n"
                    "        .checkpoint()\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;\n"
                    "    let admission_read = cut\n"
                    "        .read_ids(ReadIdsRequestV1 {\n",
                ),
                (
                    "ranker bounded pool",
                    "        let (ranked_items, rank_observation) = tokio::task::spawn_blocking(move || {\n"
                    "            let observation = ranker.rank(\n"
                    "                &rank_owner,\n"
                    "                body_generation,\n"
                    "                &rank_query,\n"
                    "                &mut admitted_items,\n"
                    "            )?;\n"
                    "            Ok::<_, String>((admitted_items, observation))\n"
                    "        })\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RankerUnavailable)?\n"
                    "        .map_err(|_| CognitiveContextError::RankerUnavailable)?;\n",
                    "        let (ranked_items, rank_observation) = executor\n"
                    "            .run(&request_work, move |work| {\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                let observation = ranker.rank(\n"
                    "                    &rank_owner,\n"
                    "                    body_generation,\n"
                    "                    &rank_query,\n"
                    "                    &mut admitted_items,\n"
                    "                )?;\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                Ok((admitted_items, observation))\n"
                    "            })\n"
                    "            .await\n"
                    "            .map_err(|_| CognitiveContextError::RankerUnavailable)?;\n",
                ),
                (
                    "candidate revalidation deadline",
                    "    let statuses = store\n"
                    "        .revalidate_memory_candidates(&access, &ordered_bindings, now_seconds()?)\n"
                    "        .await?;\n",
                    "    let revalidation_now = now_seconds()?;\n"
                    "    let statuses = executor\n"
                    "        .run_async(\n"
                    "            &request_work,\n"
                    "            store.revalidate_memory_candidates(\n"
                    "                &access,\n"
                    "                &ordered_bindings,\n"
                    "                revalidation_now,\n"
                    "            ),\n"
                    "        )\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;\n",
                ),
                (
                    "revalidation snapshot deadline",
                    "    let cut = store\n"
                    "        .lane_c_snapshot(&access, &scope, now_seconds()?)\n"
                    "        .await?;\n",
                    "    let revalidation_snapshot_now = now_seconds()?;\n"
                    "    let cut = executor\n"
                    "        .run_async(\n"
                    "            &request_work,\n"
                    "            store.lane_c_snapshot(\n"
                    "                &access,\n"
                    "                &scope,\n"
                    "                revalidation_snapshot_now,\n"
                    "            ),\n"
                    "        )\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;\n",
                ),
                (
                    "final sqlite publication fence",
                    "    store\n"
                    "        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)\n"
                    "        .await?;\n",
                    "    let final_fence_now = now_seconds()?;\n"
                    "    executor\n"
                    "        .run_async(\n"
                    "            &request_work,\n"
                    "            store.revalidate_lane_c_snapshot(\n"
                    "                &access,\n"
                    "                &scope,\n"
                    "                &cut,\n"
                    "                final_fence_now,\n"
                    "            ),\n"
                    "        )\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)??;\n",
                ),
                (
                    "ranker final fence bounded",
                    "    if let Some(ranker) = ranker {\n"
                    "        let ranker = std::sync::Arc::clone(ranker);\n"
                    "        tokio::task::spawn_blocking(move || ranker.revalidate())\n"
                    "            .await\n"
                    "            .map_err(|_| CognitiveContextError::RankerUnavailable)?\n"
                    "            .map_err(|_| CognitiveContextError::RankerUnavailable)?;\n"
                    "    }\n",
                    "    if let Some(ranker) = ranker {\n"
                    "        let ranker = std::sync::Arc::clone(ranker);\n"
                    "        executor\n"
                    "            .run(&request_work, move |work| {\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                ranker.revalidate()?;\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                Ok(())\n"
                    "            })\n"
                    "            .await\n"
                    "            .map_err(|_| CognitiveContextError::RankerUnavailable)?;\n"
                    "    }\n",
                ),
                (
                    "ledger bounded pool",
                    "        let appended = tokio::task::spawn_blocking(move || {\n"
                    "            sink.append_with_delivery_policy(\n"
                    "                &owner,\n"
                    "                body_generation,\n"
                    "                request_id,\n"
                    "                &assignment,\n"
                    "                &delivered_candidates,\n"
                    "                context_exposed,\n"
                    "                published_context_digest,\n"
                    "                downstream_policy_digest,\n"
                    "                delivery_propensity,\n"
                    "            )\n"
                    "        })\n"
                    "        .await\n"
                    "        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)\n"
                    "        .and_then(|result| result.map_err(|_| CognitiveContextError::RetrievalLearningUnavailable));\n",
                    "        let appended = executor\n"
                    "            .run(&request_work, move |work| {\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                let receipt = sink.append_with_delivery_policy(\n"
                    "                    &owner,\n"
                    "                    body_generation,\n"
                    "                    request_id,\n"
                    "                    &assignment,\n"
                    "                    &delivered_candidates,\n"
                    "                    context_exposed,\n"
                    "                    published_context_digest,\n"
                    "                    downstream_policy_digest,\n"
                    "                    delivery_propensity,\n"
                    "                )?;\n"
                    "                work.checkpoint().map_err(|error| error.to_string())?;\n"
                    "                Ok(receipt)\n"
                    "            })\n"
                    "            .await\n"
                    "            .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable);\n",
                ),
            ],
        )
    )

    receipts.append(
        update(
            bootstrap,
            [
                (
                    "bootstrap provider timeout bound constant",
                    "const LEGACY_CANARY_COHORT_DOMAIN: &[u8] = b\"hepta.retrieval.default-canary-cohort.v1\";\n",
                    "const LEGACY_CANARY_COHORT_DOMAIN: &[u8] = b\"hepta.retrieval.default-canary-cohort.v1\";\n"
                    "const MAX_PROVIDER_REQUEST_TIMEOUT_MS: u64 = 800;\n",
                ),
                (
                    "bootstrap provider timeout admission",
                    "    let delivery = DeliverySettings::from_descriptor(&descriptor)?;\n"
                    "    if descriptor.owner_id != identity.agent_id.as_str()\n",
                    "    let delivery = DeliverySettings::from_descriptor(&descriptor)?;\n"
                    "    if descriptor.request_timeout_ms == 0\n"
                    "        || descriptor.request_timeout_ms > MAX_PROVIDER_REQUEST_TIMEOUT_MS\n"
                    "    {\n"
                    "        return Err(\n"
                    "            \"retrieval frontier timeout must fit the 1..=800ms host delivery budget\"\n"
                    "                .to_string(),\n"
                    "        );\n"
                    "    }\n"
                    "    if descriptor.owner_id != identity.agent_id.as_str()\n",
                ),
            ],
        )
    )
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    receipts = apply(root)
    output = json.dumps(
        {
            "schema": "hepta.memory-retrieval.completion-transform.v2",
            "files": receipts,
            "production_activation": False,
            "release": False,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.receipt is None:
        print(output, end="")
    else:
        args.receipt.write_text(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
