# Fix S3 Path for Discounted Batch Processing

## Problem Summary

Bedrock Batch Inference is failing with error:
```
"The S3 resource locations in your prompt do not match the folder prefix specified in
CreateModelInvocationJob InputDataConfig parameter. Batch Inference requires both JSONL
and S3 resources to be in the same S3 bucket and folder (paths are case-sensitive).
If you intend to use S3 URIs in prompts, the InputDataConfig parameter must specify a
folder containing all linked resources, not an individual .jsonl file."
```

### Root Cause

**Current Implementation** (BROKEN):
- JSONL uploaded to: `s3://bucket/nova/batch/input/{job_name}.jsonl`
- InputDataConfig points to: `s3://bucket/nova/batch/input/{job_name}.jsonl` (a FILE)
- Video files at: `s3://bucket/proxies/{video_name}.mp4`

**Problem**:
1. InputDataConfig must point to a **folder**, not a file
2. That folder must contain BOTH the JSONL AND all S3 resources referenced in the prompts
3. `nova/batch/input/` and `proxies/` are sibling folders with no common parent except bucket root

### Evidence

From `debug_batch_record.json`:
```json
{
  "video": {
    "source": {
      "s3Location": {
        "uri": "s3://video-analysis-app-676206912644/proxies/C0126_33938_720p15.MP4"
      }
    }
  },
  "error": {
    "errorCode": 400,
    "errorMessage": "The S3 resource locations in your prompt do not match..."
  }
}
```

---

## Solution

**Upload JSONL to bucket root and set InputDataConfig to bucket root folder.**

Since videos are in `proxies/`, `source_files/`, and potentially other folders, the only common parent is the bucket root. We need to:

1. Upload JSONL files to bucket root (not `nova/batch/input/`)
2. Set InputDataConfig to `s3://bucket/` (trailing slash = folder)
3. Keep OutputDataConfig in a subfolder (this is still valid for output)

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/services/nova_service.py` | Lines 475-501: Fix S3 path construction |
| `app/config.py` | Line 29: Update default NOVA_BATCH_INPUT_PREFIX |
| `app/services/batch_cleanup_service.py` | Lines 86, 94: Fix hardcoded paths for cleanup |

---

## Implementation Steps

### Step 1: Update nova_service.py - Fix S3 Path Construction

**Location**: `app/services/nova_service.py:463-523`

**Current Code** (lines 475-501):
```python
input_prefix = self._normalize_s3_prefix(input_prefix)
output_prefix = self._normalize_s3_prefix(output_prefix)

input_key = f"{input_prefix}/{job_name}.jsonl"
output_prefix_key = f"{output_prefix}/{job_name}/"

# ... upload JSONL ...

job_arn = self._start_batch_job(
    job_name=job_name,
    model_id=runtime_model_id,
    role_arn=role_arn,
    input_s3_uri=self._build_s3_uri(input_key),      # Points to FILE
    output_s3_uri=self._build_s3_uri(output_prefix_key)
)
```

**New Code**:
```python
input_prefix = self._normalize_s3_prefix(input_prefix)
output_prefix = self._normalize_s3_prefix(output_prefix)

# CRITICAL FIX: Upload JSONL to bucket root so InputDataConfig can point to root folder
# Bedrock requires InputDataConfig to be a folder containing BOTH JSONL and all S3 resources
# Since videos are in proxies/, source_files/, etc., the only common parent is bucket root
input_key = f"batch_input_{job_name}.jsonl"  # Bucket root - flat file
output_prefix_key = f"{output_prefix}/{job_name}/"

# ... upload JSONL unchanged ...

job_arn = self._start_batch_job(
    job_name=job_name,
    model_id=runtime_model_id,
    role_arn=role_arn,
    input_s3_uri=f"s3://{self.bucket_name}/",  # FOLDER (bucket root with trailing slash)
    output_s3_uri=self._build_s3_uri(output_prefix_key)
)
```

**Key Changes**:
1. `input_key` changed from `{input_prefix}/{job_name}.jsonl` to `batch_input_{job_name}.jsonl` (bucket root)
2. `input_s3_uri` changed from file path to bucket root folder: `s3://{bucket}/`
3. The trailing `/` is critical - it tells Bedrock this is a folder

### Step 2: Update _start_batch_job method

**Location**: `app/services/nova_service.py:357-392`

The `_start_batch_job` method accepts `input_s3_uri` parameter. No change needed here - it passes the URI directly to Bedrock API. The fix is in the caller.

### Step 3: Update batch_cleanup_service.py - Fix Cleanup Paths

**Location**: `app/services/batch_cleanup_service.py:83-97`

**Current Code** (hardcoded paths):
```python
input_prefix = 'nova/batch/input/'
output_prefix = 'nova/batch/output/'
```

**New Code**:
```python
# Input files are now at bucket root with pattern: batch_input_{job_name}.jsonl
input_pattern = 'batch_input_'
output_prefix = current_app.config.get('NOVA_BATCH_OUTPUT_PREFIX', 'nova/batch/output/')
```

Update the cleanup logic to find files matching the `batch_input_*.jsonl` pattern at bucket root.

### Step 4: Update config.py (Optional)

**Location**: `app/config.py:29`

The `NOVA_BATCH_INPUT_PREFIX` config is no longer used for input since files go to bucket root. Either:
- Remove it
- Or keep it but document it's deprecated

**Recommendation**: Keep for backward compatibility but add comment that it's unused for input.

---

## Return Values Update

The `start_batch_analysis_records` function returns:
```python
return {
    'batch_job_arn': job_arn,
    'batch_input_s3_key': input_key,  # Now: "batch_input_{job_name}.jsonl"
    'batch_output_s3_prefix': output_prefix_key
}
```

The `batch_input_s3_key` will now be just the filename (at bucket root) instead of a nested path.

---

## Verification Steps

1. **Before Fix**: Submit a batch job and observe the 400 error in logs
2. **After Fix**:
   - Submit a batch job
   - Check S3 bucket root for `batch_input_{job_name}.jsonl` file
   - Verify Bedrock job status transitions to IN_PROGRESS (not immediate FAILED)
   - Wait for completion and verify results are fetched correctly

---

## Rollback Plan

If issues arise:
1. Revert `input_key` to `{input_prefix}/{job_name}.jsonl`
2. Revert `input_s3_uri` to `self._build_s3_uri(input_key)`
3. This will return to the current (broken) behavior

---

## Alternative Approaches Considered

### Option A: Copy Videos to Batch Input Folder (Rejected)
- Copy each video to `nova/batch/input/` before submission
- **Rejected**: Doubles storage costs, slow for large videos

### Option B: Create Symbolic Links in S3 (Rejected)
- S3 doesn't support symbolic links
- **Rejected**: Not possible

### Option C: Use Bucket Root (Selected)
- Upload JSONL to bucket root
- Set InputDataConfig to bucket root
- **Selected**: Simplest solution, no data duplication, works with existing video locations

---

## Timeline

| Step | Description | Complexity |
|------|-------------|------------|
| 1 | Update nova_service.py path construction | Low |
| 2 | Update batch_cleanup_service.py cleanup logic | Low |
| 3 | Test with single video batch | Low |
| 4 | Test with multi-video batch | Low |
| 5 | Deploy and monitor | Low |

Total: ~30 minutes implementation, plus testing.
