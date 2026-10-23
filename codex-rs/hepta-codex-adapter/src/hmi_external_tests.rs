use super::*;
use crate::hmi::tests::*;
use futures::StreamExt;
use tokio_tungstenite::accept_async;

#[tokio::test]
async fn interrupt_during_external_lookup_invalidates_admission_and_never_reopens_output() {
    let (listener, url) = listener().await;
    let peer = tokio::spawn(async move {
        let mut socket = accept_async(listener.accept().await.unwrap().0)
            .await
            .unwrap();
        initialize(&mut socket).await;
        let _ = socket.next().await;
    });
    let connection = HmiConnectionV1::connect(args(&url), binding(), 8, Duration::from_secs(3))
        .await
        .unwrap();
    let pending_lookup = connection.requests.owner_admission_fence().unwrap();
    connection.requests.stop_output(7).unwrap();
    assert_eq!(
        connection.requests.observe_owner_submission(
            pending_lookup,
            7,
            1,
            "hepta.authbus:first",
            "输入"
        ),
        Err(HmiError::Fenced)
    );
    // A distinct user intent after retirement has a newly minted owner fence.
    let new_intent = connection.requests.owner_admission_fence().unwrap();
    connection
        .requests
        .observe_owner_submission(new_intent, 7, 2, "hepta.authbus:second", "新的输入")
        .unwrap();
    connection.events.shutdown().await.unwrap();
    peer.await.unwrap();
}
