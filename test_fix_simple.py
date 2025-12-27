"""
Simple test to verify the escape sequence fix works with actual Windows paths.
"""
import json
import re
import sys

# This is what Nova might return - Windows path with single backslash (not properly escaped)
# In the actual JSON string, \C is an invalid escape sequence
MALFORMED_JSON_FROM_NOVA = r'''{
  "summary": {
    "text": "Video from proxy_video\C0002_8494_720p15.MP4"
  },
  "search_metadata": {
    "entities": [
      {"value": "proxy_video\C0146_8959_720p15.MP4"}
    ]
  }
}'''

print("=" * 70)
print("TESTING ESCAPE SEQUENCE FIX WITH ACTUAL WINDOWS PATHS")
print("=" * 70)
print()

print("Test JSON (contains invalid escape sequences like \\C):")
print(MALFORMED_JSON_FROM_NOVA[:150] + "...")
print()

# Test 1: Verify it fails initially
print("TEST 1: Parsing without fix")
print("-" * 70)
try:
    result = json.loads(MALFORMED_JSON_FROM_NOVA)
    print("UNEXPECTED: Parsing succeeded (should have failed)")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"EXPECTED: Parsing failed")
    print(f"Error: {str(e)}")
    print()

# Test 2: Apply the fix
print("TEST 2: Applying escape sequence fix")
print("-" * 70)

try:
    json.loads(MALFORMED_JSON_FROM_NOVA)
except json.JSONDecodeError as e:
    error_str = str(e)

    # Check if our condition would trigger
    old_condition = 'Invalid \\escape' in error_str or 'Invalid escape' in error_str
    new_condition = 'Invalid \\escape' in error_str or 'Invalid escape' in error_str or 'bad escape' in error_str

    print(f"Old condition (before fix) matches: {old_condition}")
    print(f"New condition (after fix) matches: {new_condition}")
    print()

    if new_condition:
        print("Applying escape sequence fixing logic...")

        # This is the exact logic from nova_service.py lines 1062-1089
        replacements = {
            '\\"': '\x00QUOTE\x00',
            '\\\\': '\x00BACKSLASH\x00',
            '\\/': '\x00SLASH\x00',
            '\\b': '\x00BACKSPACE\x00',
            '\\f': '\x00FORMFEED\x00',
            '\\n': '\x00NEWLINE\x00',
            '\\r': '\x00RETURN\x00',
            '\\t': '\x00TAB\x00'
        }

        fixed = MALFORMED_JSON_FROM_NOVA

        # Replace valid escapes with placeholders
        for old, new in replacements.items():
            fixed = fixed.replace(old, new)

        # Handle Unicode escapes (use non-raw string for \x00 to avoid regex errors)
        fixed = re.sub(r'\\u([0-9a-fA-F]{4})', '\x00UNICODE\\1\x00', fixed)

        # Escape any remaining backslashes (these are the invalid ones)
        fixed = fixed.replace('\\', '\\\\')

        # Restore valid escapes
        for old, new in replacements.items():
            fixed = fixed.replace(new, old)

        # Restore Unicode escapes
        fixed = re.sub('\x00UNICODE([0-9a-fA-F]{4})\x00', r'\\u\1', fixed)

        # Try parsing again
        try:
            result = json.loads(fixed)
            print("SUCCESS: Parsing succeeded after applying fix!")
            print()
            print(f"Parsed successfully:")
            print(f"  - Summary text: {result['summary']['text']}")
            print(f"  - Entity value: {result['search_metadata']['entities'][0]['value']}")
            print()
            print("=" * 70)
            print("FIX VERIFICATION: PASS")
            print("The fix correctly handles Windows paths with backslashes")
            print("=" * 70)
            sys.exit(0)

        except json.JSONDecodeError as e2:
            print(f"FAILED: Still couldn't parse after applying fix")
            print(f"Error: {str(e2)}")
            print()
            print("=" * 70)
            print("FIX VERIFICATION: FAIL")
            print("=" * 70)
            sys.exit(1)
    else:
        print("ERROR: Condition did not match")
        sys.exit(1)
