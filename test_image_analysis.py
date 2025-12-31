"""Test script for Nova image analysis."""
import requests
import json
import time

BASE_URL = 'http://127.0.0.1:5700'

def get_sample_images():
    """Get a list of sample images from the database."""
    response = requests.get(f'{BASE_URL}/api/files', params={'file_type': 'image', 'limit': 10})
    if response.status_code == 200:
        data = response.json()
        return data.get('files', [])
    else:
        print(f"Error getting files: {response.status_code}")
        print(response.text)
        return []

def check_proxy_exists(file_id):
    """Check if an image proxy exists for a file."""
    response = requests.get(f'{BASE_URL}/api/files/{file_id}')
    if response.status_code == 200:
        file_data = response.json()
        metadata = file_data.get('metadata', {})
        return metadata.get('has_proxy', False)
    return False

def analyze_image(file_id, model='lite', analysis_types=None):
    """Analyze an image with Nova."""
    if analysis_types is None:
        analysis_types = ['description', 'elements', 'metadata']

    payload = {
        'file_id': file_id,
        'model': model,
        'analysis_types': analysis_types
    }

    print(f"\n{'='*60}")
    print(f"Testing Nova Image Analysis")
    print(f"{'='*60}")
    print(f"File ID: {file_id}")
    print(f"Model: {model}")
    print(f"Analysis Types: {', '.join(analysis_types)}")
    print(f"{'='*60}\n")

    response = requests.post(f'{BASE_URL}/api/nova/image/analyze', json=payload)

    if response.status_code == 200:
        result = response.json()
        print("✓ Analysis completed successfully!")
        print(f"\nJob ID: {result.get('nova_job_id')}")
        print(f"Status: {result.get('status')}")
        print(f"Estimated Cost: ${result.get('estimated_cost', 0):.6f}")
        if 'actual_cost' in result:
            print(f"Actual Cost: ${result.get('actual_cost'):.6f}")
        if 'processing_time_seconds' in result:
            print(f"Processing Time: {result.get('processing_time_seconds'):.2f}s")

        # Get detailed results
        job_id = result.get('nova_job_id')
        if job_id:
            time.sleep(1)  # Brief wait
            results_response = requests.get(f'{BASE_URL}/api/nova/image/results/{job_id}')
            if results_response.status_code == 200:
                results = results_response.json()
                print(f"\n{'='*60}")
                print("ANALYSIS RESULTS:")
                print(f"{'='*60}\n")

                if 'results' in results:
                    res = results['results']

                    if 'description' in res:
                        desc = res['description']
                        print("Description:")
                        print(f"  Scene Type: {desc.get('scene_type', 'N/A')}")
                        print(f"  Primary Subject: {desc.get('primary_subject', 'N/A')}")
                        print(f"  Overview: {desc.get('description', {}).get('overview', 'N/A')[:200]}...")
                        print()

                    if 'elements' in res:
                        elem = res['elements']
                        print("Visual Elements:")
                        if elem.get('equipment'):
                            print(f"  Equipment: {len(elem['equipment'])} items")
                            for item in elem['equipment'][:3]:
                                print(f"    - {item.get('name')} ({item.get('category')})")
                        if elem.get('objects'):
                            print(f"  Objects: {len(elem['objects'])} items")
                        if elem.get('text_visible'):
                            print(f"  Visible Text: {len(elem['text_visible'])} items")
                            for text in elem['text_visible'][:3]:
                                print(f"    - \"{text.get('text')}\" ({text.get('type')})")
                        print()

                    if 'metadata' in res:
                        meta = res['metadata']
                        print("Metadata:")
                        if meta.get('recording_date', {}).get('date'):
                            rd = meta['recording_date']
                            print(f"  Date: {rd.get('date')} (source: {rd.get('date_source')})")
                        if meta.get('location', {}).get('city'):
                            loc = meta['location']
                            print(f"  Location: {loc.get('city')}, {loc.get('state_region')} (source: {loc.get('location_source')})")
                        if meta.get('keywords'):
                            print(f"  Keywords: {', '.join(meta['keywords'][:10])}")
                        print()

                print(f"{'='*60}\n")
        return result
    else:
        print(f"✗ Analysis failed with status {response.status_code}")
        print(response.text)
        return None

def main():
    """Main test function."""
    print("Nova Image Analysis Test Script")
    print("="*60 + "\n")

    # Get sample images
    print("Fetching sample images...")
    images = get_sample_images()

    if not images:
        print("No images found in database. Please upload some images first.")
        return

    print(f"Found {len(images)} images.\n")

    # Find first image with a proxy
    test_image = None
    for img in images:
        if check_proxy_exists(img['id']):
            test_image = img
            break

    if not test_image:
        print("No images with proxies found.")
        print("Please create image proxies first using the create_image_proxies script.")
        return

    print(f"Selected image: {test_image['filename']}")
    print(f"File ID: {test_image['id']}\n")

    # Test 1: Basic analysis
    print("\nTest 1: Basic analysis (description, elements, metadata)")
    analyze_image(test_image['id'], model='lite')

    # Test 2: Waterfall classification (if waterfall image)
    if 'waterfall' in test_image['filename'].lower() or 'pool' in test_image['filename'].lower():
        print("\n\nTest 2: Waterfall classification")
        analyze_image(test_image['id'], model='lite', analysis_types=['waterfall'])

    print("\n" + "="*60)
    print("Testing Complete!")
    print("="*60)

if __name__ == '__main__':
    main()
