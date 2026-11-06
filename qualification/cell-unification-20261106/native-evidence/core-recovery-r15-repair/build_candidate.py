import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
COMMIT = "638997499470f0b7dd33ad18226feacf0198ef3d"
TREE = "1646e1656cf6365e74accae19a1225fd2ce6d964"
HELPER = "codex-rs/core/tests/common/streaming_sse.rs"
SUITE = "codex-rs/core/tests/suite/turn_input_submission.rs"
EXPECTED = {
    HELPER: (
        "ed1e35fa973116adf94c8ddbb39bb7e0d2c4c7773b980277921f859ce40d252b",
        "3766bbd88084f0ba514df52143918450be7d21eb",
    ),
    SUITE: (
        "ae71b734d0b46ce5b285afc827d765d0a4a066bbe825ffd0aba467a4d78e1824",
        "4ee793ddfc1a9592c933e8b861e76d46bf111c40",
    ),
}


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
        "mode": "100644",
    }


edits = {HELPER: [], SUITE: []}


def edit(path, before, after):
    edits[path].append({"before": before, "after": after})


edit(
    HELPER,
    """pub async fn start_streaming_sse_server(
    responses: Vec<Vec<StreamingSseChunk>>,
) -> (StreamingSseServer, Vec<oneshot::Receiver<i64>>) {
    let listener = TcpListener::bind("127.0.0.1:0")
""",
    """pub async fn start_streaming_sse_server(
    responses: Vec<Vec<StreamingSseChunk>>,
) -> (StreamingSseServer, Vec<oneshot::Receiver<i64>>) {
    start_streaming_sse_server_with_initial_response_gate(
        responses,
        /*initial_response_gate*/ None,
    )
    .await
}

/// Records the initial response request, then waits for its optional gate before
/// sending HTTP headers or SSE chunks. Dropping the sender closes that response
/// without sending either; subsequent queued responses keep their chunk gates.
pub async fn start_streaming_sse_server_with_initial_response_gate(
    responses: Vec<Vec<StreamingSseChunk>>,
    initial_response_gate: Option<oneshot::Receiver<()>>,
) -> (StreamingSseServer, Vec<oneshot::Receiver<i64>>) {
    let listener = TcpListener::bind("127.0.0.1:0")
""",
)
edit(
    HELPER,
    """        responses: VecDeque::from(responses),
        completions: VecDeque::from(completion_senders),
""",
    """        responses: VecDeque::from(responses),
        completions: VecDeque::from(completion_senders),
        initial_response_gate,
""",
)
edit(
    HELPER,
    """                            let Some((chunks, completion)) = take_next_stream(&state).await else {
                                let _ = write_http_response(&mut stream, /*status*/ 500, "no responses queued", "text/plain").await;
                                return;
                            };

                            if write_sse_headers(&mut stream).await.is_err() {
""",
    """                            let Some(StreamingSseResponse { chunks, completion, headers_gate }) = take_next_stream(&state).await else {
                                let _ = write_http_response(&mut stream, /*status*/ 500, "no responses queued", "text/plain").await;
                                return;
                            };

                            if let Some(gate) = headers_gate
                                && gate.await.is_err() {
                                    return;
                                }

                            if write_sse_headers(&mut stream).await.is_err() {
""",
)
edit(
    HELPER,
    """struct StreamingSseState {
    responses: VecDeque<Vec<StreamingSseChunk>>,
    completions: VecDeque<oneshot::Sender<i64>>,
}

async fn take_next_stream(
    state: &TokioMutex<StreamingSseState>,
) -> Option<(Vec<StreamingSseChunk>, oneshot::Sender<i64>)> {
    let mut guard = state.lock().await;
    let chunks = guard.responses.pop_front()?;
    let completion = guard.completions.pop_front()?;
    Some((chunks, completion))
}
""",
    """struct StreamingSseState {
    responses: VecDeque<Vec<StreamingSseChunk>>,
    completions: VecDeque<oneshot::Sender<i64>>,
    initial_response_gate: Option<oneshot::Receiver<()>>,
}

struct StreamingSseResponse {
    chunks: Vec<StreamingSseChunk>,
    completion: oneshot::Sender<i64>,
    headers_gate: Option<oneshot::Receiver<()>>,
}

async fn take_next_stream(state: &TokioMutex<StreamingSseState>) -> Option<StreamingSseResponse> {
    let mut guard = state.lock().await;
    let chunks = guard.responses.pop_front()?;
    let completion = guard.completions.pop_front()?;
    let headers_gate = guard.initial_response_gate.take();
    Some(StreamingSseResponse {
        chunks,
        completion,
        headers_gate,
    })
}
""",
)
edit(
    HELPER,
    """            completions: VecDeque::from(vec![first_tx, second_tx]),
        });

        let (first_chunks, first_completion) =
            take_next_stream(&state).await.expect("first stream");
""",
    """            completions: VecDeque::from(vec![first_tx, second_tx]),
            initial_response_gate: None,
        });

        let StreamingSseResponse {
            chunks: first_chunks,
            completion: first_completion,
            ..
        } = take_next_stream(&state).await.expect("first stream");
""",
)
edit(
    HELPER,
    """        let (second_chunks, second_completion) =
            take_next_stream(&state).await.expect("second stream");
""",
    """        let StreamingSseResponse {
            chunks: second_chunks,
            completion: second_completion,
            ..
        } = take_next_stream(&state).await.expect("second stream");
""",
)
edit(
    SUITE,
    "use core_test_support::streaming_sse::start_streaming_sse_server;\n",
    "use core_test_support::streaming_sse::start_streaming_sse_server;\n"
    "use core_test_support::streaming_sse::start_streaming_sse_server_with_initial_response_gate;\n",
)
edit(
    SUITE,
    """    let (server, _completions) = start_streaming_sse_server(vec![
        vec![
            StreamingSseChunk {
                // Recovery ends when the first provider event reaches the turn
                // executor, including response.created. Keep that event gated.
                gate: Some(first_response_gate),
                body: responses::sse(vec![ev_response_created("resp-interrupted")]),
            },
            StreamingSseChunk {
                gate: None,
                body: responses::sse(vec![ev_completed("resp-interrupted")]),
            },
        ],
        vec![StreamingSseChunk {
            gate: None,
            body: responses::sse(vec![
                ev_response_created("resp-recovered"),
                ev_completed("resp-recovered"),
            ]),
        }],
    ])
    .await;
""",
    """    // HTTP headers produce a RateLimits event before any SSE chunk. Hold the
    // initial response before its headers so recovery stays before provider output.
    let (server, _completions) = start_streaming_sse_server_with_initial_response_gate(
        vec![
            vec![
                StreamingSseChunk {
                    gate: None,
                    body: responses::sse(vec![ev_response_created("resp-interrupted")]),
                },
                StreamingSseChunk {
                    gate: None,
                    body: responses::sse(vec![ev_completed("resp-interrupted")]),
                },
            ],
            vec![StreamingSseChunk {
                gate: None,
                body: responses::sse(vec![
                    ev_response_created("resp-recovered"),
                    ev_completed("resp-recovered"),
                ]),
            }],
        ],
        Some(first_response_gate),
    )
    .await;
""",
)

patch_parts = []
manifest = {
    "schema": "hepta.fixture-repair-source.v1",
    "base_commit": COMMIT,
    "base_tree": TREE,
    "files": [],
    "rust_commands_executed": False,
    "candidate_executed": False,
}
for path, operations in edits.items():
    before_bytes = (ROOT / "original" / path).read_bytes()
    before_identity = identity(before_bytes)
    assert (before_identity["sha256"], before_identity["git_blob"]) == EXPECTED[path]
    before = before_bytes.decode("utf-8")
    after = before
    for operation in operations:
        assert after.count(operation["before"]) == 1, (path, operation["before"])
        after = after.replace(operation["before"], operation["after"], 1)
    reverse = after
    for operation in reversed(operations):
        assert reverse.count(operation["after"]) == 1
        reverse = reverse.replace(operation["after"], operation["before"], 1)
    assert reverse.encode("utf-8") == before_bytes
    assert "#[allow" not in "".join(x["after"] for x in operations)
    for operation in operations:
        # Every existing assertion lies outside the replacement regions.
        assert "assert!" not in operation["before"]
        assert "assert_eq!" not in operation["before"]
        assert "assert_ne!" not in operation["before"]
    output = ROOT / "source" / path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(after.encode("utf-8"))
    diff = list(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    patch_parts.extend(diff)
    manifest["files"].append(
        {
            "path": path,
            "before": before_identity,
            "after": identity(output.read_bytes()),
            "edit_count": len(operations),
            "added_lines": sum(x.startswith("+") and not x.startswith("+++") for x in diff),
            "removed_lines": sum(x.startswith("-") and not x.startswith("---") for x in diff),
            "exact_inverse_to_stage44": True,
            "original_assertions_outside_edit_regions": True,
        }
    )

patch = "".join(patch_parts).encode("utf-8")
(ROOT / "repair.patch").write_bytes(patch)
manifest["patch"] = {"path": "repair.patch", **identity(patch)}
(ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
(ROOT / "edit-operations.json").write_text(json.dumps(edits, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
