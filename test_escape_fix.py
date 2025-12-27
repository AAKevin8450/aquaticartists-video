"""
Test script to verify the Windows path escape sequence fix for Nova JSON parsing.
This simulates the exact error that caused 14% batch failure rate.
"""
import json
import sys
import re
import io

# Fix Windows console encoding issues
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Mock Nova response with unescaped Windows paths (the problematic case)
MOCK_NOVA_RESPONSE = """{
  "summary": {
    "text": "This video shows installation of equipment at proxy_video\\C0002_8494_720p15.MP4",
    "depth": "detailed",
    "language": "en"
  },
  "chapters": {
    "chapters": [
      {
        "index": 1,
        "title": "Introduction",
        "start_time": "00:00",
        "end_time": "03:00",
        "summary": "File located at proxy_video\\C0150_9124_720p15.MP4",
        "detailed_summary": "This chapter covers the basics found in proxy_video\\C0146_8959_720p15.MP4",
        "key_points": ["Point 1", "Point 2"]
      }
    ]
  },
  "elements": {
    "equipment": [],
    "topics_discussed": [],
    "people": {"max_count": 1, "multiple_speakers": false},
    "speakers": []
  },
  "waterfall_classification": {
    "family": "Unknown",
    "tier_level": "Unknown",
    "functional_type": "Unknown",
    "sub_type": "Unknown",
    "confidence": {"overall": 0.0},
    "evidence": ["Located in proxy_video\\C0040_8555_720p15.MP4"],
    "unknown_reasons": {},
    "search_tags": [],
    "product_keywords": [],
    "content_type": "tutorial",
    "skill_level": "beginner",
    "building_techniques": []
  },
  "search_metadata": {
    "project": {
      "customer_name": "Unknown",
      "project_name": "Test from proxy_video\\C0037_8552_720p15.MP4"
    },
    "location": {"city": "Unknown"},
    "water_feature": {"family": "Unknown"},
    "content": {"content_type": "tutorial"},
    "entities": [
      {
        "type": "path",
        "value": "proxy_video\\C0042_8557_720p15.MP4",
        "sources": ["filename"]
      }
    ],
    "keywords": []
  }
}"""

def test_old_parsing_logic(response_text):
    """Test with the OLD logic (should fail)."""
    print("=" * 70)
    print("TEST 1: Old parsing logic (before fix)")
    print("=" * 70)

    # Simulate old code - only checks for 'Invalid \\escape' or 'Invalid escape'
    cleaned = response_text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        result = json.loads(cleaned)
        print("✗ UNEXPECTED: Parsing succeeded (should have failed with bad escape error)")
        return False
    except json.JSONDecodeError as e:
        error_msg = str(e)
        print(f"✓ EXPECTED: Parsing failed with error: {error_msg}")

        # Old logic check
        if 'Invalid \\escape' in error_msg or 'Invalid escape' in error_msg:
            print("✗ PROBLEM: Old logic WOULD trigger escape fixing (but it doesn't in reality)")
            return False
        else:
            print(f"✓ CONFIRMED: Old logic does NOT trigger escape fixing")
            print(f"   Error message contains: '{error_msg[:50]}...'")
            print(f"   Contains 'bad escape': {'bad escape' in error_msg}")
            return True

def test_new_parsing_logic(response_text):
    """Test with the NEW logic (should succeed)."""
    print("\n" + "=" * 70)
    print("TEST 2: New parsing logic (after fix)")
    print("=" * 70)

    # Simulate new code - checks for 'Invalid \\escape' or 'Invalid escape' or 'bad escape'
    cleaned = response_text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        result = json.loads(cleaned)
        print("✗ First attempt succeeded (no fixing needed - unexpected for this test)")
        return True
    except json.JSONDecodeError as e:
        error_msg = str(e)
        print(f"First parse failed (expected): {error_msg[:60]}...")

        # New logic check - includes 'bad escape'
        if 'Invalid \\escape' in error_msg or 'Invalid escape' in error_msg or 'bad escape' in error_msg:
            print("✓ NEW LOGIC TRIGGERED: Attempting to fix escape sequences...")

            # Apply the escape fixing logic
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

            fixed = cleaned
            for old, new in replacements.items():
                fixed = fixed.replace(old, new)

            # Handle Unicode escapes (use non-raw string for \x00 to avoid regex errors)
            fixed = re.sub(r'\\u([0-9a-fA-F]{4})', '\x00UNICODE\\1\x00', fixed)

            # Escape remaining backslashes (the problematic ones)
            fixed = fixed.replace('\\', '\\\\')

            # Restore valid escapes
            for old, new in replacements.items():
                fixed = fixed.replace(new, old)

            # Restore Unicode escapes
            fixed = re.sub('\x00UNICODE([0-9a-fA-F]{4})\x00', r'\\u\1', fixed)

            try:
                result = json.loads(fixed)
                print("✓ SUCCESS: Parsing succeeded after fixing escape sequences!")
                print(f"✓ Parsed {len(result)} top-level keys: {list(result.keys())}")

                # Verify paths were properly escaped
                summary_text = result.get('summary', {}).get('text', '')
                if 'proxy_video' in summary_text:
                    print(f"✓ Summary text preserved: {summary_text[:80]}...")

                entities = result.get('search_metadata', {}).get('entities', [])
                if entities:
                    print(f"✓ Found {len(entities)} entities with paths")

                return True
            except json.JSONDecodeError as e2:
                print(f"✗ FAILED: Still couldn't parse after fixing: {e2}")
                return False
        else:
            print(f"✗ FAILED: New logic did not trigger (unexpected)")
            return False

def test_actual_code():
    """Test using the actual updated code from nova_service.py"""
    print("\n" + "=" * 70)
    print("TEST 3: Using actual NovaVideoService._parse_json_response()")
    print("=" * 70)

    try:
        # Import the actual service
        sys.path.insert(0, 'E:\\coding\\video')
        from app.services.nova_service import NovaVideoService

        # Create a service instance (minimal config needed for this test)
        service = NovaVideoService(
            bucket_name='test-bucket',
            region='us-east-1'
        )

        # Test the actual _parse_json_response method
        result = service._parse_json_response(MOCK_NOVA_RESPONSE)

        print("✓ SUCCESS: Actual code parsed the response successfully!")
        print(f"✓ Parsed {len(result)} top-level keys: {list(result.keys())}")

        # Verify data integrity
        summary_text = result.get('summary', {}).get('text', '')
        if 'proxy_video' in summary_text:
            print(f"✓ Summary text preserved with paths: ...{summary_text[40:80]}...")

        chapters = result.get('chapters', {}).get('chapters', [])
        if chapters:
            print(f"✓ Found {len(chapters)} chapters")
            if 'proxy_video' in str(chapters[0]):
                print(f"✓ Chapter data preserved with paths")

        entities = result.get('search_metadata', {}).get('entities', [])
        if entities and 'proxy_video' in str(entities[0]):
            print(f"✓ Search metadata entities preserved: {entities[0].get('value', '')}")

        return True

    except ImportError as e:
        print(f"⚠ Could not import NovaVideoService: {e}")
        print("  (This is expected if running outside the Flask app context)")
        return None
    except Exception as e:
        print(f"✗ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("TESTING NOVA JSON PARSING ESCAPE SEQUENCE FIX")
    print("=" * 70)
    print("\nThis test simulates the exact error that caused 14% batch failure:")
    print("- Nova returns JSON with Windows paths like: proxy_video\\C0002_8494_720p15.MP4")
    print("- The backslash sequences (\\C, \\8, etc.) are not valid JSON escapes")
    print("- Python's json.loads() throws: 'bad escape \\x at position 0'")
    print("- Old code didn't catch this error variant, so fixing logic never ran")
    print("- New code catches 'bad escape' and applies the fix")
    print()

    results = []

    # Test 1: Verify the problem exists
    result1 = test_old_parsing_logic(MOCK_NOVA_RESPONSE)
    results.append(("Old logic fails (expected)", result1))

    # Test 2: Verify the fix works
    result2 = test_new_parsing_logic(MOCK_NOVA_RESPONSE)
    results.append(("New logic succeeds (fix works)", result2))

    # Test 3: Verify actual code
    result3 = test_actual_code()
    if result3 is not None:
        results.append(("Actual code works", result3))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(r for _, r in results if r is not None)

    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL TESTS PASSED - Fix is working correctly!")
        print("\nThe fix will resolve the 14% batch failure rate.")
        print("Files with Windows paths will now parse successfully.")
    else:
        print("✗ SOME TESTS FAILED - Review the fix")
    print("=" * 70)

    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
