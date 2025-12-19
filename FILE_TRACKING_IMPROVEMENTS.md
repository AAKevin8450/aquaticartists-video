# File Tracking System Improvements

**Date**: 2025-12-19
**Status**: ✅ Implementation Complete

## Overview
Enhanced the video analysis application with a robust file storage and tracking system that manages both source and proxy video files with comprehensive media metadata.

---

## Changes Made

### 1. Database Schema Enhancements

#### Files Table - New Columns
Added 10 new columns to track file relationships and media metadata:

| Column | Type | Description |
|--------|------|-------------|
| `is_proxy` | BOOLEAN | Flag indicating if file is a proxy (0=source, 1=proxy) |
| `source_file_id` | INTEGER | Foreign key linking proxy to source file |
| `local_path` | TEXT | Local filesystem path where file is stored |
| `resolution_width` | INTEGER | Video width in pixels |
| `resolution_height` | INTEGER | Video height in pixels |
| `frame_rate` | REAL | Frame rate (fps) |
| `codec_video` | TEXT | Video codec (e.g., h264, hevc) |
| `codec_audio` | TEXT | Audio codec (e.g., aac, mp3) |
| `duration_seconds` | REAL | Duration in seconds |
| `bitrate` | INTEGER | Bitrate in bits per second |

#### Transcripts Table - New Column
- `file_id` (INTEGER): Foreign key linking transcripts to source files

**Migration File**: `migrations/004_enhance_file_tracking.sql`
**Migration Script**: `run_migration_004.py`

### 2. File Storage Structure

#### New Folder: `proxy_video/`
All proxy videos are now stored persistently in this dedicated folder:
- **Naming Convention**: `{upload_id}_720p15.mp4`
- **Purpose**: Reusable proxy files for future processing
- **Location**: Project root directory

#### Source Video Storage
Source videos remain in: `uploads/{upload_id}/{filename}`

### 3. New Utility: Media Metadata Extraction

**File**: `app/utils/media_metadata.py`

**Key Functions**:
- `extract_media_metadata(file_path)` - Extract all metadata using FFprobe
- `format_media_metadata(metadata)` - Format metadata as human-readable string
- `get_video_resolution(file_path)` - Quick resolution extraction
- `get_video_duration(file_path)` - Quick duration extraction
- `verify_proxy_spec(file_path)` - Verify proxy meets 720p15 specification

**Features**:
- Uses FFprobe (part of FFmpeg suite)
- Extracts resolution, frame rate, codecs, duration, bitrate
- Graceful error handling with MediaMetadataError exception
- Supports both video and image files

### 4. Database CRUD Methods

**File**: `app/database.py`

**New Methods**:
```python
# Create source file with media metadata
create_source_file(filename, s3_key, file_type, size_bytes, content_type,
                  local_path, resolution_width, resolution_height,
                  frame_rate, codec_video, codec_audio,
                  duration_seconds, bitrate, metadata)

# Create proxy file linked to source
create_proxy_file(source_file_id, filename, s3_key, size_bytes,
                 content_type, local_path, resolution_width,
                 resolution_height, frame_rate, codec_video,
                 codec_audio, duration_seconds, bitrate, metadata)

# Get proxy for a source file
get_proxy_for_source(source_file_id)

# Get source for a proxy file
get_source_for_proxy(proxy_file_id)

# List only source files (exclude proxies)
list_source_files(file_type, limit, offset)
```

### 5. Upload Workflow Changes

**File**: `app/routes/upload.py`

**New Workflow**:
1. User uploads video file
2. **Server saves source video** to `uploads/{upload_id}/{filename}`
3. **Extract metadata** from source video using FFprobe
4. **Create source file record** in database with full metadata
5. **Generate 720p15 proxy** using FFmpeg
6. **Save proxy** to `proxy_video/{upload_id}_720p15.mp4`
7. **Extract metadata** from proxy video
8. **Upload proxy to S3** at `uploads/{upload_id}/proxy_720p15.mp4`
9. **Create proxy file record** in database linked to source
10. **Return both file IDs** to client

**Key Changes**:
- ✅ Proxy creation is now **always automatic** (no checkbox)
- ✅ Both source and proxy files tracked in database
- ✅ Media metadata extracted and stored for both files
- ✅ Proxy files stored locally in `proxy_video/` folder
- ✅ Source file kept locally (not uploaded to S3)

### 6. Frontend Updates

**File**: `app/templates/upload.html`

**Changes**:
- ❌ **Removed** proxy creation checkbox (automatic now)
- ✅ **Updated** help text to inform users about automatic proxy creation
- ✅ **Removed** JavaScript code for checkbox show/hide logic
- ✅ **Removed** `create_proxy` form data parameter

**New Help Text**:
> "Video: MP4, MOV, AVI, MKV (Max 10GB) - Proxy (720p, 15fps) automatically created for Nova analysis"

---

## Benefits

### 1. **Complete File Tracking**
- Every source video and its proxy are tracked separately
- Full relationship mapping between source and proxy files
- Media metadata stored for quick queries without re-scanning files

### 2. **Proxy File Reusability**
- Proxy files stored in dedicated `proxy_video/` folder
- Can be reused for multiple analysis jobs
- Reduces redundant transcoding operations

### 3. **Rich Metadata**
- Resolution, frame rate, codec information available
- Enables filtering and querying by media properties
- Supports future features (e.g., "Show all 1080p videos", "Show h264 videos")

### 4. **Transcript Integration** (Future)
- `transcripts.file_id` column ready for linking transcripts to source files
- Can query all transcripts for a specific video
- Maintains relationship integrity via foreign keys

### 5. **Simplified User Experience**
- No checkbox confusion - proxy creation is automatic
- Clearer expectations about file processing
- Faster upload workflow

---

## Database Migration

### Running the Migration

```bash
cd E:\coding\video
python run_migration_004.py
```

**Expected Output**:
```
Running migration: migrations\004_enhance_file_tracking.sql
Database: data\app.db
[OK] Executed statement 5/18
[OK] Executed statement 6/18
...
[SUCCESS] Migration completed successfully!

Files table columns (18):
  - id
  - filename
  - s3_key
  - ... (full list)
```

### Migration Safety
- **Idempotent**: Can be run multiple times safely
- **Non-destructive**: Only adds columns, doesn't drop data
- **Backward compatible**: Existing records remain valid
- **Automatic data migration**: Updates existing files with metadata from JSON

---

## File Structure

```
E:\coding\video\
├── proxy_video/               # NEW - Proxy video storage
│   ├── .gitkeep
│   └── {upload_id}_720p15.mp4
├── uploads/                   # Source video storage
│   └── {upload_id}/
│       └── {filename}
├── migrations/
│   └── 004_enhance_file_tracking.sql  # NEW - Schema migration
├── app/
│   ├── utils/
│   │   └── media_metadata.py  # NEW - FFprobe metadata extraction
│   ├── routes/
│   │   └── upload.py          # UPDATED - New workflow
│   ├── database.py            # UPDATED - New CRUD methods
│   └── templates/
│       └── upload.html        # UPDATED - Removed checkbox
└── run_migration_004.py       # NEW - Migration runner
```

---

## API Response Changes

### Old Response (Image Upload)
```json
{
  "file_id": 123,
  "message": "File uploaded successfully",
  "s3_key": "uploads/.../file.mp4",
  "size_bytes": 1024000,
  "display_size": "1.0 MB"
}
```

### New Response (Video Upload)
```json
{
  "file_id": 123,              // Source file ID
  "proxy_file_id": 124,        // NEW - Proxy file ID
  "message": "File uploaded successfully",
  "s3_key": "uploads/.../proxy_720p15.mp4",
  "size_bytes": 5242880,       // Source file size
  "proxy_size_bytes": 1048576, // NEW - Proxy file size
  "display_size": "5.0 MB",
  "duration_seconds": 120.5,
  "display_duration": "2m 0s"
}
```

---

## Testing Checklist

### ✅ Completed
- [x] Database migration successful
- [x] `proxy_video/` folder created
- [x] Media metadata extraction utility created
- [x] Database CRUD methods added
- [x] Upload route updated
- [x] Frontend checkbox removed

### 🔄 To Test
- [ ] Upload a video file via web interface
- [ ] Verify source file created in `uploads/{id}/`
- [ ] Verify proxy file created in `proxy_video/`
- [ ] Verify proxy uploaded to S3
- [ ] Verify both file records in database
- [ ] Verify media metadata populated correctly
- [ ] Verify file relationships (source_file_id)
- [ ] Test video analysis with new file records
- [ ] Test Nova analysis using proxy files

---

## Future Enhancements

### Phase 2 - Transcript Integration
- Update transcription service to populate `transcripts.file_id`
- Add queries to list all transcripts for a source file
- Show transcript status in file listing

### Phase 3 - Advanced Querying
- Filter files by resolution (e.g., "Show all 1080p videos")
- Filter by codec (e.g., "Show all HEVC videos")
- Filter by duration range
- Sort by bitrate, frame rate, etc.

### Phase 4 - Proxy Management
- Option to regenerate proxies with different specs
- Support multiple proxy formats (480p, 1080p, etc.)
- Automatic cleanup of unused proxy files

### Phase 5 - S3 Source Upload (Optional)
- Option to upload source files to S3 for backup
- Separate S3 bucket for source vs. proxy files
- Lifecycle policies for archival storage

---

## Dependencies

### Required
- **FFmpeg**: For proxy video generation
- **FFprobe**: For media metadata extraction (part of FFmpeg)
- **Python 3.12+**: For type hints with `|` syntax

### Python Packages
- `sqlite3`: Database operations (built-in)
- `pathlib`: File path handling (built-in)
- `subprocess`: FFprobe execution (built-in)

---

## Configuration

### Environment Variables (.env)
No new environment variables required. Existing configuration is sufficient:
```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET_NAME=video-analysis-app-676206912644
```

### Flask Config
Uses existing `UPLOAD_FOLDER` configuration for source video storage.

---

## Troubleshooting

### Migration Fails
**Issue**: `run_migration_004.py` fails with SQL errors
**Solution**: Check if database is locked, close any connections, retry

### FFprobe Not Found
**Issue**: `MediaMetadataError: ffprobe is not available`
**Solution**: Install FFmpeg (includes FFprobe) and ensure it's in PATH

### Proxy File Not Created
**Issue**: Proxy file missing from `proxy_video/` folder
**Solution**: Check FFmpeg availability, check upload logs for errors

### Database Columns Missing
**Issue**: New columns not showing in `PRAGMA table_info(files)`
**Solution**: Re-run migration, check for error messages

---

## Summary

This update transforms the application from a simple file upload system to a comprehensive video management platform with:

✅ **Dual file tracking** (source + proxy)
✅ **Rich media metadata** (resolution, codecs, frame rate)
✅ **Persistent proxy storage** (reusable for multiple jobs)
✅ **Automatic workflow** (no user configuration needed)
✅ **Future-ready** (transcript integration, advanced queries)

All TBs of local video can now be efficiently processed with Nova using automatically generated 720p15 proxies, with full tracking of both source and proxy files including detailed media metadata.
