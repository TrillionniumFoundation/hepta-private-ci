use std::error::Error;
use std::io::Cursor;
use std::num::NonZeroUsize;

use image::DynamicImage;
use image::ImageBuffer;
use image::ImageFormat;
use image::Rgba;

use super::*;
use crate::PromptImageResizeLimits;
use crate::data_url_from_bytes;
use crate::load_data_url_for_prompt_uncached;

fn png_bytes() -> Result<Vec<u8>, image::ImageError> {
    let pixels = ImageBuffer::from_fn(64, 32, |x, y| Rgba([x as u8, y as u8, 17, 255]));
    let mut bytes = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(pixels).write_to(&mut bytes, ImageFormat::Png)?;
    Ok(bytes.into_inner())
}

fn assert_same_image(actual: &EncodedImage, expected: &EncodedImage) {
    assert_eq!(
        (
            actual.bytes.as_ref(),
            &actual.mime,
            actual.source_width,
            actual.source_height,
            actual.width,
            actual.height,
        ),
        (
            expected.bytes.as_ref(),
            &expected.mime,
            expected.source_width,
            expected.source_height,
            expected.width,
            expected.height,
        )
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn observed_resize_and_cache_hit_preserve_output() -> Result<(), Box<dyn Error>> {
    let cache: LazyLock<ImageCache> = LazyLock::new(|| ImageCache::new(NonZeroUsize::MIN));
    let image_url = data_url_from_bytes("image/png", &png_bytes()?);
    let mode = PromptImageMode::ResizeWithLimits(PromptImageResizeLimits {
        max_dimension: 32,
        max_patches: 4,
    });
    let expected = load_data_url_for_prompt_uncached(&image_url, mode)?;
    let mut phases = Vec::new();
    let first = load_data_url_for_prompt_observed(&image_url, mode, &cache, &mut |phase| {
        phases.push(phase);
    })?;
    assert_same_image(&first, &expected);
    assert_eq!((first.width, first.height), (32, 16));
    assert_eq!(
        phases,
        [
            PromptImageLoadPhase::DataUrlDecoded,
            PromptImageLoadPhase::CacheMiss,
            PromptImageLoadPhase::PixelsDecoded,
            PromptImageLoadPhase::ResizeFinished,
            PromptImageLoadPhase::OutputEncoded,
            PromptImageLoadPhase::CacheStoreFinished,
        ]
    );

    phases.clear();
    let second = load_data_url_for_prompt_observed(&image_url, mode, &cache, &mut |phase| {
        phases.push(phase);
    })?;
    assert_same_image(&second, &expected);
    assert_eq!(
        phases,
        [
            PromptImageLoadPhase::DataUrlDecoded,
            PromptImageLoadPhase::CacheHit,
        ]
    );
    Ok(())
}

#[test]
fn original_bytes_and_disabled_cache_keep_their_behavior() -> Result<(), Box<dyn Error>> {
    let cache: LazyLock<ImageCache> = LazyLock::new(|| ImageCache::new(NonZeroUsize::MIN));
    let bytes = png_bytes()?;
    let image_url = data_url_from_bytes("image/png", &bytes);
    let expected = load_data_url_for_prompt_uncached(&image_url, PromptImageMode::Original)?;
    for _ in 0..2 {
        let mut phases = Vec::new();
        let image = load_data_url_for_prompt_observed(
            &image_url,
            PromptImageMode::Original,
            &cache,
            &mut |phase| phases.push(phase),
        )?;
        assert_same_image(&image, &expected);
        assert_eq!(image.bytes.as_ref(), bytes);
        assert_eq!((image.width, image.height), (64, 32));
        assert_eq!(
            phases,
            [
                PromptImageLoadPhase::DataUrlDecoded,
                PromptImageLoadPhase::CacheMiss,
                PromptImageLoadPhase::PixelsDecoded,
                PromptImageLoadPhase::ResizeFinished,
                PromptImageLoadPhase::OriginalBytesReady,
                PromptImageLoadPhase::CacheStoreFinished,
            ]
        );
    }
    Ok(())
}

#[test]
fn errors_preserve_the_result_and_do_not_report_later_completion() -> Result<(), Box<dyn Error>> {
    let cache: LazyLock<ImageCache> = LazyLock::new(|| ImageCache::new(NonZeroUsize::MIN));
    let invalid_image = data_url_from_bytes("image/png", b"not an image");
    for (image_url, expected_phases) in [
        ("not a data URL", Vec::new()),
        ("data:image/png,not-base64", Vec::new()),
        ("data:image/png;base64,!", Vec::new()),
        (
            invalid_image.as_str(),
            vec![
                PromptImageLoadPhase::DataUrlDecoded,
                PromptImageLoadPhase::CacheMiss,
            ],
        ),
    ] {
        let mode = PromptImageMode::Original;
        let expected = load_data_url_for_prompt_uncached(image_url, mode)
            .err()
            .ok_or("the invalid input must fail")?;
        let mut phases = Vec::new();
        let error = load_data_url_for_prompt_observed(image_url, mode, &cache, &mut |phase| {
            phases.push(phase);
        })
        .err()
        .ok_or("the observed invalid input must fail")?;
        assert_eq!(
            std::mem::discriminant(&error),
            std::mem::discriminant(&expected)
        );
        assert_eq!(error.to_string(), expected.to_string());
        assert_eq!(phases, expected_phases);
    }
    Ok(())
}
