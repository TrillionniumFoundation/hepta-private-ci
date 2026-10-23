//! Bounded full-duplex link to the owned Pipecat media process. The caller owns
//! process supervision and drains `events.next()` concurrently with bridge
//! requests. This module starts no task and grants no authority. On link failure
//! the owner must close/join its media process, including capture/native workers.
use super::*;
#[path = "hmi_media_codec.rs"]
mod codec;
use codec::*;
#[path = "hmi_media_state.rs"]
mod state;
use serde_json::Value;
use serde_json::json;
use state::*;
use std::collections::BTreeMap;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncRead;
use tokio::io::AsyncWrite;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::sync::oneshot;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HmiMediaPresentationEventV1 {
    pub scope: HmiOutputScopeV1,
    pub state: HmiMediaPresentationV1,
    pub error: Option<String>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "type", rename_all = "camelCase")]
pub enum HmiOwnedMediaEventV1 {
    FinalTranscript {
        input: HmiOwnerTranscriptV1,
    },
    Interrupt {
        connection_id: u64,
        stream: HmiCaptureStreamV1,
        output_epoch: u64,
        local_error: Option<String>,
    },
    Presentation {
        observation: HmiMediaPresentationEventV1,
    },
    DisplayTranscript {
        stream: HmiCaptureStreamV1,
        text: String,
    },
    Terminal {
        connection_id: u64,
        diagnostic: Value,
    },
}
pub struct HmiJsonlMediaV1<W> {
    writer: Arc<WriterSlot<W>>,
    shared: Arc<MediaPendingState>,
    connection_id: u64,
    capture_generation: u64,
    timeout: Duration,
}
impl<W> Clone for HmiJsonlMediaV1<W> {
    fn clone(&self) -> Self {
        Self {
            writer: self.writer.clone(),
            shared: self.shared.clone(),
            connection_id: self.connection_id,
            capture_generation: self.capture_generation,
            timeout: self.timeout,
        }
    }
}
pub struct HmiJsonlMediaEventsV1<R> {
    reader: BufReader<R>,
    partial: Vec<u8>,
    shared: Arc<MediaPendingState>,
    connection_id: u64,
}
impl<W: AsyncWrite + Unpin + Send> HmiJsonlMediaV1<W> {
    /// Explicit retention acknowledgement by the existing trusted owner. Call
    /// only after its durable observation/media retention policy permits release.
    /// Matching an in-memory DTO does not authenticate the supplied receipt.
    pub async fn release_source(
        &self,
        input: &HmiOwnerTranscriptV1,
        receipt: &HmiObservationReceiptV1,
    ) -> Result<(), HmiError> {
        if input.connection_id != self.connection_id
            || receipt.observation_id.is_empty()
            || receipt.payload_sha256 != input.payload_sha256()?
        {
            return Err(HmiError::Identity);
        }
        self.command(
            "release_source",
            json!({"type":"release_source","source":input.source}),
        )
        .await
        .map(|_| ())
    }
    /// Bind pipes already created and authorized by the existing owner. The
    /// connection ID comes from its HmiRequestsV1, never from media JSON.
    pub fn bind<R: AsyncRead + Unpin>(
        connection_id: u64,
        capture_generation: u64,
        reader: R,
        writer: W,
        timeout: Duration,
    ) -> Result<(Self, HmiJsonlMediaEventsV1<R>), HmiError> {
        if connection_id == 0
            || capture_generation == 0
            || timeout.is_zero()
            || timeout > Duration::from_secs(30)
        {
            return Err(HmiError::Identity);
        }
        let shared = Arc::new(MediaPendingState {
            closed: AtomicBool::new(false),
            closed_notify: tokio::sync::Notify::new(),
            next: AtomicU64::new(1),
            pending: Mutex::new(BTreeMap::new()),
        });
        Ok((
            Self {
                writer: Arc::new(WriterSlot {
                    writer: Mutex::new(Some(writer)),
                    gate: tokio::sync::Semaphore::new(1),
                }),
                shared: shared.clone(),
                connection_id,
                capture_generation,
                timeout,
            },
            HmiJsonlMediaEventsV1 {
                reader: BufReader::new(reader),
                partial: Vec::new(),
                shared,
                connection_id,
            },
        ))
    }
    async fn command(&self, operation: &'static str, mut value: Value) -> Result<Value, HmiError> {
        if self.shared.closed.load(Ordering::SeqCst) {
            return Err(HmiError::Fenced);
        }
        let id = self
            .shared
            .next
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |n| n.checked_add(1))
            .map_err(|_| HmiError::Fenced)?;
        let (send, recv) = oneshot::channel();
        {
            let mut pending = self.shared.pending.lock().map_err(|_| HmiError::Fenced)?;
            if pending.len() >= 8 {
                return Err(HmiError::Busy);
            }
            pending.insert(
                id,
                Pending {
                    operation,
                    reply: send,
                },
            );
        }
        let _guard = RequestGuard {
            shared: self.shared.clone(),
            id,
        };
        value["request_id"] = json!(id);
        let mut bytes =
            serde_json::to_vec(&value).map_err(|e| HmiError::Protocol(e.to_string()))?;
        if bytes.len() > 65_535 {
            return Err(HmiError::Invalid("media command exceeds 64 KiB"));
        }
        bytes.push(b'\n');
        let result = tokio::time::timeout(self.timeout, async {
            let permit = self
                .writer
                .gate
                .acquire()
                .await
                .map_err(|_| HmiError::Fenced)?;
            if self.shared.closed.load(Ordering::SeqCst) {
                return Err(HmiError::Fenced);
            }
            let writer = self
                .writer
                .writer
                .lock()
                .map_err(|_| HmiError::Fenced)?
                .take()
                .ok_or(HmiError::Fenced)?;
            let mut lease = WriterLease {
                owner: self.writer.clone(),
                shared: self.shared.clone(),
                writer: Some(writer),
                reusable: false,
            };
            let writer = lease.writer.as_mut().ok_or(HmiError::Fenced)?;
            writer
                .write_all(&bytes)
                .await
                .map_err(|e| HmiError::Transport(e.to_string()))?;
            writer
                .flush()
                .await
                .map_err(|e| HmiError::Transport(e.to_string()))?;
            lease.reusable = true;
            drop(lease);
            drop(permit);
            recv.await.map_err(|_| HmiError::Fenced)?
        })
        .await
        .unwrap_or(Err(HmiError::Deadline));
        if let Err(error) = &result {
            self.shared.fail(error.clone());
            let writer = self
                .writer
                .writer
                .lock()
                .map_err(|_| HmiError::Fenced)?
                .take();
            if let Some(mut writer) = writer {
                let _ = tokio::time::timeout(self.timeout, writer.shutdown()).await;
            }
        }
        result
    }
}
impl<W: AsyncWrite + Unpin + Send> HmiOwnerMediaV1 for HmiJsonlMediaV1<W> {
    fn connection_id(&self) -> u64 {
        self.connection_id
    }
    fn capture_generation(&self) -> u64 {
        self.capture_generation
    }
    async fn verify_source(&self, source: &HmiCapturedAudioRefV1) -> Result<(), HmiError> {
        self.command(
            "verify_source",
            json!({"type":"verify_source","source":source}),
        )
        .await
        .map(|_| ())
    }
    async fn attach_turn(&self, scope: &HmiOutputScopeV1) -> Result<(), HmiError> {
        if scope.connection_id != self.connection_id {
            return Err(HmiError::Identity);
        }
        self.command("turn", json!({"type":"turn","scope":scope}))
            .await
            .map(|_| ())
    }
    async fn speak(&self, request: HmiSpeechRequestV1) -> Result<HmiMediaPresentationV1, HmiError> {
        let HmiSpeechRequestV1::Speak { scope, text } = request;
        if scope.connection_id != self.connection_id {
            return Err(HmiError::Identity);
        }
        let result = self
            .command("speak", json!({"type":"speak","scope":scope,"text":text}))
            .await?;
        if result["state"] != "queued" {
            return Err(HmiError::Identity);
        }
        Ok(HmiMediaPresentationV1::Queued)
    }
    async fn retire_output(&self, output_epoch: u64) -> Result<(), HmiError> {
        self.command(
            "retire",
            json!({"type":"retire","output_epoch":output_epoch}),
        )
        .await
        .map(|_| ())
    }
    async fn revoke_capture(&self) -> Result<(), HmiError> {
        self.command("revoke_capture", json!({"type":"revoke_capture"}))
            .await
            .map(|_| ())
    }
}
impl<R: AsyncRead + Unpin> HmiJsonlMediaEventsV1<R> {
    /// Cancellation-safe bounded reader. Acks wake the exact originating future;
    /// source/presentation/interrupt events go back to the same owner bridge.
    pub async fn next(&mut self) -> Result<HmiOwnedMediaEventV1, HmiError> {
        let result = self.read_event().await;
        if let Err(error) = &result {
            self.shared.fail(error.clone());
        }
        result
    }
    async fn read_event(&mut self) -> Result<HmiOwnedMediaEventV1, HmiError> {
        loop {
            let closed = self.shared.closed_notify.notified();
            tokio::pin!(closed);
            closed.as_mut().enable();
            if self.shared.closed.load(Ordering::SeqCst) {
                return Err(HmiError::Fenced);
            }
            let available = tokio::select! {
                _ = closed => return Err(HmiError::Fenced),
                read = self.reader.fill_buf() => read.map_err(|e|HmiError::Transport(e.to_string()))?,
            };
            if available.is_empty() {
                return Err(HmiError::Transport(
                    "media pipe closed before an owned terminal".into(),
                ));
            }
            let count = available
                .iter()
                .position(|b| *b == b'\n')
                .map_or(available.len(), |i| i + 1);
            if count > 65_536 - self.partial.len() {
                return Err(HmiError::Invalid("media event exceeds 64 KiB"));
            }
            self.partial.extend_from_slice(&available[..count]);
            self.reader.consume(count);
            if self.partial.last() != Some(&b'\n') {
                continue;
            }
            let raw: Value = serde_json::from_slice(&std::mem::take(&mut self.partial))
                .map_err(|e| HmiError::Protocol(e.to_string()))?;
            let event: NativeEvent = serde_json::from_value(raw.clone())
                .map_err(|e| HmiError::Protocol(e.to_string()))?;
            match event {
                NativeEvent::MediaAck {
                    request_id,
                    operation,
                    error,
                } => {
                    let result =
                        error.map_or_else(|| Ok(raw), |error| Err(HmiError::Transport(error)));
                    self.shared.ack(request_id, &operation, result)?;
                }
                NativeEvent::SourceTranscript { source, transcript } => {
                    if transcript
                        .result
                        .as_ref()
                        .and_then(|r| r.get("audio_source"))
                        != Some(
                            &serde_json::to_value(&source)
                                .map_err(|e| HmiError::Protocol(e.to_string()))?,
                        )
                    {
                        return Err(HmiError::Identity);
                    }
                    return Ok(HmiOwnedMediaEventV1::FinalTranscript {
                        input: HmiOwnerTranscriptV1 {
                            connection_id: self.connection_id,
                            source,
                            text: transcript.text,
                            finalized: transcript.finalized,
                        },
                    });
                }
                NativeEvent::TurnInterrupt {
                    stream,
                    request,
                    local_error,
                } => {
                    return Ok(HmiOwnedMediaEventV1::Interrupt {
                        connection_id: self.connection_id,
                        stream,
                        output_epoch: request.output_epoch,
                        local_error,
                    });
                }
                NativeEvent::Presentation {
                    identity,
                    state,
                    error,
                } => {
                    return Ok(HmiOwnedMediaEventV1::Presentation {
                        observation: HmiMediaPresentationEventV1 {
                            scope: identity.scope(self.connection_id),
                            state: match state {
                                NativePresentationState::Submitted => {
                                    HmiMediaPresentationV1::Submitted
                                }
                                NativePresentationState::Unknown => HmiMediaPresentationV1::Unknown,
                            },
                            error,
                        },
                    });
                }
                NativeEvent::UnboundTranscript { stream, transcript } => {
                    return Ok(HmiOwnedMediaEventV1::DisplayTranscript {
                        stream,
                        text: transcript.text,
                    });
                }
                NativeEvent::MediaTerminal {
                    request_id,
                    input_errors,
                } => {
                    let failures = [
                        "error",
                        "local_stop_error",
                        "input_error",
                        "cleanup_error",
                        "verification_error",
                    ]
                    .iter()
                    .any(|key| !raw[*key].is_null())
                        || input_errors != 0;
                    if let Some(id) = request_id {
                        let result = if failures {
                            Err(HmiError::Transport(raw.to_string()))
                        } else {
                            Ok(raw.clone())
                        };
                        self.shared.ack(id, "revoke_capture", result)?;
                    }
                    self.shared.fail(HmiError::Fenced);
                    return Ok(HmiOwnedMediaEventV1::Terminal {
                        connection_id: self.connection_id,
                        diagnostic: raw,
                    });
                }
            }
        }
    }
}
impl<R> Drop for HmiJsonlMediaEventsV1<R> {
    fn drop(&mut self) {
        self.shared.fail(HmiError::Fenced);
    }
}


