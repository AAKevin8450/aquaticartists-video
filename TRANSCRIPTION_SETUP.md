# Local Video Transcription Setup Guide

This guide will help you set up and use the local video transcription feature in the AWS Video & Image Analysis application.

## Prerequisites

### 1. FFmpeg Installation (Required)

FFmpeg is required for extracting audio from video files.

#### Windows Installation:
1. Download FFmpeg from https://www.gyan.dev/ffmpeg/builds/
2. Extract the ZIP file to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your system PATH:
   - Open "Environment Variables" in Windows settings
   - Edit the "Path" variable under System Variables
   - Add new entry: `C:\ffmpeg\bin`
   - Click OK and restart your terminal

#### Verify Installation:
```bash
ffmpeg -version
```

### 2. Python Dependencies (Required)

Install the required Python packages:

```bash
cd E:\coding\video
.\.venv\Scripts\activate
pip install -r requirements.txt
```

This will install:
- `faster-whisper>=1.0.0` - Fast Whisper implementation
- `ffmpeg-python>=0.2.0` - Python FFmpeg bindings

### 3. GPU Acceleration (Optional but Recommended)

For 4-10x faster processing, install CUDA if you have an NVIDIA GPU:

1. Check if you have CUDA-capable GPU:
   - NVIDIA GeForce GTX/RTX series
   - NVIDIA Quadro/Tesla series

2. Install NVIDIA CUDA Toolkit:
   - Download from https://developer.nvidia.com/cuda-downloads
   - Install CUDA 11.8 or 12.x
   - Restart your computer

3. Verify CUDA installation:
```bash
nvidia-smi
```

## Quick Start

### 1. Start the Application

```bash
cd E:\coding\video
.\.venv\Scripts\activate
python run.py
```

Navigate to http://localhost:5700/transcription/

### 2. Scan a Directory

1. Enter the full path to your video directory (e.g., `E:\videos`)
2. Select model size:
   - **tiny**: Fastest, lowest quality (~1GB RAM)
   - **base**: Fast, decent quality (~1GB RAM)
   - **small**: Balanced (~2GB RAM)
   - **medium**: Recommended - best balance (~5GB RAM/VRAM)
   - **large-v2**: High quality (~10GB RAM/VRAM)
   - **large-v3**: Best quality, slowest (~10GB RAM/VRAM)
3. Optionally specify language (e.g., `en` for English)
4. Check "Scan subdirectories recursively" if needed
5. Click "Scan Directory"

### 3. Start Batch Transcription

1. Review the scanned files list
2. Select files to transcribe (already-transcribed files are marked)
3. Check "Force reprocess" only if you want to re-transcribe existing files
4. Click "Start Batch Transcription"
5. Monitor progress in real-time

### 4. View and Download Transcripts

Once completed, transcripts appear in the list at the bottom:
- Click "View" to see the full transcript
- Use "Download" to export in various formats:
  - **TXT**: Plain text transcript
  - **JSON**: Full data with timestamps and metadata
  - **SRT**: SubRip subtitle format (for video players)
  - **VTT**: WebVTT subtitle format (for web players)

## Model Selection Guide

| Model | Size | Speed | Quality | RAM/VRAM | Use Case |
|-------|------|-------|---------|----------|----------|
| tiny | 39M | Very Fast | Low | ~1GB | Quick drafts, testing |
| base | 74M | Fast | Fair | ~1GB | Fast processing |
| small | 244M | Moderate | Good | ~2GB | Balanced workflow |
| **medium** | 769M | Moderate | Very Good | ~5GB | **Recommended** |
| large-v2 | 1550M | Slow | Excellent | ~10GB | High accuracy needs |
| large-v3 | 1550M | Slow | Best | ~10GB | Maximum quality |

## Performance Expectations

### GPU (CUDA) Processing:
- **1 hour video**: 6-12 minutes (5-10x realtime)
- **10 videos (10 hours total)**: 1-2 hours
- **100 videos (100 hours total)**: 10-20 hours

### CPU Processing:
- **1 hour video**: 30-60 minutes (1-2x realtime)
- **10 videos (10 hours total)**: 5-10 hours
- **100 videos (100 hours total)**: 50-100 hours

**Note**: Times are approximate and depend on:
- Audio complexity (music, background noise, multiple speakers)
- Video quality and codec
- System specifications

## Smart Deduplication

The system automatically prevents duplicate processing:

1. Each file is hashed (SHA-256) when scanned
2. Database is checked for existing transcripts with same hash
3. Already-transcribed files are marked with a green "Transcribed" badge
4. By default, these files are deselected (won't be processed again)
5. Use "Force reprocess" checkbox to override and re-transcribe

**Why this matters for 10TB libraries**:
- Saves processing time on duplicate files
- Prevents wasted GPU/CPU cycles
- Allows resuming interrupted batch jobs
- Works even if files are moved/renamed (hash-based)

## Supported Video Formats

The system supports all common video formats:
- MP4, MOV, AVI, MKV, WMV, FLV, WebM, M4V, MPG, MPEG

Audio is automatically extracted as 16kHz mono WAV (optimal for Whisper).

## Batch Processing Best Practices

### For Large Libraries (~10TB):

1. **Start Small**: Test with 5-10 videos first to verify setup
2. **Optimal Batch Size**: Process 20-50 videos per batch
3. **Monitor Progress**: Keep browser tab open to track progress
4. **Check Errors**: Review error list for failed files and fix issues
5. **Resume Processing**: Scan directory again - already-processed files are auto-skipped

### Workflow for 10TB Library:

```bash
# Example: Process 1000 videos in 20 batches of 50 each

1. Scan main directory recursively
2. Select first 50 unprocessed videos
3. Start batch → wait for completion (1-2 hours on GPU)
4. Review any errors
5. Repeat for next 50 videos
6. Continue until all videos processed

# Total estimated time (medium model, GPU):
# 1000 videos × 1 hour avg = 1000 hours content
# Processing: ~100-200 hours (4-8 days continuous)
```

## Troubleshooting

### "FFmpeg not found" Error
**Problem**: FFmpeg is not installed or not in PATH

**Solution**:
1. Install FFmpeg (see Prerequisites above)
2. Verify with `ffmpeg -version` in terminal
3. Restart the Flask application

### "CUDA not available" Warning
**Problem**: GPU acceleration not working

**Solution**:
1. Verify GPU: Run `nvidia-smi` in terminal
2. Install CUDA Toolkit if needed
3. The system will fall back to CPU (slower but works)

### Out of Memory Error
**Problem**: Model too large for available RAM/VRAM

**Solution**:
1. Use smaller model (try `small` or `base`)
2. Close other applications
3. For GPU: Reduce batch size or use CPU mode

### Slow Processing Speed
**Problem**: Transcription is very slow

**Check**:
1. Look for "device: cuda" in logs (GPU should be used)
2. If using CPU, expect slower speeds (normal)
3. Try smaller model for faster processing

### Files Being Skipped
**Problem**: Videos not being processed in batch

**Explanation**:
- System prevents duplicate processing by default
- Files with same hash (already transcribed) are skipped
- This is a feature, not a bug!

**Override**: Check "Force reprocess" to re-transcribe

## Database Location

All transcripts are stored in: `E:\coding\video\data\app.db`

To backup your transcripts:
```bash
# Backup database
copy E:\coding\video\data\app.db E:\coding\video\data\app.db.backup

# Restore from backup
copy E:\coding\video\data\app.db.backup E:\coding\video\data\app.db
```

## API Usage (Advanced)

For scripting and automation, use the REST API:

### Scan Directory
```bash
curl -X POST http://localhost:5700/transcription/api/scan \
  -H "Content-Type: application/json" \
  -d '{"directory_path": "E:\\videos", "recursive": true}'
```

### Start Batch Transcription
```bash
curl -X POST http://localhost:5700/transcription/api/start-batch \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": ["E:\\videos\\video1.mp4", "E:\\videos\\video2.mp4"],
    "language": "en",
    "force": false
  }'
```

### Check Batch Status
```bash
curl http://localhost:5700/transcription/api/batch-status/<job_id>
```

### List All Transcripts
```bash
curl http://localhost:5700/transcription/api/transcripts?limit=100
```

### Download Transcript
```bash
curl http://localhost:5700/transcription/api/transcript/1/download?format=srt \
  -o transcript.srt
```

## Tips for Best Results

1. **Use GPU**: Install CUDA for 4-10x speed improvement
2. **Medium Model**: Best balance of speed and quality for most content
3. **Specify Language**: If you know the language, specifying it improves accuracy
4. **Clean Audio**: Videos with clear speech transcribe better
5. **Batch Processing**: Process 20-50 files at a time for manageable progress tracking
6. **Regular Backups**: Backup `data/app.db` periodically to preserve transcripts

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs in the terminal where `python run.py` is running
3. Verify all prerequisites are installed correctly
4. Test with a single small video first before batch processing

## Performance Monitoring

While processing, monitor:
- **CPU/GPU Usage**: Task Manager (Windows) or `nvidia-smi` (GPU)
- **Memory**: Should stay below 80% of available RAM/VRAM
- **Disk I/O**: Temporary audio files created in system temp directory
- **Progress**: Real-time updates in the web interface

Happy transcribing!
