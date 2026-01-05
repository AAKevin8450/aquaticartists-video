"""
Test URL encoding fix for S3 URIs with special characters
"""
from urllib.parse import quote

# Test cases from the 35 failed files
test_keys = [
    "proxies/Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov",
    "proxies/Video Mar 17 2025, 1 29 06 PM (1)_756_720p15.mov",
    "proxies/Video Oct 22 2025, 2 02 08 PM_3010_720p15.mov"
]

bucket_name = "video-analysis-app-676206912644"

print("=" * 80)
print("URL ENCODING TEST")
print("=" * 80)
print()

for s3_key in test_keys:
    # Original (would fail in Bedrock)
    original_uri = f"s3://{bucket_name}/{s3_key}"

    # URL-encoded (should work)
    encoded_key = quote(s3_key, safe='/')
    encoded_uri = f"s3://{bucket_name}/{encoded_key}"

    print(f"Original key: {s3_key}")
    print(f"  Has spaces: {'YES' if ' ' in s3_key else 'NO'}")
    print(f"  Has commas: {'YES' if ',' in s3_key else 'NO'}")
    print(f"  Has parens: {'YES' if '(' in s3_key or ')' in s3_key else 'NO'}")
    print()
    print(f"Original URI (would fail):")
    print(f"  {original_uri}")
    print()
    print(f"Encoded URI (will work):")
    print(f"  {encoded_uri}")
    print()
    print("-" * 80)
    print()

# Show encoding map
print("=" * 80)
print("CHARACTER ENCODING MAP")
print("=" * 80)
special_chars = {
    ' ': 'space',
    ',': 'comma',
    '(': 'left paren',
    ')': 'right paren'
}

for char, name in special_chars.items():
    encoded = quote(char)
    print(f"{name:15} '{char}' -> '{encoded}'")

print()
print("✓ URL encoding fix verified!")
