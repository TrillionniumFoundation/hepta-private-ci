//! Executable experimental PoN relation. No production-hardness or mining-network claim.
//! Full-transcript work on challenge-encoded matrices; verification recomputes it.
use sha2::{Digest, Sha256};

pub mod arithmetic_facts;
pub mod artifacts;
pub mod blocked_one_zero;
pub mod blocked_zero;
pub mod blocked_zero_paired;
pub mod facts;
mod integer_paired;
pub mod legal_attempt;
pub mod maintenance_limb;
pub mod maintenance_periodic;
pub mod maintenance_prefix;
pub mod paired_product;
pub mod rejection_cache;
pub mod structured;

pub const PROFILE: &str = "pon-matmul-transcript-64-v1";
pub const N: usize = 64;
pub const R: usize = 8;
pub const Q: u128 = 4_294_967_291;
pub const CELLS: usize = N * N;
pub const PROOF_BYTES: usize = 4 + 3 * CELLS * 4 + 32;
pub type Hash = [u8; 32];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkError {
    Length,
    Version,
    Field,
    Task,
    Transcript,
    Product,
    Target,
    NoiseBudget,
}

/// Allocation-free rejection of malformed PNW1 bytes before task or State lookup.
/// Success checks only the fixed encoding, never the task, target or relation.
/// The original full verifier still performs its checks in their original order
/// and is the only path here that can construct VerifiedWork.
pub fn precheck_proof_encoding(bytes: &[u8]) -> Result<(), WorkError> {
    if bytes.len() != PROOF_BYTES {
        return Err(WorkError::Length);
    }
    if &bytes[..4] != b"PNW1" {
        return Err(WorkError::Version);
    }
    // Every A/B/C word must already be canonical; never reduce caller bytes.
    // The final transcript digest is opaque bytes, not another field element.
    if bytes[4..4 + 3 * CELLS * 4]
        .chunks_exact(4)
        .any(|p| u128::from(u32::from_le_bytes([p[0], p[1], p[2], p[3]])) >= Q)
    {
        return Err(WorkError::Field);
    }
    Ok(())
}

/// Allocation-free statement filter before a receiver restores parent State.
/// It binds the canonical A/B bytes and claimed ticket to this exact header;
/// passing does not check the transcript/product or construct VerifiedWork.
/// The full verifier's original validation and error order remain unchanged.
pub fn precheck_proof_statement(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<(), WorkError> {
    precheck_proof_encoding(bytes)?;
    if target == [0; 32] {
        return Err(WorkError::Target);
    }
    let actual_task = hash(
        b"task",
        &[
            &bytes[4..4 + CELLS * 4],
            &bytes[4 + CELLS * 4..4 + CELLS * 8],
        ],
    );
    if actual_task != expected_task {
        return Err(WorkError::Task);
    }
    let trace_claim = &bytes[4 + 3 * CELLS * 4..];
    if hash(b"ticket", &[&challenge, trace_claim]) > target {
        return Err(WorkError::Target);
    }
    Ok(())
}

/// Local observation boundaries; these are neither proof bytes nor consensus input.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerificationProgress {
    BeforeReplay,
    Noise {
        label: u8,
        counter: u32,
    },
    MatrixRow {
        row: usize,
    },
    TranscriptTile {
        row: usize,
        column: usize,
        inner: usize,
    },
    BeforeProduct,
    BeforeVerifiedWork,
}

/// An abandoned local computation does not assert that the relation is invalid.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VerificationError<E> {
    Relation(WorkError),
    Cancelled(E),
}
impl<E> From<WorkError> for VerificationError<E> {
    fn from(error: WorkError) -> Self {
        Self::Relation(error)
    }
}
fn relation_only<T>(
    result: Result<T, VerificationError<std::convert::Infallible>>,
) -> Result<T, WorkError> {
    match result {
        Ok(value) => Ok(value),
        Err(VerificationError::Relation(error)) => Err(error),
        Err(VerificationError::Cancelled(impossible)) => match impossible {},
    }
}
fn no_cancellation(_: VerificationProgress) -> Result<(), std::convert::Infallible> {
    Ok(())
}

/// A successful relation check for an exact caller-supplied statement, not a capability.
#[derive(Debug)]
pub struct VerifiedWork {
    challenge: Hash,
    task: Hash,
    ticket: Hash,
    product: Vec<u32>,
}
impl VerifiedWork {
    pub fn challenge(&self) -> Hash {
        self.challenge
    }
    pub fn task(&self) -> Hash {
        self.task
    }
    pub fn ticket(&self) -> Hash {
        self.ticket
    }
    pub fn product(&self) -> &[u32] {
        &self.product
    }
}

pub fn hash(tag: &[u8], parts: &[&[u8]]) -> Hash {
    let mut h = Sha256::new();
    h.update(b"TRNM-PON1\0");
    h.update((tag.len() as u16).to_le_bytes());
    h.update(tag);
    for p in parts {
        h.update((p.len() as u32).to_le_bytes());
        h.update(p);
    }
    h.finalize().into()
}
fn field_bytes(values: &[u32]) -> Vec<u8> {
    values.iter().flat_map(|v| v.to_le_bytes()).collect()
}
fn validate(values: &[u32]) -> Result<(), WorkError> {
    if values.len() != CELLS {
        return Err(WorkError::Length);
    }
    if values.iter().any(|v| u128::from(*v) >= Q) {
        return Err(WorkError::Field);
    }
    Ok(())
}
pub fn task_id(a: &[u32], b: &[u32]) -> Result<Hash, WorkError> {
    validate(a)?;
    validate(b)?;
    Ok(hash(b"task", &[&field_bytes(a), &field_bytes(b)]))
}
fn expand(challenge: Hash, label: u8, len: usize) -> Result<Vec<u32>, WorkError> {
    relation_only(expand_with_progress(
        challenge,
        label,
        len,
        &mut no_cancellation,
    ))
}
fn expand_with_progress<E>(
    challenge: Hash,
    label: u8,
    len: usize,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, VerificationError<E>> {
    let mut out = Vec::with_capacity(len);
    let mut counter = 0_u32;
    while out.len() < len {
        if counter >= 128 {
            return Err(WorkError::NoiseBudget.into());
        }
        progress(VerificationProgress::Noise { label, counter })
            .map_err(VerificationError::Cancelled)?;
        let bytes = hash(b"noise", &[&challenge, &[label], &counter.to_le_bytes()]);
        for pair in bytes.chunks_exact(4) {
            let v = u32::from_le_bytes([pair[0], pair[1], pair[2], pair[3]]);
            if u128::from(v) < Q {
                out.push(v);
                if out.len() == len {
                    break;
                }
            }
        }
        counter += 1;
    }
    Ok(out)
}
#[cfg(test)]
fn mul(a: &[u32], b: &[u32], rows: usize, inner: usize, cols: usize) -> Vec<u32> {
    match mul_with_progress(a, b, rows, inner, cols, &mut no_cancellation) {
        Ok(product) => product,
        Err(impossible) => match impossible {},
    }
}
fn mul_with_progress<E>(
    a: &[u32],
    b: &[u32],
    rows: usize,
    inner: usize,
    cols: usize,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    let mut out = vec![0; rows * cols];
    for i in 0..rows {
        progress(VerificationProgress::MatrixRow { row: i })?;
        for j in 0..cols {
            let mut sum = 0_u128;
            for k in 0..inner {
                sum += u128::from(a[i * inner + k]) * u128::from(b[k * cols + j]);
            }
            out[i * cols + j] = (sum % Q) as u32;
        }
    }
    Ok(out)
}
// Operation-local arithmetic intermediates, never a verified-work capability or cache.
struct TranscriptEvaluation {
    cp: Vec<u32>,
    el: Vec<u32>,
    er: Vec<u32>,
    fl: Vec<u32>,
    fr: Vec<u32>,
    bp: Vec<u32>,
    trace: Hash,
}

// Keep the independently coded scalar path's row-major intermediates unchanged.
// Optimized replay owns exactly one representation of B': the column kernel
// retains rows, while the other kernels retain the transpose already used by
// every transcript tile. Neither representation carries verification authority.
enum ReplayedRightOperand {
    RowMajor(Vec<u32>),
    Transposed(Vec<u32>),
}

struct OptimizedTranscriptEvaluation {
    cp: Vec<u32>,
    el: Vec<u32>,
    er: Vec<u32>,
    fl: Vec<u32>,
    fr: Vec<u32>,
    right: ReplayedRightOperand,
    trace: Hash,
}

enum ReplayedTranscript {
    Reference(TranscriptEvaluation),
    Optimized(OptimizedTranscriptEvaluation),
}

impl ReplayedTranscript {
    fn trace(&self) -> &Hash {
        match self {
            Self::Reference(evaluated) => &evaluated.trace,
            Self::Optimized(evaluated) => &evaluated.trace,
        }
    }
}

fn evaluate_transcript(
    challenge: Hash,
    a: &[u32],
    b: &[u32],
) -> Result<TranscriptEvaluation, WorkError> {
    relation_only(evaluate_transcript_with_progress(
        challenge,
        a,
        b,
        &mut no_cancellation,
    ))
}
fn evaluate_transcript_with_progress<E>(
    challenge: Hash,
    a: &[u32],
    b: &[u32],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<TranscriptEvaluation, VerificationError<E>> {
    validate(a)?;
    validate(b)?;
    let el = expand_with_progress(challenge, 0, N * R, progress)?;
    let er = expand_with_progress(challenge, 1, R * N, progress)?;
    let fl = expand_with_progress(challenge, 2, N * R, progress)?;
    let fr = expand_with_progress(challenge, 3, R * N, progress)?;
    let e = mul_with_progress(&el, &er, N, R, N, progress).map_err(VerificationError::Cancelled)?;
    let f = mul_with_progress(&fl, &fr, N, R, N, progress).map_err(VerificationError::Cancelled)?;
    let ap: Vec<u32> = a
        .iter()
        .zip(e)
        .map(|(x, y)| ((u128::from(*x) + u128::from(y)) % Q) as u32)
        .collect();
    let bp: Vec<u32> = b
        .iter()
        .zip(f)
        .map(|(x, y)| ((u128::from(*x) + u128::from(y)) % Q) as u32)
        .collect();
    let mut cp = vec![0_u32; CELLS];
    let mut transcript = Sha256::new();
    transcript.update(b"TRNM-PON-TRACE1\0");
    transcript.update(challenge);
    for bi in 0..N / R {
        for bj in 0..N / R {
            for bk in 0..N / R {
                progress(VerificationProgress::TranscriptTile {
                    row: bi,
                    column: bj,
                    inner: bk,
                })
                .map_err(VerificationError::Cancelled)?;
                for i in bi * R..(bi + 1) * R {
                    for j in bj * R..(bj + 1) * R {
                        let mut sum = u128::from(cp[i * N + j]);
                        for k in bk * R..(bk + 1) * R {
                            sum += u128::from(ap[i * N + k]) * u128::from(bp[k * N + j]);
                        }
                        cp[i * N + j] = (sum % Q) as u32;
                        transcript.update(cp[i * N + j].to_le_bytes());
                    }
                }
            }
        }
    }
    Ok(TranscriptEvaluation {
        cp,
        el,
        er,
        fl,
        fr,
        bp,
        trace: transcript.finalize().into(),
    })
}

#[cfg(test)]
thread_local! {
    static PRODUCT_RECONSTRUCTIONS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    static ARITHMETIC_TRANSCRIPT_REPLAYS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    static ARITHMETIC_TRANSCRIPT_COMPLETIONS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    static ARITHMETIC_INPUT_DECODES: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}

fn finish_product(a: &[u32], evaluated: TranscriptEvaluation) -> Vec<u32> {
    match finish_product_with_progress(a, evaluated, &mut no_cancellation) {
        Ok(product) => product,
        Err(impossible) => match impossible {},
    }
}
fn finish_product_with_progress<E>(
    a: &[u32],
    evaluated: TranscriptEvaluation,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    progress(VerificationProgress::BeforeProduct)?;
    #[cfg(test)]
    PRODUCT_RECONSTRUCTIONS.with(|count| count.set(count.get() + 1));
    let left = mul_with_progress(a, &evaluated.fl, N, N, R, progress)?;
    let correction1 = mul_with_progress(&left, &evaluated.fr, N, R, N, progress)?;
    let right = mul_with_progress(&evaluated.er, &evaluated.bp, R, N, N, progress)?;
    let correction2 = mul_with_progress(&evaluated.el, &right, N, R, N, progress)?;
    Ok(evaluated
        .cp
        .iter()
        .zip(correction1)
        .zip(correction2)
        .map(|((x, y), z)| ((u128::from(*x) + 2 * Q - u128::from(y) - u128::from(z)) % Q) as u32)
        .collect())
}

/// Exact useful matrix product plus the bound transcript digest.
/// The entire fixed-size job is evaluated; no proof-randomness lottery is offered.
pub fn evaluate(challenge: Hash, a: &[u32], b: &[u32]) -> Result<(Vec<u32>, Hash), WorkError> {
    let evaluated = evaluate_transcript(challenge, a, b)?;
    let trace = evaluated.trace;
    Ok((finish_product(a, evaluated), trace))
}
pub fn prove(challenge: Hash, a: &[u32], b: &[u32]) -> Result<Vec<u8>, WorkError> {
    let (product, trace) = evaluate(challenge, a, b)?;
    let mut out = Vec::with_capacity(PROOF_BYTES);
    out.extend_from_slice(b"PNW1");
    for matrix in [a, b, &product] {
        out.extend_from_slice(&field_bytes(matrix));
    }
    out.extend_from_slice(&trace);
    Ok(out)
}
/// Draft native default using exact bounded limb sums for the complete relation.
/// This implementation selection does not qualify work hardness or public service.
pub fn verify(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}
/// Full PNW1 replay with bounded limb arithmetic and caller-local cancellation.
/// A callback error drops all intermediates; only complete success creates VerifiedWork.
/// Checkpoints bound arithmetic between observations, not physical CPU time or preemption.
pub fn verify_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::FullLimb,
    )
}

/// Retained transposed baseline using exact reduction of u128 dot-product sums.
/// Explicit selection keeps historical measurements independent of the default.
pub fn verify_transposed(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_transposed_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}

/// Retained transposed replay with the same ordered cancellation checkpoints.
pub fn verify_transposed_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::Transposed,
    )
}

/// Explicit transcript-only arithmetic research comparison.
/// Replays the identical relation and observation sequence, replacing only each
/// eight-product transcript accumulation with exact bounded u64 limb sums.
pub fn verify_limb(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_limb_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}

pub fn verify_limb_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::LimbTranscript,
    )
}

/// Explicit full-replay candidate using bounded u64 limb sums for every
/// matrix multiplication, including noise and product corrections. The default
/// currently selects this same kernel; this entry keeps its explicit identity.
pub fn verify_full_limb(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_full_limb_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}

pub fn verify_full_limb_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::FullLimb,
    )
}

/// Explicit complete-replay comparison with eight independent column accumulators.
/// The retained transposed and scalar reference paths remain unchanged. This
/// changes memory access and exact integer accumulation, never the work relation.
pub fn verify_column_limb(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_column_limb_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}

pub fn verify_column_limb_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::ColumnLimbTranscript,
    )
}

/// Retained scalar verifier for differential checks and explicitly named cost baselines.
/// This follows the same admission grammar but uses the original u128 remainder,
/// row-major multiplication and per-cell transcript updates for the full relation.
pub fn verify_reference(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<VerifiedWork, WorkError> {
    relation_only(verify_reference_with_progress(
        challenge,
        expected_task,
        target,
        bytes,
        &mut no_cancellation,
    ))
}

pub fn verify_reference_with_progress<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<VerifiedWork, VerificationError<E>> {
    verify_with_kernel(
        challenge,
        expected_task,
        target,
        bytes,
        progress,
        VerificationKernel::ScalarReference,
    )
}

#[derive(Clone, Copy)]
enum VerificationKernel {
    ScalarReference,
    Transposed,
    LimbTranscript,
    ColumnLimbTranscript,
    FullLimb,
}

struct CheckedProofInputs {
    matrices: Vec<u32>,
    actual_task: Hash,
    ticket: Hash,
}

// Current canonical bytes and cheap statement checks only, never a work fact.
// Borrowing the immutable proof lets cache lookup precede the 32-KiB A/B
// allocation. Only an actual arithmetic replay needs decoded input matrices.
struct CheckedProofStatement<'a> {
    inputs: &'a [u8],
    actual_task: Hash,
    ticket: Hash,
}
impl CheckedProofStatement<'_> {
    fn decode_inputs(&self) -> Vec<u32> {
        #[cfg(test)]
        ARITHMETIC_INPUT_DECODES.with(|count| count.set(count.get() + 1));
        self.inputs
            .chunks_exact(4)
            .map(|p| u32::from_le_bytes([p[0], p[1], p[2], p[3]]))
            .collect()
    }
}

// Preserve the complete original optimized cheap-check order before any cache
// access or callback. This deliberately differs from the wire-only precheck.
fn checked_proof_statement(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
) -> Result<CheckedProofStatement<'_>, WorkError> {
    if bytes.len() != PROOF_BYTES {
        return Err(WorkError::Length);
    }
    if &bytes[..4] != b"PNW1" {
        return Err(WorkError::Version);
    }
    if target == [0; 32] {
        return Err(WorkError::Target);
    }
    // Preserve C, A, B field-error precedence before task, ticket and
    // callbacks. Exact fixed slices need no allocation, unaligned cast,
    // host-endian assumption or reduction of noncanonical input words.
    for matrix in [2, 0, 1] {
        let start = 4 + matrix * CELLS * 4;
        if bytes[start..start + CELLS * 4]
            .chunks_exact(4)
            .any(|p| u128::from(u32::from_le_bytes([p[0], p[1], p[2], p[3]])) >= Q)
        {
            return Err(WorkError::Field);
        }
    }
    // These are the current canonical bytes, not a cached task verdict.
    let actual_task = hash(
        b"task",
        &[
            &bytes[4..4 + CELLS * 4],
            &bytes[4 + CELLS * 4..4 + CELLS * 8],
        ],
    );
    if actual_task != expected_task {
        return Err(WorkError::Task);
    }
    let trace_claim: &[u8] = &bytes[4 + 3 * CELLS * 4..];
    // Cheap ticket rejection before expensive transcript verification is only an admission filter.
    // A passing filter alone never constructs VerifiedWork.
    let ticket = hash(b"ticket", &[&challenge, trace_claim]);
    if ticket > target {
        return Err(WorkError::Target);
    }
    Ok(CheckedProofStatement {
        inputs: &bytes[4..4 + 2 * CELLS * 4],
        actual_task,
        ticket,
    })
}

fn checked_proof_inputs(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    kernel: VerificationKernel,
) -> Result<CheckedProofInputs, WorkError> {
    if !matches!(kernel, VerificationKernel::ScalarReference) {
        let checked = checked_proof_statement(challenge, expected_task, target, bytes)?;
        return Ok(CheckedProofInputs {
            matrices: checked.decode_inputs(),
            actual_task: checked.actual_task,
            ticket: checked.ticket,
        });
    }
    // Retain the scalar reference's original three-matrix decoding and
    // independent field re-encoding, including its original error order.
    if bytes.len() != PROOF_BYTES {
        return Err(WorkError::Length);
    }
    if &bytes[..4] != b"PNW1" {
        return Err(WorkError::Version);
    }
    if target == [0; 32] {
        return Err(WorkError::Target);
    }
    let matrices = bytes[4..4 + 3 * CELLS * 4]
        .chunks_exact(4)
        .map(|p| u32::from_le_bytes([p[0], p[1], p[2], p[3]]))
        .collect::<Vec<_>>();
    let (a, tail) = matrices.split_at(CELLS);
    let (b, claimed) = tail.split_at(CELLS);
    validate(claimed)?;
    let actual_task = task_id(a, b)?;
    if actual_task != expected_task {
        return Err(WorkError::Task);
    }
    let trace_claim = &bytes[4 + 3 * CELLS * 4..];
    let ticket = hash(b"ticket", &[&challenge, trace_claim]);
    if ticket > target {
        return Err(WorkError::Target);
    }
    Ok(CheckedProofInputs {
        matrices,
        actual_task,
        ticket,
    })
}

fn verify_with_kernel<E>(
    challenge: Hash,
    expected_task: Hash,
    target: Hash,
    bytes: &[u8],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
    kernel: VerificationKernel,
) -> Result<VerifiedWork, VerificationError<E>> {
    let CheckedProofInputs {
        matrices,
        actual_task,
        ticket,
    } = checked_proof_inputs(challenge, expected_task, target, bytes, kernel)?;
    let (a, tail) = matrices.split_at(CELLS);
    let (b, claimed) = tail.split_at(CELLS);
    let claimed_bytes = &bytes[4 + 2 * CELLS * 4..4 + 3 * CELLS * 4];
    let trace_claim = &bytes[4 + 3 * CELLS * 4..];
    progress(VerificationProgress::BeforeReplay).map_err(VerificationError::Cancelled)?;
    let evaluated = match kernel {
        VerificationKernel::ScalarReference => ReplayedTranscript::Reference(
            evaluate_transcript_with_progress(challenge, a, b, progress)?,
        ),
        VerificationKernel::Transposed => ReplayedTranscript::Optimized(
            evaluate_transposed_with_progress::<false, E>(challenge, a, b, progress)?,
        ),
        VerificationKernel::LimbTranscript => ReplayedTranscript::Optimized(
            evaluate_transposed_with_progress::<true, E>(challenge, a, b, progress)?,
        ),
        VerificationKernel::ColumnLimbTranscript => {
            ReplayedTranscript::Optimized(evaluate_transcript_kernel_with_progress::<
                false,
                true,
                false,
                E,
            >(challenge, a, b, progress)?)
        }
        VerificationKernel::FullLimb => {
            ReplayedTranscript::Optimized(evaluate_transcript_kernel_with_progress::<
                true,
                false,
                true,
                E,
            >(challenge, a, b, progress)?)
        }
    };
    // PNW1 submits only a final digest: every transcript update is still replayed.
    // A mismatch skips product corrections; a matching digest is not yet VerifiedWork.
    if evaluated.trace().as_slice() != trace_claim {
        return Err(WorkError::Transcript.into());
    }
    let product = match evaluated {
        ReplayedTranscript::Reference(evaluated) => {
            finish_product_with_progress(a, evaluated, progress)
        }
        ReplayedTranscript::Optimized(evaluated) => {
            if matches!(kernel, VerificationKernel::FullLimb) {
                finish_transposed_kernel_with_progress::<true, E>(a, evaluated, progress)
            } else {
                finish_transposed_with_progress(a, evaluated, progress)
            }
        }
    }
    .map_err(VerificationError::Cancelled)?;
    let matches_claim = match kernel {
        VerificationKernel::ScalarReference => product == claimed,
        VerificationKernel::Transposed
        | VerificationKernel::LimbTranscript
        | VerificationKernel::FullLimb
        | VerificationKernel::ColumnLimbTranscript => product
            .iter()
            .flat_map(|word| word.to_le_bytes())
            .eq(claimed_bytes.iter().copied()),
    };
    if !matches_claim {
        return Err(WorkError::Product.into());
    }
    progress(VerificationProgress::BeforeVerifiedWork).map_err(VerificationError::Cancelled)?;
    Ok(VerifiedWork {
        challenge,
        task: actual_task,
        ticket,
        product,
    })
}

// q = 2^32 - 5. A transcript sum is below 2^70; two folds followed by
// one subtraction are exact. The prepared producer and retained transposed dots
// use this arithmetic, as do field additions in the limb paths. The separately
// retained scalar reference uses u128 remainder.
fn producer_reduce(x: u128) -> u32 {
    debug_assert!(x < (1_u128 << 70));
    let first = (x as u32 as u64) + 5 * ((x >> 32) as u64);
    let second = (first as u32 as u64) + 5 * (first >> 32);
    if second >= Q as u64 {
        (second - Q as u64) as u32
    } else {
        second as u32
    }
}
fn producer_mul(a: &[u32], b: &[u32], rows: usize, inner: usize, cols: usize) -> Vec<u32> {
    match transposed_mul_with_progress(a, b, rows, inner, cols, &mut no_cancellation) {
        Ok(product) => product,
        Err(impossible) => match impossible {},
    }
}
fn transposed_mul_with_progress<E>(
    a: &[u32],
    b: &[u32],
    rows: usize,
    inner: usize,
    cols: usize,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    transposed_mul_kernel_with_progress::<false, E>(a, b, rows, inner, cols, progress)
}

fn transposed_mul_kernel_with_progress<const LIMB: bool, E>(
    a: &[u32],
    b: &[u32],
    rows: usize,
    inner: usize,
    cols: usize,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    debug_assert!(inner <= N);
    let mut transposed = vec![0; b.len()];
    for k in 0..inner {
        for j in 0..cols {
            transposed[j * inner + k] = b[k * cols + j];
        }
    }
    multiply_transposed_right_with_progress::<LIMB, E>(a, &transposed, rows, inner, cols, progress)
}

// Receives a transpose owned by this same arithmetic call. Keeping it across
// transcript/product stages avoids another full B' transpose; every dot product
// and every original MatrixRow callback is still performed.
fn multiply_transposed_right_with_progress<const LIMB: bool, E>(
    a: &[u32],
    transposed: &[u32],
    rows: usize,
    inner: usize,
    cols: usize,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    debug_assert!(inner <= N);
    let mut out = vec![0; rows * cols];
    for i in 0..rows {
        progress(VerificationProgress::MatrixRow { row: i })?;
        for j in 0..cols {
            out[i * cols + j] = if LIMB {
                maintenance_limb::dot_bounded(
                    &a[i * inner..(i + 1) * inner],
                    &transposed[j * inner..(j + 1) * inner],
                    0,
                )
            } else {
                let mut sum = 0_u128;
                for k in 0..inner {
                    sum += u128::from(a[i * inner + k]) * u128::from(transposed[j * inner + k]);
                }
                producer_reduce(sum)
            };
        }
    }
    Ok(out)
}

// The owned B' buffer is square. Transposing each off-diagonal pair once
// preserves its allocation and all field values; callers need only this
// representation after preparation. No input, proof or arithmetic fact is shared.
fn transpose_square_in_place(matrix: &mut [u32]) {
    debug_assert_eq!(matrix.len(), CELLS);
    for row in 0..N {
        for column in row + 1..N {
            matrix.swap(row * N + column, column * N + row);
        }
    }
}

// Exact full replay. Transposition and batched hashing change neither transcript
// order nor the original noise/row/tile observation sequence. Nothing is trusted
// from the producer, a prior task, the claimed product or an earlier callback.
fn evaluate_transposed_with_progress<const LIMB_TRANSCRIPT: bool, E>(
    challenge: Hash,
    a: &[u32],
    b: &[u32],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<OptimizedTranscriptEvaluation, VerificationError<E>> {
    evaluate_transcript_kernel_with_progress::<LIMB_TRANSCRIPT, false, false, E>(
        challenge, a, b, progress,
    )
}

fn evaluate_transcript_kernel_with_progress<
    const LIMB_TRANSCRIPT: bool,
    const COLUMN_LIMB: bool,
    const FULL_LIMB: bool,
    E,
>(
    challenge: Hash,
    a: &[u32],
    b: &[u32],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<OptimizedTranscriptEvaluation, VerificationError<E>> {
    #[cfg(test)]
    ARITHMETIC_TRANSCRIPT_REPLAYS.with(|count| count.set(count.get() + 1));
    validate(a)?;
    validate(b)?;
    let el = expand_with_progress(challenge, 0, N * R, progress)?;
    let er = expand_with_progress(challenge, 1, R * N, progress)?;
    let fl = expand_with_progress(challenge, 2, N * R, progress)?;
    let fr = expand_with_progress(challenge, 3, R * N, progress)?;
    let e = transposed_mul_kernel_with_progress::<FULL_LIMB, E>(&el, &er, N, R, N, progress)
        .map_err(VerificationError::Cancelled)?;
    let f = transposed_mul_kernel_with_progress::<FULL_LIMB, E>(&fl, &fr, N, R, N, progress)
        .map_err(VerificationError::Cancelled)?;
    let mut ap = e;
    for (value, original) in ap.iter_mut().zip(a) {
        *value = producer_reduce(u128::from(*original) + u128::from(*value));
    }
    let mut bp = f;
    for (value, original) in bp.iter_mut().zip(b) {
        *value = producer_reduce(u128::from(*original) + u128::from(*value));
    }
    // The column kernel keeps the original contiguous B' rows. The other
    // kernels need only its transpose, so move the same owned allocation
    // after an exact in-place permutation. There are no callbacks in this
    // preparation interval; the original callback sequence remains unchanged.
    let mut bt = Vec::new();
    if !COLUMN_LIMB {
        transpose_square_in_place(&mut bp);
        bt = std::mem::take(&mut bp);
    }
    let mut cp = vec![0u32; CELLS];
    let mut transcript = Sha256::new();
    transcript.update(b"TRNM-PON-TRACE1\0");
    transcript.update(challenge);
    for bi in 0..N / R {
        for bj in 0..N / R {
            let mut cells = [0u32; R * R];
            let mut bytes = [0u8; R * R * 4];
            for bk in 0..N / R {
                progress(VerificationProgress::TranscriptTile {
                    row: bi,
                    column: bj,
                    inner: bk,
                })
                .map_err(VerificationError::Cancelled)?;
                for i in 0..R {
                    if COLUMN_LIMB {
                        let left = (bi * R + i) * N + bk * R;
                        let right = bk * R * N + bj * R;
                        let row = column_limb_row(
                            &ap[left..left + R],
                            &bp[right..right + (R - 1) * N + R],
                            &cells[i * R..(i + 1) * R],
                        );
                        cells[i * R..(i + 1) * R].copy_from_slice(&row);
                        for (j, value) in row.iter().enumerate() {
                            let pos = i * R + j;
                            bytes[pos * 4..pos * 4 + 4].copy_from_slice(&value.to_le_bytes());
                        }
                        continue;
                    }
                    for j in 0..R {
                        let pos = i * R + j;
                        cells[pos] = if LIMB_TRANSCRIPT {
                            let left = (bi * R + i) * N + bk * R;
                            let right = (bj * R + j) * N + bk * R;
                            maintenance_limb::dot8(
                                &ap[left..left + R],
                                &bt[right..right + R],
                                cells[pos],
                            )
                        } else {
                            let mut sum = u128::from(cells[pos]);
                            for k in bk * R..(bk + 1) * R {
                                sum += u128::from(ap[(bi * R + i) * N + k])
                                    * u128::from(bt[(bj * R + j) * N + k]);
                            }
                            producer_reduce(sum)
                        };
                        bytes[pos * 4..pos * 4 + 4].copy_from_slice(&cells[pos].to_le_bytes());
                    }
                }
                transcript.update(bytes);
            }
            for i in 0..R {
                cp[(bi * R + i) * N + bj * R..(bi * R + i) * N + (bj + 1) * R]
                    .copy_from_slice(&cells[i * R..(i + 1) * R]);
            }
        }
    }
    let trace = transcript.finalize().into();
    #[cfg(test)]
    ARITHMETIC_TRANSCRIPT_COMPLETIONS.with(|count| count.set(count.get() + 1));
    let right = if COLUMN_LIMB {
        ReplayedRightOperand::RowMajor(bp)
    } else {
        // Retain only the already computed transpose for the later ER * B'.
        // This is per-call arithmetic material, never reused across requests.
        drop(bp);
        ReplayedRightOperand::Transposed(bt)
    };
    Ok(OptimizedTranscriptEvaluation {
        cp,
        el,
        er,
        fl,
        fr,
        right,
        trace,
    })
}

// Eight independent columns keep the right-hand row contiguous. LLVM may
// vectorize these portable integer operations; no SIMD capability is required.
// For each column, p=lo+2^32*hi and 2^32=5 (mod q). Including prior,
// low<9*2^32, high<8*2^32, sum=low+5*high<49*2^32. Its fold is
// <2^32+240<2q, so one subtraction is exact. No u64 sum can overflow.
#[inline]
fn column_limb_row(left: &[u32], right: &[u32], prior: &[u32]) -> [u32; R] {
    debug_assert_eq!(left.len(), R);
    debug_assert_eq!(right.len(), (R - 1) * N + R);
    debug_assert_eq!(prior.len(), R);
    let mut low = [0u64; R];
    let mut high = [0u64; R];
    for j in 0..R {
        low[j] = u64::from(prior[j]);
    }
    for k in 0..R {
        let row = &right[k * N..k * N + R];
        let value = u64::from(left[k]);
        for j in 0..R {
            let product = value * u64::from(row[j]);
            low[j] += u64::from(product as u32);
            high[j] += product >> 32;
        }
    }
    std::array::from_fn(|j| {
        let sum = low[j] + 5 * high[j];
        let folded = u64::from(sum as u32) + 5 * (sum >> 32);
        if folded >= Q as u64 {
            (folded - Q as u64) as u32
        } else {
            folded as u32
        }
    })
}

fn finish_transposed_with_progress<E>(
    a: &[u32],
    evaluated: OptimizedTranscriptEvaluation,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    finish_transposed_kernel_with_progress::<false, E>(a, evaluated, progress)
}

// Both product corrections have shape (N x R) * (R x N). Subtract each
// complete dot product directly into this call's owned result, avoiding a
// second full-size output matrix. Every original MatrixRow callback still
// precedes that row's arithmetic. On cancellation the caller discards this
// operation-local result; partial updates are never published as a fact.
fn subtract_transposed_correction_with_progress<const LIMB: bool, E>(
    left: &[u32],
    right: &[u32],
    product: &mut [u32],
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<(), E> {
    debug_assert_eq!(left.len(), N * R);
    debug_assert_eq!(right.len(), R * N);
    debug_assert_eq!(product.len(), CELLS);
    let mut transposed = vec![0; right.len()];
    for k in 0..R {
        for j in 0..N {
            transposed[j * R + k] = right[k * N + j];
        }
    }
    for (i, row) in product.chunks_exact_mut(N).enumerate() {
        progress(VerificationProgress::MatrixRow { row: i })?;
        let a = &left[i * R..(i + 1) * R];
        for (j, value) in row.iter_mut().enumerate() {
            let b = &transposed[j * R..(j + 1) * R];
            let correction = if LIMB {
                maintenance_limb::dot_bounded(a, b, 0)
            } else {
                let mut sum = 0_u128;
                for k in 0..R {
                    sum += u128::from(a[k]) * u128::from(b[k]);
                }
                producer_reduce(sum)
            };
            // Canonical operands make this nonnegative and below 2Q. Two
            // successive subtractions equal the original (C' - C1 - C2) mod Q.
            let corrected = u64::from(*value) + Q as u64 - u64::from(correction);
            *value = if corrected >= Q as u64 {
                (corrected - Q as u64) as u32
            } else {
                corrected as u32
            };
        }
    }
    Ok(())
}

fn finish_transposed_kernel_with_progress<const LIMB: bool, E>(
    a: &[u32],
    evaluated: OptimizedTranscriptEvaluation,
    progress: &mut impl FnMut(VerificationProgress) -> Result<(), E>,
) -> Result<Vec<u32>, E> {
    progress(VerificationProgress::BeforeProduct)?;
    #[cfg(test)]
    PRODUCT_RECONSTRUCTIONS.with(|count| count.set(count.get() + 1));
    let mut product = evaluated.cp;
    let left = transposed_mul_kernel_with_progress::<LIMB, E>(a, &evaluated.fl, N, N, R, progress)?;
    subtract_transposed_correction_with_progress::<LIMB, E>(
        &left,
        &evaluated.fr,
        &mut product,
        progress,
    )?;
    let right = match &evaluated.right {
        ReplayedRightOperand::RowMajor(bp) => {
            transposed_mul_kernel_with_progress::<LIMB, E>(&evaluated.er, bp, R, N, N, progress)
        }
        ReplayedRightOperand::Transposed(bt) => {
            multiply_transposed_right_with_progress::<LIMB, E>(&evaluated.er, bt, R, N, N, progress)
        }
    }?;
    subtract_transposed_correction_with_progress::<LIMB, E>(
        &evaluated.el,
        &right,
        &mut product,
        progress,
    )?;
    Ok(product)
}

/// Bounded producer cache for one exact task. It carries no verification authority.
/// The useful product is fixed across challenges; every challenge still hashes every tile.
pub struct PreparedTask {
    a: Vec<u32>,
    b: Vec<u32>,
    prefix: Vec<u8>,
}

/// Local generation checkpoints, with no proof field or verification capability.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PreparedGenerationProgress {
    BeforeReplay,
    Noise {
        label: u8,
        counter: u32,
    },
    NoiseRow {
        operand: u8,
        row: usize,
    },
    TranscriptTile {
        row: usize,
        column: usize,
        inner: usize,
    },
    BeforeProof,
}

#[derive(Debug, PartialEq, Eq)]
pub enum PreparedGenerationError<E> {
    Relation(WorkError),
    Cancelled(E),
}

impl PreparedTask {
    /// Cached mathematical result bytes for producer root planning. This is not
    /// a verified-work capability; admission still replays the original relation.
    pub fn product_bytes(&self) -> &[u8] {
        &self.prefix[4 + 2 * CELLS * 4..4 + 3 * CELLS * 4]
    }
    pub fn new(a: &[u32], b: &[u32]) -> Result<Self, WorkError> {
        validate(a)?;
        validate(b)?;
        let product = producer_mul(a, b, N, N, N);
        let mut prefix = Vec::with_capacity(PROOF_BYTES);
        prefix.extend_from_slice(b"PNW1");
        for matrix in [a, b, product.as_slice()] {
            prefix.extend_from_slice(&field_bytes(matrix));
        }
        Ok(Self {
            a: a.to_vec(),
            b: b.to_vec(),
            prefix,
        })
    }
    pub fn prove(&self, challenge: Hash) -> Result<Vec<u8>, WorkError> {
        match self.prove_with_progress(challenge, |_| Ok::<_, std::convert::Infallible>(())) {
            Ok(proof) => Ok(proof),
            Err(PreparedGenerationError::Relation(error)) => Err(error),
            Err(PreparedGenerationError::Cancelled(impossible)) => match impossible {},
        }
    }

    /// Same complete arithmetic and byte order as ordinary production. Each
    /// observation precedes its bounded work; cancellation returns no proof and
    /// leaves this exact mathematical cache available for a later fresh call.
    pub fn prove_with_progress<E>(
        &self,
        challenge: Hash,
        mut progress: impl FnMut(PreparedGenerationProgress) -> Result<(), E>,
    ) -> Result<Vec<u8>, PreparedGenerationError<E>> {
        progress(PreparedGenerationProgress::BeforeReplay)
            .map_err(PreparedGenerationError::Cancelled)?;
        let mut noise = |label| {
            expand_with_progress(challenge, label, N * R, &mut |point| {
                let VerificationProgress::Noise { label, counter } = point else {
                    unreachable!("noise expansion emits only noise observations")
                };
                progress(PreparedGenerationProgress::Noise { label, counter })
            })
            .map_err(|error| match error {
                VerificationError::Relation(error) => PreparedGenerationError::Relation(error),
                VerificationError::Cancelled(error) => PreparedGenerationError::Cancelled(error),
            })
        };
        let el = noise(0)?;
        let er = noise(1)?;
        let fl = noise(2)?;
        let fr = noise(3)?;
        let e = transposed_mul_with_progress(&el, &er, N, R, N, &mut |point| {
            let VerificationProgress::MatrixRow { row } = point else {
                unreachable!("matrix multiplication emits only row observations")
            };
            progress(PreparedGenerationProgress::NoiseRow { operand: 0, row })
        })
        .map_err(PreparedGenerationError::Cancelled)?;
        let ap: Vec<u32> = self
            .a
            .iter()
            .zip(e)
            .map(|(x, y)| ((u128::from(*x) + u128::from(y)) % Q) as u32)
            .collect();
        let f = transposed_mul_with_progress(&fl, &fr, N, R, N, &mut |point| {
            let VerificationProgress::MatrixRow { row } = point else {
                unreachable!("matrix multiplication emits only row observations")
            };
            progress(PreparedGenerationProgress::NoiseRow { operand: 1, row })
        })
        .map_err(PreparedGenerationError::Cancelled)?;
        let bp: Vec<u32> = self
            .b
            .iter()
            .zip(f)
            .map(|(x, y)| ((u128::from(*x) + u128::from(y)) % Q) as u32)
            .collect();
        let mut bt = vec![0u32; CELLS];
        for k in 0..N {
            for j in 0..N {
                bt[j * N + k] = bp[k * N + j];
            }
        }
        let mut transcript = Sha256::new();
        transcript.update(b"TRNM-PON-TRACE1\0");
        transcript.update(challenge);
        for bi in 0..N / R {
            for bj in 0..N / R {
                let mut cells = [0u32; R * R];
                let mut bytes = [0u8; R * R * 4];
                for bk in 0..N / R {
                    progress(PreparedGenerationProgress::TranscriptTile {
                        row: bi,
                        column: bj,
                        inner: bk,
                    })
                    .map_err(PreparedGenerationError::Cancelled)?;
                    for i in 0..R {
                        for j in 0..R {
                            let pos = i * R + j;
                            let mut sum = u128::from(cells[pos]);
                            for k in bk * R..(bk + 1) * R {
                                sum += u128::from(ap[(bi * R + i) * N + k])
                                    * u128::from(bt[(bj * R + j) * N + k]);
                            }
                            cells[pos] = producer_reduce(sum);
                            bytes[pos * 4..pos * 4 + 4].copy_from_slice(&cells[pos].to_le_bytes());
                        }
                    }
                    transcript.update(bytes);
                }
            }
        }
        progress(PreparedGenerationProgress::BeforeProof)
            .map_err(PreparedGenerationError::Cancelled)?;
        let mut out = self.prefix.clone();
        out.extend_from_slice(&transcript.finalize());
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn proof_statement_precheck_rejects_task_and_ticket_without_replay() {
        let (a, b) = matrices();
        let challenge = [71; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        assert_eq!(
            precheck_proof_statement(challenge, task, [255; 32], &proof),
            Ok(())
        );
        let mut wrong_task = task;
        wrong_task[0] ^= 1;
        let mut tiny_target = [0; 32];
        tiny_target[31] = 1;
        for (expected_task, target, expected) in [
            (wrong_task, [255; 32], WorkError::Task),
            (task, tiny_target, WorkError::Target),
        ] {
            assert_eq!(
                precheck_proof_statement(challenge, expected_task, target, &proof),
                Err(expected),
            );
            let mut replay_started = false;
            let result =
                verify_with_progress(challenge, expected_task, target, &proof, &mut |_| {
                    replay_started = true;
                    Ok::<(), ()>(())
                });
            assert_eq!(result.unwrap_err(), VerificationError::Relation(expected));
            assert!(!replay_started);
        }
    }

    #[test]
    fn proof_statement_precheck_never_promotes_a_passing_forgery() {
        let (a, b) = matrices();
        let challenge = [72; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut false_trace = proof.clone();
        false_trace[PROOF_BYTES - 1] ^= 1;
        let mut false_product = proof;
        let at = 4 + 2 * CELLS * 4;
        let old = u32::from_le_bytes(false_product[at..at + 4].try_into().unwrap());
        false_product[at..at + 4].copy_from_slice(&(((old as u128 + 1) % Q) as u32).to_le_bytes());
        for (bytes, expected) in [
            (false_trace, WorkError::Transcript),
            (false_product, WorkError::Product),
        ] {
            assert_eq!(
                precheck_proof_statement(challenge, task, [255; 32], &bytes),
                Ok(())
            );
            let mut replay_started = false;
            let result = verify_with_progress(challenge, task, [255; 32], &bytes, &mut |_| {
                replay_started = true;
                Ok::<(), ()>(())
            });
            assert!(replay_started);
            assert_eq!(result.unwrap_err(), VerificationError::Relation(expected));
        }
    }

    fn checked_value(
        result: Result<VerifiedWork, WorkError>,
    ) -> Result<(Hash, Hash, Hash, Vec<u32>), WorkError> {
        result.map(|work| (work.challenge(), work.task(), work.ticket(), work.product))
    }

    #[test]
    fn borrowed_product_bytes_reject_first_middle_last_and_noncanonical_cells() {
        let (a, b) = matrices();
        let challenge = [61; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let kernels = [
            VerificationKernel::ScalarReference,
            VerificationKernel::Transposed,
            VerificationKernel::LimbTranscript,
            VerificationKernel::ColumnLimbTranscript,
            VerificationKernel::FullLimb,
        ];
        for cell in [0, CELLS / 2, CELLS - 1] {
            let offset = 4 + 2 * CELLS * 4 + cell * 4;
            let old = u32::from_le_bytes(proof[offset..offset + 4].try_into().unwrap());
            for (value, expected) in [
                (((u128::from(old) + 1) % Q) as u32, WorkError::Product),
                (Q as u32, WorkError::Field),
                (u32::MAX, WorkError::Field),
            ] {
                let mut changed = proof.clone();
                changed[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
                let mut reference_points = None;
                for kernel in kernels {
                    let mut points = Vec::new();
                    PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
                    let result = verify_with_kernel(
                        challenge,
                        task,
                        [255; 32],
                        &changed,
                        &mut |point| {
                            points.push(point);
                            Ok::<(), &str>(())
                        },
                        kernel,
                    );
                    assert_eq!(result.unwrap_err(), VerificationError::Relation(expected));
                    PRODUCT_RECONSTRUCTIONS.with(|count| {
                        assert_eq!(count.get(), usize::from(expected == WorkError::Product));
                    });
                    if let Some(reference) = &reference_points {
                        assert_eq!(&points, reference);
                    } else {
                        reference_points = Some(points);
                    }
                }
            }
        }
        let expected = checked_value(verify_reference(challenge, task, [255; 32], &proof));
        assert_eq!(
            checked_value(verify(challenge, task, [255; 32], &proof)),
            expected
        );
        assert_eq!(
            checked_value(verify_limb(challenge, task, [255; 32], &proof)),
            expected
        );
    }

    #[test]
    fn borrowed_product_bytes_keep_rejection_before_cancellation_and_retry() {
        let (a, b) = matrices();
        let challenge = [62; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut invalid = proof.clone();
        invalid[4 + 3 * CELLS * 4 - 4..4 + 3 * CELLS * 4]
            .copy_from_slice(&(Q as u32).to_le_bytes());
        for kernel in [
            VerificationKernel::ScalarReference,
            VerificationKernel::Transposed,
            VerificationKernel::LimbTranscript,
            VerificationKernel::ColumnLimbTranscript,
            VerificationKernel::FullLimb,
        ] {
            let mut calls = 0;
            let result = verify_with_kernel(
                challenge,
                [0; 32],
                [255; 32],
                &invalid,
                &mut |_| {
                    calls += 1;
                    Err("cancel")
                },
                kernel,
            );
            assert_eq!(
                result.unwrap_err(),
                VerificationError::Relation(WorkError::Field)
            );
            assert_eq!(calls, 0);
            let result = verify_with_kernel(
                challenge,
                task,
                [255; 32],
                &proof,
                &mut |point| {
                    if point == VerificationProgress::BeforeVerifiedWork {
                        Err("final cancellation")
                    } else {
                        Ok(())
                    }
                },
                kernel,
            );
            assert_eq!(
                result.unwrap_err(),
                VerificationError::Cancelled("final cancellation")
            );
            let retried = verify_with_kernel(
                challenge,
                task,
                [255; 32],
                &proof,
                &mut no_cancellation,
                kernel,
            )
            .unwrap();
            assert_eq!(retried.product(), mul(&a, &b, N, N, N));
        }
    }

    #[test]
    fn untrusted_trace_ticket_search_needs_no_producer_and_never_gains_verified_work() {
        // This is a relation/admission control, not a timing or network-load
        // measurement. Neither a prepared producer nor a valid proof is used.
        let (a, b) = matrices();
        let task = task_id(&a, &b).unwrap();
        let challenge = [63; 32];
        let mut target = [255; 32];
        target[0] = 7;
        let mut proof = b"PNW1".to_vec();
        proof.extend(field_bytes(&a));
        proof.extend(field_bytes(&b));
        proof.resize(PROOF_BYTES, 0); // arbitrary canonical C, then a claimed trace
        let mut selected = None;
        for trace_nonce in 0u64..4096 {
            let trace = hash(b"untrusted-trace-control-v1", &[&trace_nonce.to_le_bytes()]);
            let ticket = hash(b"ticket", &[&challenge, &trace]);
            if ticket <= target {
                selected = Some((trace_nonce, trace, ticket));
                break;
            }
        }
        let (trace_nonce, trace, ticket) = selected.expect("deterministic bounded control");
        // Recheck every target miss instead of concealing the search prefix.
        for nonce in 0..trace_nonce {
            let missed = hash(b"untrusted-trace-control-v1", &[&nonce.to_le_bytes()]);
            assert!(hash(b"ticket", &[&challenge, &missed]) > target);
        }
        assert!(ticket <= target);
        proof[PROOF_BYTES - 32..].copy_from_slice(&trace);
        for kernel in [
            VerificationKernel::ScalarReference,
            VerificationKernel::Transposed,
            VerificationKernel::LimbTranscript,
            VerificationKernel::ColumnLimbTranscript,
            VerificationKernel::FullLimb,
        ] {
            PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
            let mut tiles = 0;
            let result = verify_with_kernel(
                challenge,
                task,
                target,
                &proof,
                &mut |point| {
                    if matches!(point, VerificationProgress::TranscriptTile { .. }) {
                        tiles += 1;
                    }
                    assert_ne!(point, VerificationProgress::BeforeVerifiedWork);
                    Ok::<(), &str>(())
                },
                kernel,
            );
            assert_eq!(
                result.unwrap_err(),
                VerificationError::Relation(WorkError::Transcript)
            );
            assert_eq!(tiles, (N / R).pow(3));
            PRODUCT_RECONSTRUCTIONS.with(|count| assert_eq!(count.get(), 0));
        }
    }

    #[test]
    fn canonical_task_byte_reuse_preserves_asymmetric_inputs_and_field_precedence() {
        let a: Vec<_> = (0..CELLS)
            .map(|i| ((i * 65_537 + 258) as u128 % Q) as u32)
            .collect();
        let b: Vec<_> = (0..CELLS)
            .map(|i| (Q - 1 - (i % 257) as u128) as u32)
            .collect();
        let task = task_id(&a, &b).unwrap();
        let challenge = [42; 32];
        let proof = prove(challenge, &a, &b).unwrap();
        assert_eq!(
            hash(
                b"task",
                &[
                    &proof[4..4 + CELLS * 4],
                    &proof[4 + CELLS * 4..4 + CELLS * 8]
                ]
            ),
            task
        );
        for start in [4, 4 + CELLS * 4, 4 + CELLS * 8] {
            for index in [0, CELLS / 2, CELLS - 1] {
                let mut invalid = proof.clone();
                let offset = start + 4 * index;
                invalid[offset..offset + 4].copy_from_slice(&(Q as u32).to_le_bytes());
                for kernel in [
                    VerificationKernel::ScalarReference,
                    VerificationKernel::Transposed,
                    VerificationKernel::LimbTranscript,
                    VerificationKernel::ColumnLimbTranscript,
                    VerificationKernel::FullLimb,
                ] {
                    let mut calls = 0;
                    let result = verify_with_kernel(
                        challenge,
                        [0; 32],
                        [255; 32],
                        &invalid,
                        &mut |_| {
                            calls += 1;
                            Ok::<(), usize>(())
                        },
                        kernel,
                    );
                    assert_eq!(
                        result.unwrap_err(),
                        VerificationError::Relation(WorkError::Field)
                    );
                    assert_eq!(calls, 0);
                }
            }
        }
        let mut reordered = proof.clone();
        reordered[4..4 + CELLS * 4].copy_from_slice(&proof[4 + CELLS * 4..4 + CELLS * 8]);
        reordered[4 + CELLS * 4..4 + CELLS * 8].copy_from_slice(&proof[4..4 + CELLS * 4]);
        assert_eq!(
            verify(challenge, task, [255; 32], &reordered).unwrap_err(),
            WorkError::Task
        );
        let reference = checked_value(verify_reference(challenge, task, [255; 32], &proof));
        assert_eq!(
            checked_value(verify(challenge, task, [255; 32], &proof)),
            reference
        );
        assert_eq!(
            checked_value(verify_limb(challenge, task, [255; 32], &proof)),
            reference
        );
    }

    #[test]
    fn fast_and_scalar_verifiers_match_extreme_products_and_error_precedence() {
        let a: Vec<_> = (0..CELLS)
            .map(|i| if i % 2 == 0 { (Q - 1) as u32 } else { 0 })
            .collect();
        let b: Vec<_> = (0..CELLS)
            .map(|i| (Q - 1 - (i % 19) as u128) as u32)
            .collect();
        let challenge = [255; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut cases = vec![(challenge, task, [255; 32], proof.clone())];
        cases.push(([7; 32], task, [255; 32], proof.clone()));
        cases.push((challenge, [0; 32], [255; 32], proof.clone()));
        cases.push((challenge, task, [0; 32], proof.clone()));
        for length in [0, 4, PROOF_BYTES - 1] {
            cases.push((challenge, task, [255; 32], proof[..length].to_vec()));
        }
        let mut extra = proof.clone();
        extra.push(0);
        cases.push((challenge, task, [255; 32], extra));
        for pos in [4, 4 + CELLS * 4, 4 + CELLS * 8] {
            let mut bad = proof.clone();
            bad[pos..pos + 4].copy_from_slice(&u32::MAX.to_le_bytes());
            cases.push((challenge, [0; 32], [255; 32], bad));
        }
        let mut wrong_product = proof.clone();
        wrong_product[4 + CELLS * 8..4 + CELLS * 8 + 4].copy_from_slice(&0u32.to_le_bytes());
        // Use a guaranteed different canonical value even if the true cell is zero.
        if wrong_product == proof {
            wrong_product[4 + CELLS * 8] = 1;
        }
        cases.push((challenge, task, [255; 32], wrong_product.clone()));
        wrong_product[PROOF_BYTES - 1] ^= 1;
        cases.push((challenge, task, [255; 32], wrong_product));
        let mut wrong_magic = proof.clone();
        wrong_magic[0] ^= 1;
        cases.push((challenge, [0; 32], [0; 32], wrong_magic));
        for (c, t, target, bytes) in cases {
            assert_eq!(
                checked_value(verify_transposed(c, t, target, &bytes)),
                checked_value(verify_reference(c, t, target, &bytes))
            );
            assert_eq!(
                checked_value(verify_column_limb(c, t, target, &bytes)),
                checked_value(verify_reference(c, t, target, &bytes))
            );
            assert_eq!(
                checked_value(verify_full_limb(c, t, target, &bytes)),
                checked_value(verify_reference(c, t, target, &bytes))
            );
            assert_eq!(
                checked_value(verify_limb(c, t, target, &bytes)),
                checked_value(verify_reference(c, t, target, &bytes))
            );
            assert_eq!(
                checked_value(verify(c, t, target, &bytes)),
                checked_value(verify_reference(c, t, target, &bytes))
            );
        }
    }

    #[test]
    fn fast_and_scalar_verifiers_preserve_observation_order_and_cancelled_results() {
        let (a, b) = matrices();
        let challenge = [23; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut fast_points = Vec::new();
        let fast = verify_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
            fast_points.push(point);
            Ok::<(), usize>(())
        })
        .unwrap();
        let mut scalar_points = Vec::new();
        let scalar =
            verify_reference_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                scalar_points.push(point);
                Ok::<(), usize>(())
            })
            .unwrap();
        assert_eq!(fast_points, scalar_points);
        assert_eq!(fast.product(), scalar.product());
        let mut transposed_points = Vec::new();
        let transposed =
            verify_transposed_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                transposed_points.push(point);
                Ok::<(), usize>(())
            })
            .unwrap();
        assert_eq!(transposed_points, scalar_points);
        assert_eq!(transposed.product(), scalar.product());
        let mut limb_points = Vec::new();
        let limb = verify_limb_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
            limb_points.push(point);
            Ok::<(), usize>(())
        })
        .unwrap();
        assert_eq!(limb_points, scalar_points);
        assert_eq!(limb.product(), scalar.product());
        let mut column_points = Vec::new();
        let column =
            verify_column_limb_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                column_points.push(point);
                Ok::<(), usize>(())
            })
            .unwrap();
        assert_eq!(column_points, scalar_points);
        assert_eq!(column.product(), scalar.product());
        let cuts: Vec<_> = scalar_points
            .iter()
            .enumerate()
            .filter_map(|(index, point)| {
                let selected = match point {
                    VerificationProgress::BeforeReplay
                    | VerificationProgress::BeforeProduct
                    | VerificationProgress::BeforeVerifiedWork => true,
                    VerificationProgress::Noise { counter, .. } => *counter == 0 || *counter == 63,
                    VerificationProgress::MatrixRow { row } => [0, 7, 63].contains(row),
                    VerificationProgress::TranscriptTile { row, column, inner } => {
                        (*row, *column, *inner) == (0, 0, 0)
                            || (*row, *column, *inner) == (4, 4, 4)
                            || (*row, *column, *inner) == (7, 7, 7)
                    }
                };
                selected.then_some(index)
            })
            .collect();
        for cut in cuts {
            let mut observed = 0;
            let mut stop = |_| {
                let current = observed;
                observed += 1;
                if current == cut {
                    Err(cut)
                } else {
                    Ok(())
                }
            };
            let fast_error =
                verify_with_progress(challenge, task, [255; 32], &proof, &mut stop).unwrap_err();
            assert_eq!(observed, cut + 1);
            observed = 0;
            let scalar_error =
                verify_reference_with_progress(challenge, task, [255; 32], &proof, &mut |_| {
                    let current = observed;
                    observed += 1;
                    if current == cut {
                        Err(cut)
                    } else {
                        Ok(())
                    }
                })
                .unwrap_err();
            assert_eq!(observed, cut + 1);
            assert_eq!(fast_error, VerificationError::Cancelled(cut));
            assert_eq!(fast_error, scalar_error);
            observed = 0;
            let transposed_error =
                verify_transposed_with_progress(challenge, task, [255; 32], &proof, &mut |_| {
                    let current = observed;
                    observed += 1;
                    if current == cut {
                        Err(cut)
                    } else {
                        Ok(())
                    }
                })
                .unwrap_err();
            assert_eq!(observed, cut + 1);
            assert_eq!(transposed_error, scalar_error);
            observed = 0;
            let limb_error =
                verify_limb_with_progress(challenge, task, [255; 32], &proof, &mut |_| {
                    let current = observed;
                    observed += 1;
                    if current == cut {
                        Err(cut)
                    } else {
                        Ok(())
                    }
                })
                .unwrap_err();
            assert_eq!(observed, cut + 1);
            assert_eq!(limb_error, scalar_error);
            observed = 0;
            let column_error =
                verify_column_limb_with_progress(challenge, task, [255; 32], &proof, &mut |_| {
                    let current = observed;
                    observed += 1;
                    if current == cut {
                        Err(cut)
                    } else {
                        Ok(())
                    }
                })
                .unwrap_err();
            assert_eq!(observed, cut + 1);
            assert_eq!(column_error, scalar_error);
        }
    }

    #[test]
    fn full_limb_matrix_products_match_reference_for_all_w1_shapes() {
        for (rows, inner, cols) in [(N, R, N), (N, N, R), (R, N, N)] {
            for maximum in [false, true] {
                let a: Vec<_> = (0..rows * inner)
                    .map(|i| {
                        if maximum {
                            Q as u32 - 1
                        } else {
                            [0, 1, Q as u32 - 1, 1 << 31, 31][i % 5]
                        }
                    })
                    .collect();
                let b: Vec<_> = (0..inner * cols)
                    .map(|i| {
                        if maximum {
                            Q as u32 - 1
                        } else {
                            [Q as u32 - 2, 0, 17, 1 << 16][i % 4]
                        }
                    })
                    .collect();
                let mut expected_points = Vec::new();
                let expected = mul_with_progress(&a, &b, rows, inner, cols, &mut |point| {
                    expected_points.push(point);
                    Ok::<_, usize>(())
                })
                .unwrap();
                let mut actual_points = Vec::new();
                let actual = transposed_mul_kernel_with_progress::<true, usize>(
                    &a,
                    &b,
                    rows,
                    inner,
                    cols,
                    &mut |point| {
                        actual_points.push(point);
                        Ok(())
                    },
                )
                .unwrap();
                assert_eq!(actual, expected);
                assert_eq!(actual_points, expected_points);
                for cut in 0..rows {
                    let mut observed = Vec::new();
                    let result = transposed_mul_kernel_with_progress::<true, usize>(
                        &a,
                        &b,
                        rows,
                        inner,
                        cols,
                        &mut |point| {
                            observed.push(point);
                            if observed.len() - 1 == cut {
                                Err(cut)
                            } else {
                                Ok(())
                            }
                        },
                    );
                    assert_eq!(result, Err(cut));
                    assert_eq!(observed, expected_points[..=cut]);
                }
            }
        }
    }

    #[test]
    fn owned_square_transpose_preserves_allocation_and_exact_permutation() {
        let original: Vec<_> = (0..CELLS)
            .map(|i| Q as u32 - 1 - (i * 65_537) as u32)
            .collect();
        let mut actual = original.clone();
        let pointer = actual.as_ptr();
        let capacity = actual.capacity();
        transpose_square_in_place(&mut actual);
        assert_eq!(actual.as_ptr(), pointer);
        assert_eq!(actual.capacity(), capacity);
        for row in 0..N {
            for column in 0..N {
                assert_eq!(actual[row * N + column], original[column * N + row]);
            }
        }
        transpose_square_in_place(&mut actual);
        assert_eq!(actual, original);
        assert_eq!(actual.as_ptr(), pointer);
        assert_eq!(actual.capacity(), capacity);
    }

    #[test]
    fn in_place_corrections_match_independent_scalar_for_full_w1_shape() {
        fn exercise<const LIMB: bool>() {
            let values = [0, 1, 1 << 16, 1 << 31, Q as u32 - 2, Q as u32 - 1];
            for case in 0..8 {
                let word = |index: usize| match case {
                    0 => 0,
                    1 => Q as u32 - 1,
                    2 => values[index % values.len()],
                    3 => Q as u32 - 1 - (index % 257) as u32,
                    _ => ((index as u128 * 65_537 + case * 97) % Q) as u32,
                };
                let left: Vec<_> = (0..N * R).map(word).collect();
                let right: Vec<_> = (0..R * N).map(|i| word(i * 3 + 1)).collect();
                let next_left: Vec<_> = (0..N * R).map(|i| word(i * 5 + 2)).collect();
                let next_right: Vec<_> = (0..R * N).map(|i| word(i * 7 + 3)).collect();
                let first = mul(&left, &right, N, R, N);
                let second = mul(&next_left, &next_right, N, R, N);
                let original: Vec<_> = (0..CELLS)
                    .map(|i| match i % 4 {
                        0 => 0,
                        1 => Q as u32 - 1,
                        2 => first[i],
                        _ => word(i + 4),
                    })
                    .collect();
                let expected_first: Vec<_> = original
                    .iter()
                    .zip(&first)
                    .map(|(&p, &c)| ((u128::from(p) + Q - u128::from(c)) % Q) as u32)
                    .collect();
                let expected: Vec<_> = original
                    .iter()
                    .zip(&first)
                    .zip(&second)
                    .map(|((&p, &c1), &c2)| {
                        ((u128::from(p) + 2 * Q - u128::from(c1) - u128::from(c2)) % Q) as u32
                    })
                    .collect();
                let mut actual = original;
                let mut points = Vec::new();
                subtract_transposed_correction_with_progress::<LIMB, usize>(
                    &left,
                    &right,
                    &mut actual,
                    &mut |point| {
                        points.push(point);
                        Ok(())
                    },
                )
                .unwrap();
                assert_eq!(actual, expected_first, "first correction, case {case}");
                subtract_transposed_correction_with_progress::<LIMB, usize>(
                    &next_left,
                    &next_right,
                    &mut actual,
                    &mut |point| {
                        points.push(point);
                        Ok(())
                    },
                )
                .unwrap();
                assert_eq!(actual, expected, "two corrections, case {case}");
                let expected_points: Vec<_> = (0..2 * N)
                    .map(|i| VerificationProgress::MatrixRow { row: i % N })
                    .collect();
                assert_eq!(points, expected_points);
            }
        }
        exercise::<false>();
        exercise::<true>();
    }

    #[test]
    fn in_place_correction_cancellation_stops_before_each_row_and_retry_is_fresh() {
        fn exercise<const LIMB: bool>() {
            let left: Vec<_> = (0..N * R).map(|i| Q as u32 - 1 - i as u32).collect();
            let right: Vec<_> = (0..R * N)
                .map(|i| [0, 1, Q as u32 - 1, 1 << 31, 31][i % 5])
                .collect();
            let original: Vec<_> = (0..CELLS).map(|i| (i * 65_537 + 258) as u32).collect();
            let correction = mul(&left, &right, N, R, N);
            let expected: Vec<_> = original
                .iter()
                .zip(correction)
                .map(|(&p, c)| ((u128::from(p) + Q - u128::from(c)) % Q) as u32)
                .collect();
            for cut in 0..N {
                let mut local_product = original.clone();
                let mut points = Vec::new();
                let result = subtract_transposed_correction_with_progress::<LIMB, usize>(
                    &left,
                    &right,
                    &mut local_product,
                    &mut |point| {
                        points.push(point);
                        if point == (VerificationProgress::MatrixRow { row: cut }) {
                            Err(cut)
                        } else {
                            Ok(())
                        }
                    },
                );
                assert_eq!(result, Err(cut));
                let expected_points: Vec<_> = (0..=cut)
                    .map(|row| VerificationProgress::MatrixRow { row })
                    .collect();
                assert_eq!(points, expected_points);
                assert_eq!(local_product[..cut * N], expected[..cut * N]);
                assert_eq!(local_product[cut * N..], original[cut * N..]);
                // The verifier discards the operation-local partial result on
                // cancellation. A later invocation starts with its own C'.
                drop(local_product);
                let mut retry = original.clone();
                subtract_transposed_correction_with_progress::<LIMB, usize>(
                    &left,
                    &right,
                    &mut retry,
                    &mut |_| Ok(()),
                )
                .unwrap();
                assert_eq!(retry, expected);
            }
        }
        exercise::<false>();
        exercise::<true>();
    }

    #[test]
    fn full_limb_preserves_every_cancellation_boundary_and_retry_isolation() {
        let (a, b) = matrices();
        let challenge = [41; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut expected_points = Vec::new();
        let expected =
            verify_reference_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                expected_points.push(point);
                Ok::<_, usize>(())
            })
            .unwrap();
        let mut actual_points = Vec::new();
        let actual =
            verify_full_limb_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                actual_points.push(point);
                Ok::<_, usize>(())
            })
            .unwrap();
        assert_eq!(checked_value(Ok(actual)), checked_value(Ok(expected)));
        assert_eq!(actual_points, expected_points);
        for cut in 0..expected_points.len() {
            let mut observed = Vec::new();
            let result =
                verify_full_limb_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                    observed.push(point);
                    if observed.len() - 1 == cut {
                        Err(cut)
                    } else {
                        Ok(())
                    }
                });
            assert!(matches!(result, Err(VerificationError::Cancelled(value)) if value == cut));
            assert_eq!(observed, expected_points[..=cut]);
        }
        let other_challenge = [42; 32];
        let other = prove(other_challenge, &a, &b).unwrap();
        for (selected, bytes) in [(other_challenge, &other), (challenge, &proof)] {
            assert_eq!(
                checked_value(verify_full_limb(selected, task, [255; 32], bytes)),
                checked_value(verify_reference(selected, task, [255; 32], bytes))
            );
        }
    }

    #[test]
    fn column_limb_each_prefix_matches_independent_scalar_with_strided_extremes() {
        // Exercise all carries and asymmetric row/column indexing. These are
        // raw arithmetic controls, not alternate externally supplied noise.
        let values = [0, 1, 2, 1 << 16, 1 << 31, Q as u32 - 2, Q as u32 - 1];
        for case in 0..values.len() + 2 {
            let a: Vec<u32> = (0..CELLS)
                .map(|index| {
                    if case < values.len() {
                        values[case]
                    } else if case == values.len() {
                        values[(index * 13 + index / N) % values.len()]
                    } else {
                        ((index as u128 * 2_654_435_761 + 17) % Q) as u32
                    }
                })
                .collect();
            let b: Vec<u32> = (0..CELLS)
                .map(|index| {
                    if case < values.len() {
                        values[case]
                    } else if case == values.len() {
                        values[(index * 17 + index / N + 1) % values.len()]
                    } else {
                        ((index as u128 * 4_294_967_279 + 65_537) % Q) as u32
                    }
                })
                .collect();
            for row in 0..N {
                for bj in 0..N / R {
                    let prior = values[(row + bj) % values.len()];
                    let mut actual = [prior; R];
                    for bk in 0..N / R {
                        let left = row * N + bk * R;
                        let right = bk * R * N + bj * R;
                        actual = column_limb_row(
                            &a[left..left + R],
                            &b[right..right + (R - 1) * N + R],
                            &actual,
                        );
                        for (j, value) in actual.iter().enumerate() {
                            let sum = u128::from(prior)
                                + (0..(bk + 1) * R)
                                    .map(|k| {
                                        u128::from(a[row * N + k])
                                            * u128::from(b[k * N + bj * R + j])
                                    })
                                    .sum::<u128>();
                            assert_eq!(u128::from(*value), sum % Q);
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn column_limb_full_proofs_keep_exact_statement_and_challenge_binding() {
        for class in 0..4 {
            let a: Vec<_> = (0..CELLS)
                .map(|i| match class {
                    0 => 0,
                    1 => u32::from(i / N == i % N),
                    2 => ((i / N + 1) * (i % N + 3)) as u32,
                    _ => (Q - 1 - (i % 257) as u128) as u32,
                })
                .collect();
            let b: Vec<_> = (0..CELLS)
                .map(|i| match class {
                    0 => 0,
                    1 => u32::from(i / N == (i % N + 1) % N),
                    2 => ((i / N + 5) * (i % N + 2)) as u32,
                    _ => ((i as u128 * 65_537 + 258) % Q) as u32,
                })
                .collect();
            let task = task_id(&a, &b).unwrap();
            for challenge in [[0; 32], [255; 32], [79; 32]] {
                let proof = prove(challenge, &a, &b).unwrap();
                let expected = checked_value(verify_reference(challenge, task, [255; 32], &proof));
                assert_eq!(
                    checked_value(verify(challenge, task, [255; 32], &proof)),
                    expected
                );
                assert_eq!(
                    checked_value(verify_transposed(challenge, task, [255; 32], &proof)),
                    expected
                );
                assert_eq!(
                    checked_value(verify_column_limb(challenge, task, [255; 32], &proof)),
                    expected
                );
                assert_eq!(
                    checked_value(verify_full_limb(challenge, task, [255; 32], &proof)),
                    expected
                );
                let mut other = challenge;
                other[31] ^= 1;
                assert_eq!(
                    verify(other, task, [255; 32], &proof).unwrap_err(),
                    WorkError::Transcript
                );
                assert_eq!(
                    verify_transposed(other, task, [255; 32], &proof).unwrap_err(),
                    WorkError::Transcript
                );
                assert_eq!(
                    verify_column_limb(other, task, [255; 32], &proof).unwrap_err(),
                    WorkError::Transcript
                );
                assert_eq!(
                    verify_full_limb(other, task, [255; 32], &proof).unwrap_err(),
                    WorkError::Transcript
                );
            }
        }
    }

    #[test]
    fn producer_reduction_matches_remainder_at_boundaries_and_deterministic_samples() {
        let limit = 1_u128 << 70;
        let bounds = [
            0,
            1,
            Q - 1,
            Q,
            Q + 1,
            Q * Q - 1,
            64 * (Q - 1) * (Q - 1) + Q - 1,
            limit - 1,
        ];
        for x in bounds {
            assert_eq!(producer_reduce(x), (x % Q) as u32);
        }
        let mut seed = 19u128;
        for _ in 0..8192 {
            seed = seed
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            let x = seed % limit;
            assert_eq!(producer_reduce(x), (x % Q) as u32);
        }
    }
    #[test]
    fn optimized_producer_matches_full_verifier_for_structures_and_extreme_fields() {
        let shapes = [
            vec![0; CELLS],
            vec![(Q - 1) as u32; CELLS],
            (0..CELLS)
                .map(|i| ((i / N + 1) * (i % N + 1)) as u32)
                .collect(),
            (0..CELLS)
                .map(|i| if i % 71 == 0 { (Q - 2) as u32 } else { 0 })
                .collect(),
        ];
        for (index, a) in shapes.iter().enumerate() {
            let b = &shapes[(index + 1) % shapes.len()];
            let prepared = PreparedTask::new(a, b).unwrap();
            for c in [[0; 32], [7; 32], [255; 32]] {
                let proof = prepared.prove(c).unwrap();
                assert_eq!(proof, prove(c, a, b).unwrap());
                verify(c, task_id(a, b).unwrap(), [255; 32], &proof).unwrap();
            }
        }
    }
    fn matrices() -> (Vec<u32>, Vec<u32>) {
        (
            (0..CELLS).map(|i| (i % 31) as u32).collect(),
            (0..CELLS).map(|i| ((i * 7) % 37) as u32).collect(),
        )
    }
    #[test]
    fn decoded_output_is_the_real_matrix_product() {
        let (a, b) = matrices();
        let (p, _) = evaluate([7; 32], &a, &b).unwrap();
        assert_eq!(p, mul(&a, &b, N, N, N));
    }
    #[test]
    fn work_binds_challenge_and_inputs() {
        let (a, b) = matrices();
        let proof = prove([7; 32], &a, &b).unwrap();
        let task = task_id(&a, &b).unwrap();
        let v = verify([7; 32], task, [255; 32], &proof).unwrap();
        assert_eq!(v.challenge(), [7; 32]);
        assert_eq!(v.task(), task);
        assert_eq!(
            verify([8; 32], task, [255; 32], &proof).unwrap_err(),
            WorkError::Transcript
        );
        assert_eq!(
            verify([7; 32], [9; 32], [255; 32], &proof).unwrap_err(),
            WorkError::Task
        );
    }
    #[test]
    fn bad_proof_never_gains_a_verified_type() {
        let (a, b) = matrices();
        let mut proof = prove([3; 32], &a, &b).unwrap();
        let task = task_id(&a, &b).unwrap();
        proof[4 + 8 * CELLS] ^= 1;
        assert_eq!(
            verify([3; 32], task, [255; 32], &proof).unwrap_err(),
            WorkError::Product
        );
        proof[4 + 8 * CELLS] ^= 1;
        let last = proof.len() - 1;
        proof[last] ^= 1;
        assert_eq!(
            verify([3; 32], task, [255; 32], &proof).unwrap_err(),
            WorkError::Transcript
        );
        assert_eq!(
            verify([3; 32], task, [0; 32], &proof).unwrap_err(),
            WorkError::Target
        );
    }
    fn assert_verification_error(
        challenge: Hash,
        task: Hash,
        target: Hash,
        proof: &[u8],
        expected: WorkError,
        product_reconstructions: usize,
    ) {
        PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
        assert_eq!(
            verify(challenge, task, target, proof).unwrap_err(),
            expected
        );
        PRODUCT_RECONSTRUCTIONS.with(|count| {
            assert_eq!(count.get(), product_reconstructions);
        });
    }
    #[test]
    fn transcript_mismatch_skips_corrections_but_matching_digest_requires_product() {
        let (a, b) = matrices();
        let challenge = [3; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut bad_product = proof.clone();
        bad_product[4 + 8 * CELLS] ^= 1;
        let mut bad_both = bad_product.clone();
        bad_both[PROOF_BYTES - 1] ^= 1;
        assert_verification_error(
            challenge,
            task,
            [255; 32],
            &bad_both,
            WorkError::Transcript,
            0,
        );
        assert_verification_error([4; 32], task, [255; 32], &proof, WorkError::Transcript, 0);
        assert_verification_error(
            challenge,
            task,
            [255; 32],
            &bad_product,
            WorkError::Product,
            1,
        );
        PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
        let verified = verify(challenge, task, [255; 32], &proof).unwrap();
        assert_eq!(verified.product(), mul(&a, &b, N, N, N));
        PRODUCT_RECONSTRUCTIONS.with(|count| assert_eq!(count.get(), 1));
    }
    #[test]
    fn verifier_error_precedence_is_preserved_before_deferred_product() {
        let (a, b) = matrices();
        let challenge = [11; 32];
        let task = task_id(&a, &b).unwrap();
        let wrong_task = [0; 32];
        assert_ne!(task, wrong_task);
        let proof = prove(challenge, &a, &b).unwrap();
        let mut bad_fields = proof.clone();
        for pos in [4, 4 + 4 * CELLS, 4 + 8 * CELLS] {
            bad_fields[pos..pos + 4].copy_from_slice(&u32::MAX.to_le_bytes());
        }
        bad_fields[0] = b'X';
        assert_verification_error(
            challenge,
            wrong_task,
            [0; 32],
            &bad_fields[..PROOF_BYTES - 1],
            WorkError::Length,
            0,
        );
        assert_verification_error(
            challenge,
            wrong_task,
            [0; 32],
            &bad_fields,
            WorkError::Version,
            0,
        );
        bad_fields[0] = b'P';
        assert_verification_error(
            challenge,
            wrong_task,
            [0; 32],
            &bad_fields,
            WorkError::Target,
            0,
        );
        assert_verification_error(
            challenge,
            wrong_task,
            [255; 32],
            &bad_fields,
            WorkError::Field,
            0,
        );
        for pos in [4, 4 + 4 * CELLS] {
            let mut bad_input = proof.clone();
            bad_input[pos..pos + 4].copy_from_slice(&u32::MAX.to_le_bytes());
            assert_verification_error(
                challenge,
                wrong_task,
                [255; 32],
                &bad_input,
                WorkError::Field,
                0,
            );
        }
        let mut bad_both = proof.clone();
        bad_both[4 + 8 * CELLS] ^= 1;
        bad_both[PROOF_BYTES - 1] ^= 1;
        let ticket = hash(b"ticket", &[&challenge, &bad_both[PROOF_BYTES - 32..]]);
        let mut lower_target = ticket;
        for byte in lower_target.iter_mut().rev() {
            if *byte != 0 {
                *byte -= 1;
                break;
            }
            *byte = 255;
        }
        assert_ne!(lower_target, [0; 32]);
        assert!(lower_target < ticket);
        assert_verification_error(
            challenge,
            wrong_task,
            lower_target,
            &bad_both,
            WorkError::Task,
            0,
        );
        assert_verification_error(
            challenge,
            task,
            lower_target,
            &bad_both,
            WorkError::Target,
            0,
        );
        assert_eq!(evaluate(challenge, &[], &b), Err(WorkError::Length));
        assert_eq!(
            evaluate(challenge, &vec![u32::MAX; CELLS], &[]),
            Err(WorkError::Field)
        );
    }
    #[test]
    fn final_output_only_shortcut_is_not_a_transcript_proof() {
        let zeros = vec![0; CELLS];
        let mut proof = prove([4; 32], &zeros, &zeros).unwrap();
        assert_eq!(&proof[4 + 8 * CELLS..4 + 12 * CELLS], &vec![0; 4 * CELLS]);
        let length = proof.len();
        proof[length - 32..].fill(0);
        assert_eq!(
            verify([4; 32], task_id(&zeros, &zeros).unwrap(), [255; 32], &proof).unwrap_err(),
            WorkError::Transcript
        );
    }
    #[test]
    fn expansion_cannot_exceed_fixed_hash_budget() {
        assert_eq!(
            expand([0; 32], 0, 1025).unwrap_err(),
            WorkError::NoiseBudget
        );
    }
    #[test]
    fn exact_length_and_field_are_required() {
        assert_eq!(
            verify([0; 32], [0; 32], [255; 32], &[]).unwrap_err(),
            WorkError::Length
        );
        let mut a = vec![0; CELLS];
        a[0] = u32::MAX;
        assert_eq!(prove([0; 32], &a, &a).unwrap_err(), WorkError::Field);
    }

    #[test]
    fn proof_encoding_precheck_enforces_exact_wire_and_all_matrix_boundaries() {
        let mut proof = vec![0; PROOF_BYTES];
        proof[..4].copy_from_slice(b"PNW1");
        assert_eq!(precheck_proof_encoding(&proof), Ok(()));
        for word in proof[4..PROOF_BYTES - 32].chunks_exact_mut(4) {
            word.copy_from_slice(&((Q - 1) as u32).to_le_bytes());
        }
        // The same all-ones words would be invalid fields, but a digest is opaque.
        proof[PROOF_BYTES - 32..].fill(255);
        assert_eq!(precheck_proof_encoding(&proof), Ok(()));
        for length in [0, 3, 4, PROOF_BYTES - 1] {
            assert_eq!(
                precheck_proof_encoding(&proof[..length]),
                Err(WorkError::Length)
            );
        }
        let mut longer = proof.clone();
        longer.push(0);
        assert_eq!(precheck_proof_encoding(&longer), Err(WorkError::Length));
        let mut version = proof.clone();
        version[0] ^= 1;
        assert_eq!(precheck_proof_encoding(&version), Err(WorkError::Version));
        for matrix in 0..3 {
            for cell in [0, CELLS / 2, CELLS - 1] {
                for invalid in [Q as u32, u32::MAX] {
                    let mut changed = proof.clone();
                    let at = 4 + (matrix * CELLS + cell) * 4;
                    changed[at..at + 4].copy_from_slice(&invalid.to_le_bytes());
                    assert_eq!(precheck_proof_encoding(&changed), Err(WorkError::Field));
                }
            }
        }
    }

    #[test]
    fn proof_encoding_precheck_never_substitutes_for_full_work_or_cancellation() {
        let (a, b) = matrices();
        let challenge = [57; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        assert_eq!(precheck_proof_encoding(&proof), Ok(()));
        let verified = verify(challenge, task, [255; 32], &proof).unwrap();
        assert_eq!(verified.challenge(), challenge);
        assert_eq!(verified.task(), task);
        assert_eq!(
            field_bytes(verified.product()),
            proof[4 + 2 * CELLS * 4..PROOF_BYTES - 32]
        );

        let mut wrong_task = task;
        wrong_task[0] ^= 1;
        let mut below_ticket = [0; 32];
        below_ticket[31] = 1;
        assert!(verified.ticket() > below_ticket);
        let mut bad_trace = proof.clone();
        bad_trace[PROOF_BYTES - 1] ^= 1;
        let mut bad_product = proof.clone();
        let at = 4 + 2 * CELLS * 4;
        let original = u32::from_le_bytes(bad_product[at..at + 4].try_into().unwrap());
        let changed = ((u128::from(original) + 1) % Q) as u32;
        bad_product[at..at + 4].copy_from_slice(&changed.to_le_bytes());
        for (expected_task, target, bytes, expected_error) in [
            (wrong_task, [255; 32], proof.as_slice(), WorkError::Task),
            (task, below_ticket, proof.as_slice(), WorkError::Target),
            (task, [255; 32], bad_trace.as_slice(), WorkError::Transcript),
            (task, [255; 32], bad_product.as_slice(), WorkError::Product),
        ] {
            assert_eq!(precheck_proof_encoding(bytes), Ok(()));
            assert_eq!(
                verify(challenge, expected_task, target, bytes).unwrap_err(),
                expected_error
            );
        }

        let mut reached_final_boundary = false;
        let cancelled = verify_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
            if point == VerificationProgress::BeforeVerifiedWork {
                reached_final_boundary = true;
                Err("cancelled after complete replay")
            } else {
                Ok(())
            }
        });
        assert!(reached_final_boundary);
        assert_eq!(
            cancelled.unwrap_err(),
            VerificationError::Cancelled("cancelled after complete replay")
        );
    }

    #[test]
    fn proof_encoding_precheck_preserves_full_verifier_zero_target_precedence() {
        let mut proof = vec![0; PROOF_BYTES];
        proof[..4].copy_from_slice(b"PNW1");
        proof[4..8].copy_from_slice(&(Q as u32).to_le_bytes());
        assert_eq!(precheck_proof_encoding(&proof), Err(WorkError::Field));
        for kernel in [
            VerificationKernel::ScalarReference,
            VerificationKernel::Transposed,
            VerificationKernel::LimbTranscript,
            VerificationKernel::ColumnLimbTranscript,
            VerificationKernel::FullLimb,
        ] {
            for (target, expected_error) in
                [([0; 32], WorkError::Target), ([255; 32], WorkError::Field)]
            {
                let mut calls = 0;
                let result = verify_with_kernel(
                    [0; 32],
                    [0; 32],
                    target,
                    &proof,
                    &mut |_| {
                        calls += 1;
                        Ok::<(), ()>(())
                    },
                    kernel,
                );
                assert_eq!(
                    result.unwrap_err(),
                    VerificationError::Relation(expected_error)
                );
                assert_eq!(calls, 0);
            }
        }
    }

    #[test]
    fn controlled_verification_preserves_full_success_and_late_relation_errors() {
        let (a, b) = matrices();
        let challenge = [17; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let ordinary = verify(challenge, task, [255; 32], &proof).unwrap();
        let controlled = verify_with_progress(challenge, task, [255; 32], &proof, &mut |_| {
            Ok::<(), &str>(())
        })
        .unwrap();
        assert_eq!(controlled.challenge(), ordinary.challenge());
        assert_eq!(controlled.task(), ordinary.task());
        assert_eq!(controlled.ticket(), ordinary.ticket());
        assert_eq!(
            field_bytes(controlled.product()),
            field_bytes(ordinary.product())
        );
        let mut bad_product = proof.clone();
        bad_product[4 + 8 * CELLS] ^= 1;
        let mut bad_trace = bad_product.clone();
        bad_trace[PROOF_BYTES - 1] ^= 1;
        for (bad, expected) in [
            (&bad_product, WorkError::Product),
            (&bad_trace, WorkError::Transcript),
        ] {
            assert_eq!(
                verify(challenge, task, [255; 32], bad).unwrap_err(),
                expected
            );
            assert_eq!(
                verify_with_progress(challenge, task, [255; 32], bad, &mut |_| Ok::<(), &str>(()))
                    .unwrap_err(),
                VerificationError::Relation(expected)
            );
        }
    }
    #[test]
    fn cancellation_on_last_transcript_tile_never_starts_product_reconstruction() {
        let (a, b) = matrices();
        let challenge = [18; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
        let mut tiles = 0;
        let error = verify_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
            if let VerificationProgress::TranscriptTile { row, column, inner } = point {
                tiles += 1;
                if (row, column, inner) == (N / R - 1, N / R - 1, N / R - 1) {
                    return Err("local deadline");
                }
            }
            Ok(())
        })
        .unwrap_err();
        assert_eq!(error, VerificationError::Cancelled("local deadline"));
        assert_eq!(tiles, (N / R).pow(3));
        PRODUCT_RECONSTRUCTIONS.with(|count| assert_eq!(count.get(), 0));
    }
    #[test]
    fn product_row_and_final_cancellation_never_yield_verified_work() {
        let (a, b) = matrices();
        let challenge = [19; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        for final_boundary in [false, true] {
            PRODUCT_RECONSTRUCTIONS.with(|count| count.set(0));
            let mut correcting = false;
            let error = verify_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                if point == VerificationProgress::BeforeProduct {
                    correcting = true;
                }
                if (final_boundary && point == VerificationProgress::BeforeVerifiedWork)
                    || (!final_boundary
                        && correcting
                        && point == (VerificationProgress::MatrixRow { row: 16 }))
                {
                    return Err("local stop");
                }
                Ok(())
            })
            .unwrap_err();
            assert_eq!(error, VerificationError::Cancelled("local stop"));
            PRODUCT_RECONSTRUCTIONS.with(|count| assert_eq!(count.get(), 1));
        }
    }
    #[test]
    fn cheap_rejection_precedes_progress_and_noise_cancellation_is_local() {
        let (a, b) = matrices();
        let challenge = [20; 32];
        let task = task_id(&a, &b).unwrap();
        let proof = prove(challenge, &a, &b).unwrap();
        let mut observations = 0;
        let mut deny = |_| {
            observations += 1;
            Err("cancelled")
        };
        for (bytes, expected_task, target, expected) in [
            (&[][..], task, [255; 32], WorkError::Length),
            (&proof[..], [0; 32], [255; 32], WorkError::Task),
            (&proof[..], task, [0; 32], WorkError::Target),
        ] {
            assert_eq!(
                verify_with_progress(challenge, expected_task, target, bytes, &mut deny)
                    .unwrap_err(),
                VerificationError::Relation(expected)
            );
        }
        assert_eq!(observations, 0);
        assert_eq!(
            verify_with_progress(challenge, task, [255; 32], &proof, &mut |point| {
                if point
                    == (VerificationProgress::Noise {
                        label: 0,
                        counter: 1,
                    })
                {
                    Err("cancelled")
                } else {
                    Ok(())
                }
            })
            .unwrap_err(),
            VerificationError::Cancelled("cancelled")
        );
    }
    #[test]
    fn fixed_task_preparation_is_byte_identical_across_challenges_and_shapes() {
        for class in 0..4 {
            let a: Vec<u32> = (0..CELLS)
                .map(|i| match class {
                    0 => 0,
                    1 => u32::from(i / N == i % N),
                    2 => ((i / N + 1) * (i % N + 1)) as u32,
                    _ => (i % 31) as u32,
                })
                .collect();
            let b: Vec<u32> = (0..CELLS)
                .map(|i| match class {
                    0 => 0,
                    1 => u32::from(i / N == i % N),
                    2 => ((i / N + 2) * (i % N + 1)) as u32,
                    _ => ((i * 7) % 37) as u32,
                })
                .collect();
            let prepared = PreparedTask::new(&a, &b).unwrap();
            let task = task_id(&a, &b).unwrap();
            for challenge in [[0; 32], [255; 32], [7; 32]] {
                let actual = prepared.prove(challenge).unwrap();
                assert_eq!(actual, prove(challenge, &a, &b).unwrap());
                verify(challenge, task, [255; 32], &actual).unwrap();
            }
        }
        assert!(PreparedTask::new(&[], &[]).is_err());
        assert!(PreparedTask::new(&vec![u32::MAX; CELLS], &vec![0; CELLS]).is_err());
    }
}
