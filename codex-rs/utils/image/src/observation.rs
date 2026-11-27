use std::path::Path;
use std::sync::LazyLock;

use codex_utils_cache::sha1_digest;

use crate::EncodedImage;
use crate::IMAGE_CACHE;
use crate::ImageCache;
use crate::ImageCacheKey;
use crate::ImageProcessingError;
use crate::MAX_IMAGE_CACHE_BYTES;
use crate::PromptImageMode;
use crate::cache_image;
use crate::load_data_url_for_prompt_with;
use crate::load_for_prompt_bytes_uncached_observed;

/// Completed synchronous checkpoints in prompt image loading.
///
/// Checkpoints do not imply that an image was resized or retained in the cache.
/// Observers run after cache guards have been released and receive no image data.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PromptImageLoadPhase {
    DataUrlDecoded,
    CacheHit,
    CacheMiss,
    PixelsDecoded,
    ResizeFinished,
    OutputEncoded,
    OriginalBytesReady,
    CacheStoreFinished,
}

impl PromptImageLoadPhase {
    /// Returns a fixed diagnostic label, independent of image contents.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::DataUrlDecoded => "image_data_url_decoded",
            Self::CacheHit => "image_cache_hit",
            Self::CacheMiss => "image_cache_miss",
            Self::PixelsDecoded => "image_pixels_decoded",
            Self::ResizeFinished => "image_resize_finished",
            Self::OutputEncoded => "image_output_encoded",
            Self::OriginalBytesReady => "image_original_bytes_ready",
            Self::CacheStoreFinished => "image_cache_store_finished",
        }
    }
}

/// Loads an image using the normal cache and reports completed checkpoints.
///
/// The callback executes synchronously and can perturb observed latency. A cache
/// hit reports two checkpoints; an uncached success reports six. On error, later
/// checkpoints are not reported. Cache-store completion does not promise that an
/// entry was retained: the existing runtime and byte-capacity rules still apply.
pub fn load_data_url_for_prompt_with_observer(
    image_url: &str,
    mode: PromptImageMode,
    mut observe: impl FnMut(PromptImageLoadPhase),
) -> Result<EncodedImage, ImageProcessingError> {
    load_data_url_for_prompt_observed(image_url, mode, &IMAGE_CACHE, &mut observe)
}

fn load_data_url_for_prompt_observed(
    image_url: &str,
    mode: PromptImageMode,
    cache: &LazyLock<ImageCache>,
    observe: &mut impl FnMut(PromptImageLoadPhase),
) -> Result<EncodedImage, ImageProcessingError> {
    load_data_url_for_prompt_with(image_url, mode, |path, file_bytes, mode| {
        observe(PromptImageLoadPhase::DataUrlDecoded);
        load_for_prompt_bytes_observed(path, file_bytes, mode, cache, observe)
    })
}

pub(super) fn load_for_prompt_bytes_observed(
    path: &Path,
    file_bytes: Vec<u8>,
    mode: PromptImageMode,
    cache: &LazyLock<ImageCache>,
    observe: &mut impl FnMut(PromptImageLoadPhase),
) -> Result<EncodedImage, ImageProcessingError> {
    let path_buf = path.to_path_buf();

    let key = ImageCacheKey {
        digest: sha1_digest(&file_bytes),
        mode,
    };

    if let Some(image) = cache.get(&key) {
        observe(PromptImageLoadPhase::CacheHit);
        return Ok(image);
    }
    observe(PromptImageLoadPhase::CacheMiss);

    let image = load_for_prompt_bytes_uncached_observed(&path_buf, file_bytes, mode, observe)?;
    cache_image(cache, key, image.clone(), MAX_IMAGE_CACHE_BYTES);
    observe(PromptImageLoadPhase::CacheStoreFinished);
    Ok(image)
}

#[cfg(test)]
#[path = "observation_tests.rs"]
mod tests;
