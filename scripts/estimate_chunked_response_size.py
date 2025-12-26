"""
Estimate storage size for raw API responses in chunked Nova analyses

This script calculates:
1. Typical Bedrock API response size
2. Number of chunks for various video durations
3. Total storage needed for chunked analyses

Run: python -m scripts.estimate_chunked_response_size
"""

import json
from typing import Dict, Any


# Chunk configurations from VideoChunker
CHUNK_CONFIGS = {
    'lite': {
        'max_duration': 1800,    # 30 minutes
        'chunk_duration': 1500,  # 25 minutes per chunk
        'overlap_pct': 0.10
    },
    'pro': {
        'max_duration': 1800,    # 30 minutes
        'chunk_duration': 1500,  # 25 minutes per chunk
        'overlap_pct': 0.10
    },
    'premier': {
        'max_duration': 5400,    # 90 minutes
        'chunk_duration': 4800,  # 80 minutes per chunk
        'overlap_pct': 0.10
    }
}


def estimate_response_size() -> Dict[str, int]:
    """
    Estimate typical Bedrock API response size.

    A Bedrock Converse API response contains:
    - Response metadata (200-500 bytes)
    - Usage metrics (100-200 bytes)
    - Model information (100-200 bytes)
    - Stop reason (50-100 bytes)
    - Output message content (variable - main size driver)

    For Nova video analysis, the output is the analysis result (JSON).
    Typical sizes:
    - Summary: 500-2000 chars
    - Chapters: 1000-5000 chars (depends on video length)
    - Elements: 1000-3000 chars
    - Waterfall classification: 500-1000 chars
    - Combined: 3000-10000 chars
    """

    # Estimate response components (in bytes)
    base_overhead = 1000  # Metadata, usage, model info, timestamps, etc.

    # Analysis output sizes (conservative estimates based on typical results)
    output_sizes = {
        'summary': 1500,           # ~1.5 KB for summary text
        'chapters': 3000,          # ~3 KB for chapter list
        'elements': 2000,          # ~2 KB for equipment/topics/people
        'waterfall': 800,          # ~800 bytes for classification
        'combined': 7000,          # ~7 KB for all in one call
        'search_metadata': 1000    # ~1 KB for search metadata
    }

    # Total response size per analysis type
    response_sizes = {}
    for analysis_type, output_size in output_sizes.items():
        # Response = base overhead + output content + JSON formatting overhead
        total_size = base_overhead + output_size + int(output_size * 0.2)  # 20% JSON overhead
        response_sizes[analysis_type] = total_size

    return response_sizes


def calculate_chunk_count(video_duration: int, model: str) -> int:
    """Calculate number of chunks needed for a video."""
    config = CHUNK_CONFIGS.get(model, CHUNK_CONFIGS['lite'])

    if video_duration <= config['max_duration']:
        return 0  # No chunking needed

    chunk_duration = config['chunk_duration']
    overlap_seconds = chunk_duration * config['overlap_pct']
    effective_chunk_duration = chunk_duration - overlap_seconds

    # Calculate chunks needed
    remaining_duration = video_duration - chunk_duration
    additional_chunks = max(0, int(remaining_duration / effective_chunk_duration))

    return 1 + additional_chunks


def format_size(bytes_size: int) -> str:
    """Format bytes to human-readable size."""
    if bytes_size < 1024:
        return f"{bytes_size} bytes"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    else:
        return f"{bytes_size / (1024 * 1024):.1f} MB"


def main():
    print("=" * 80)
    print("CHUNKED NOVA ANALYSIS - RAW RESPONSE SIZE ESTIMATION")
    print("=" * 80)

    # Get response size estimates
    response_sizes = estimate_response_size()

    print("\n1. TYPICAL SINGLE API RESPONSE SIZES")
    print("-" * 80)
    for analysis_type, size in response_sizes.items():
        print(f"  {analysis_type:20s}: {format_size(size)}")

    # For chunked analysis, we typically use "combined" analysis type
    combined_response_size = response_sizes['combined']

    print(f"\n2. CHUNK COUNTS FOR VARIOUS VIDEO DURATIONS")
    print("-" * 80)

    # Test various video durations
    test_durations = [
        (45, "45 min"),
        (60, "1 hour"),
        (90, "1.5 hours"),
        (120, "2 hours"),
        (180, "3 hours"),
        (240, "4 hours"),
        (360, "6 hours"),
        (480, "8 hours"),
    ]

    for duration_minutes, label in test_durations:
        duration_seconds = duration_minutes * 60

        print(f"\n  Video Duration: {label} ({duration_seconds:,} seconds)")
        print(f"  {'Model':<10s} {'Chunks':<8s} {'Total Size (combined analysis)':<30s}")
        print(f"  {'-' * 10} {'-' * 8} {'-' * 30}")

        for model in ['lite', 'pro', 'premier']:
            chunk_count = calculate_chunk_count(duration_seconds, model)

            if chunk_count == 0:
                print(f"  {model:<10s} {'N/A':<8s} No chunking needed")
            else:
                total_size = combined_response_size * chunk_count
                print(f"  {model:<10s} {chunk_count:<8d} {format_size(total_size)}")

    print("\n" + "=" * 80)
    print("3. STORAGE IMPACT ANALYSIS")
    print("=" * 80)

    # Analyze storage for a typical workflow
    print("\nScenario: Processing 100 videos with varied lengths")
    print("-" * 80)

    # Distribution: 70% short (<30 min), 20% medium (30-90 min), 10% long (>90 min)
    distribution = {
        'short': {'count': 70, 'avg_duration': 15 * 60, 'label': '<30 min'},
        'medium': {'count': 20, 'avg_duration': 60 * 60, 'label': '30-90 min'},
        'long': {'count': 10, 'avg_duration': 180 * 60, 'label': '>90 min'}
    }

    total_storage = 0
    model = 'lite'  # Most common

    print(f"\nUsing model: {model}")
    print(f"{'Category':<12s} {'Count':<8s} {'Avg Length':<12s} {'Chunks/Video':<15s} {'Total Storage':<15s}")
    print("-" * 80)

    for category, data in distribution.items():
        count = data['count']
        avg_duration = data['avg_duration']

        chunk_count = calculate_chunk_count(avg_duration, model)

        if chunk_count == 0:
            # No chunking - single response
            storage_per_video = combined_response_size
        else:
            storage_per_video = combined_response_size * chunk_count

        category_total = storage_per_video * count
        total_storage += category_total

        chunks_label = "1 (no chunk)" if chunk_count == 0 else str(chunk_count)

        print(f"{data['label']:<12s} {count:<8d} {data['avg_duration']//60:3d} min      "
              f"{chunks_label:<15s} {format_size(category_total)}")

    print("-" * 80)
    print(f"{'TOTAL':<12s} {sum(d['count'] for d in distribution.values()):<8d} "
          f"{'':15s} {'':15s} {format_size(total_storage)}")

    print("\n" + "=" * 80)
    print("4. KEY FINDINGS")
    print("=" * 80)
    print(f"""
1. Single Response Size: ~{format_size(combined_response_size)} per chunk (combined analysis)

2. Chunking Triggers:
   - Lite/Pro: Videos > 30 minutes -> 25-min chunks
   - Premier: Videos > 90 minutes -> 80-min chunks

3. Storage Examples:
   - 45-min video (Lite): {calculate_chunk_count(45*60, 'lite')} chunks = {format_size(combined_response_size * max(1, calculate_chunk_count(45*60, 'lite')))}
   - 2-hour video (Lite): {calculate_chunk_count(120*60, 'lite')} chunks = {format_size(combined_response_size * calculate_chunk_count(120*60, 'lite'))}
   - 6-hour video (Lite): {calculate_chunk_count(360*60, 'lite')} chunks = {format_size(combined_response_size * calculate_chunk_count(360*60, 'lite'))}

4. Database Impact:
   - SQLite TEXT field: No hard limit, but large values (>1MB) can slow queries
   - Recommended max per field: <1MB for good performance
   - Videos requiring >10 chunks would exceed 100KB

5. Recommendation:
   - Videos < 2 hours: Store raw responses (moderate size)
   - Videos > 2 hours: Consider alternative storage (S3, separate files)
   - Current implementation (no chunked storage) is reasonable for most use cases
""")

    print("=" * 80)


if __name__ == '__main__':
    main()
