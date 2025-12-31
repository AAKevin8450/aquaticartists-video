# Image Proxy Optimization Plan for Nova 2 Lite

## Executive Summary

This plan outlines the implementation of optimized image proxies for AWS Nova 2 Lite analysis. Based on AWS documentation, Nova 2 Lite automatically rescales images to a minimum of 896 pixels on one side. By pre-generating optimized proxies at this target resolution, we can significantly reduce:
- S3 storage costs
- Network transfer time to AWS
- API payload sizes

## Research Findings

### Nova 2 Lite Image Processing Specifications

**Source**: [AWS Nova Image Understanding Documentation](https://docs.aws.amazon.com/nova/latest/userguide/modalities-image.html)

| Specification | Value |
|---------------|-------|
| Maximum Resolution | 8,000 x 8,000 pixels |
| Minimum Effective Resolution | 896px on at least one side |
| Payload Limit (embedded) | 25 MB |
| Payload Limit (S3 URI) | 2 GB |
| Supported Formats | PNG, JPEG, GIF, WebP |

**Internal Rescaling Logic:**
1. Nova identifies the closest aspect ratio from: 1:1, 1:2, 1:3, 1:4, 1:5, 1:6, 1:7, 1:8, 1:9, 2:3, 2:4 (and transposes)
2. Rescales so that **at least one side ≥ 896px** OR matches the shorter side of original (whichever is larger)
3. Maintains the closest aspect ratio throughout

**Token Cost by Resolution:**

| Image Resolution | Estimated Tokens |
|------------------|-----------------|
| 900 x 450 | ~515 |
| 900 x 900 | ~1,035 |
| 1400 x 900 | ~1,600 |
| 1800 x 900 | ~2,060 |
| 1300 x 1300 | ~2,155 |

### Key Insight

Since Nova automatically rescales images to a minimum of 896px, **any pixels beyond this resolution on the shorter side are wasted bandwidth**. The model receives the same effective visual information whether you send a 4000x3000 image or a 1195x896 image (same 4:3 aspect ratio).

## Optimal Proxy Strategy

### Target Specifications

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Target shorter side | 896 pixels | Matches Nova's minimum rescale threshold |
| Aspect ratio | Preserve original | Nova expects natural aspect ratios |
| Format (photos) | JPEG | Best compression for photographic content |
| Format (graphics/text) | PNG | Lossless for sharp edges and text |
| JPEG Quality | 85% | Optimal balance of size vs quality |
| Color space | sRGB | Standard web color space |

### Scaling Rules

1. **If shorter side > 896px**: Scale down so shorter side = 896px
2. **If shorter side ≤ 896px**: Keep original dimensions (no upscaling)
3. **Always maintain original aspect ratio**

### Expected Savings

| Original Size | Original Dimensions | Proxy Dimensions | Estimated Size | Savings |
|--------------|---------------------|------------------|----------------|---------|
| 4 MB | 4000 x 3000 | 1195 x 896 | ~200 KB | ~95% |
| 3 MB | 6000 x 4000 | 1344 x 896 | ~250 KB | ~92% |
| 2 MB | 3840 x 2160 | 1592 x 896 | ~280 KB | ~86% |
| 1 MB | 1920 x 1080 | 1592 x 896 | ~280 KB | ~72% |
| 500 KB | 1200 x 800 | 1200 x 800 | ~500 KB | 0% (no resize) |
| 200 KB | 800 x 600 | 800 x 600 | ~200 KB | 0% (no resize) |

## Implementation Plan

### Phase 1: Core Image Proxy Service

**File**: `app/services/image_proxy_service.py`

```
ImageProxyService
├── create_proxy(source_path, output_path, options)
│   ├── Detect image format (JPEG, PNG, etc.)
│   ├── Get original dimensions
│   ├── Calculate target dimensions (896px shorter side max)
│   ├── Resize with Pillow/PIL (high-quality Lanczos)
│   └── Save with optimal compression
├── needs_proxy(width, height) -> bool
│   └── Returns True if shorter side > 896px
├── calculate_target_dimensions(width, height) -> (w, h)
│   └── Maintains aspect ratio, caps shorter side at 896
└── get_optimal_format(source_path) -> str
    └── Returns 'JPEG' or 'PNG' based on content analysis
```

**Dependencies:**
- Pillow (PIL) - already available in project
- No FFmpeg required (unlike video proxies)

### Phase 2: Database Schema

**Table**: `files` (existing)
- Already has `is_proxy` and `source_file_id` columns
- Already has `resolution_width` and `resolution_height`
- No schema changes required

**Proxy Storage Location**: `proxy_image/`
- Parallel to existing `proxy_video/` directory
- Filename pattern: `{original_stem}_{source_file_id}_nova.{ext}`

### Phase 3: API Endpoints

**Endpoint**: `POST /api/files/<int:file_id>/create-image-proxy`
```json
Request: {}
Response: {
    "proxy_id": 456,
    "source_id": 123,
    "original_size_bytes": 4000000,
    "proxy_size_bytes": 200000,
    "savings_percent": 95.0,
    "original_dimensions": [4000, 3000],
    "proxy_dimensions": [1195, 896]
}
```

**Endpoint**: `POST /api/batch/image-proxy`
```json
Request: {
    "file_ids": [1, 2, 3]
}
Response: {
    "job_id": "batch-image-proxy-abc123",
    "total_files": 3,
    "message": "Batch image proxy creation started"
}
```

### Phase 4: Integration Points

#### 4.1 Nova Analysis Route Updates

**File**: `app/routes/nova_analysis.py`

Before sending image to Nova:
1. Check if image needs a proxy (shorter side > 896px)
2. If proxy exists, use it
3. If proxy needed but doesn't exist, create on-demand
4. Upload proxy to S3 (not original)
5. Send S3 URI to Nova

#### 4.2 Upload Route Updates

**File**: `app/routes/upload.py`

Option A: **Eager proxy creation** (recommended)
- Create image proxy immediately on upload (like video proxies)
- Pros: Proxies ready when needed, consistent behavior
- Cons: Slightly longer upload time

Option B: **Lazy proxy creation**
- Create proxy only when Nova analysis is requested
- Pros: No overhead for images never analyzed
- Cons: Delay on first Nova analysis

#### 4.3 Batch Processing Updates

**File**: `app/routes/file_management/batch.py`

Add new batch action type: `image-proxy`
- Similar to existing `proxy` action for videos
- Uses same BatchJob infrastructure
- Progress tracking with ETA

### Phase 5: UI Updates

**File**: `app/templates/file_management.html`

Add to image file cards:
- "Create Proxy" button (if no proxy exists)
- Proxy status indicator
- Size comparison (original vs proxy)

**File**: `app/static/js/file_management.js`

Add batch action option:
- "Create Image Proxies" in batch actions dropdown
- Only enabled when image files are selected

## Technical Specifications

### Pillow Configuration

```python
from PIL import Image

def create_image_proxy(source_path, output_path, quality=85):
    with Image.open(source_path) as img:
        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Preserve transparency info for PNG
            format = 'PNG'
        else:
            img = img.convert('RGB')
            format = 'JPEG'

        # Calculate target size
        width, height = img.size
        shorter_side = min(width, height)

        if shorter_side > 896:
            scale = 896 / shorter_side
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Save with optimization
        if format == 'JPEG':
            img.save(output_path, format='JPEG', quality=quality, optimize=True)
        else:
            img.save(output_path, format='PNG', optimize=True)
```

### Performance Considerations

| Factor | Approach |
|--------|----------|
| Memory | Process one image at a time |
| CPU | Pillow uses native C extensions |
| Disk I/O | Stream processing, temp files |
| Parallelism | Thread pool for batch operations |

### Error Handling

1. **Corrupt images**: Log error, skip file, continue batch
2. **Unsupported formats**: Convert to PNG/JPEG first
3. **Insufficient disk space**: Check before processing, fail fast
4. **Memory limits**: Limit max image dimensions (already enforced by Nova's 8000x8000 limit)

## Migration Plan

### Existing Images

1. Add management command: `python -m scripts.create_image_proxies`
2. Options: `--dry-run`, `--limit N`, `--force`
3. Process in batches with progress reporting

### Backward Compatibility

- Existing images without proxies continue to work (use original)
- Nova analysis falls back to original if proxy missing
- No breaking changes to existing API contracts

## Success Metrics

| Metric | Target |
|--------|--------|
| Average size reduction | >80% for images >1MB |
| Proxy creation time | <2 seconds per image |
| Nova API latency improvement | 30-50% reduction |
| S3 storage savings | >70% for analyzed images |

## Timeline Estimate

| Phase | Components | Effort |
|-------|------------|--------|
| Phase 1 | Core service | Medium |
| Phase 2 | Database (none needed) | None |
| Phase 3 | API endpoints | Medium |
| Phase 4 | Integration | Medium |
| Phase 5 | UI updates | Low |
| Migration | Backfill script | Low |

## Open Questions

1. **Format detection**: Should we analyze image content to decide JPEG vs PNG, or use original format?
   - Recommendation: Use original format unless RGBA→RGB conversion needed

2. **Proxy on upload vs on-demand**: Create proxies immediately or lazily?
   - Recommendation: Create on upload for consistency with video workflow

3. **Replace original in S3**: Should Nova use proxy S3 key exclusively?
   - Recommendation: Yes, upload only proxies to S3 for Nova analysis

4. **Quality setting**: Fixed 85% or configurable?
   - Recommendation: Start with fixed 85%, add config later if needed

## References

- [Amazon Nova Image Understanding](https://docs.aws.amazon.com/nova/latest/userguide/modalities-image.html)
- [Amazon Nova 2 Multimodal Guide](https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-multimodal-models.html)
- [Nova 2 Foundation Models](https://aws.amazon.com/nova/models/)
- [Nova 2 Lite Technical Examination](https://medium.com/@leucopsis/amazon-nova-2-lite-a-technical-examination-145e9b17112a)
