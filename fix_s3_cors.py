"""
Fix S3 CORS configuration for video upload functionality.
"""
import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

# Get configuration
BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')

print(f"Configuring CORS for bucket: {BUCKET_NAME}")
print(f"Region: {AWS_REGION}\n")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    region_name=AWS_REGION,
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Define CORS configuration
cors_configuration = {
    'CORSRules': [
        {
            'AllowedHeaders': [
                '*'
            ],
            'AllowedMethods': [
                'GET',
                'PUT',
                'POST',
                'DELETE',
                'HEAD'
            ],
            'AllowedOrigins': [
                'http://localhost:5700',
                'http://127.0.0.1:5700'
            ],
            'ExposeHeaders': [
                'ETag',
                'x-amz-request-id',
                'x-amz-id-2'
            ],
            'MaxAgeSeconds': 3600
        }
    ]
}

try:
    # Get current CORS configuration
    print("Current CORS configuration:")
    try:
        current_cors = s3_client.get_bucket_cors(Bucket=BUCKET_NAME)
        print(json.dumps(current_cors['CORSRules'], indent=2))
    except s3_client.exceptions.NoSuchCORSConfiguration:
        print("No CORS configuration found")
    except Exception as e:
        print(f"Error getting CORS: {e}")

    print("\n" + "="*50)
    print("Applying new CORS configuration...")
    print("="*50 + "\n")

    # Apply new CORS configuration
    s3_client.put_bucket_cors(
        Bucket=BUCKET_NAME,
        CORSConfiguration=cors_configuration
    )

    print("[OK] CORS configuration updated successfully!\n")

    # Verify the update
    print("New CORS configuration:")
    new_cors = s3_client.get_bucket_cors(Bucket=BUCKET_NAME)
    print(json.dumps(new_cors['CORSRules'], indent=2))

    print("\n" + "="*50)
    print("CORS Configuration Details:")
    print("="*50)
    print("[OK] Allowed Methods: GET, PUT, POST, DELETE, HEAD")
    print("[OK] Allowed Origins: http://localhost:5700, http://127.0.0.1:5700")
    print("[OK] Allowed Headers: All (*)")
    print("[OK] Exposed Headers: ETag, x-amz-request-id, x-amz-id-2")
    print("[OK] Max Age: 3600 seconds (1 hour)")

    print("\nYou can now upload files from http://localhost:5700")

except Exception as e:
    print(f"[ERROR] Error updating CORS configuration: {e}")
    print("\nPlease ensure:")
    print("1. Your AWS credentials have s3:PutBucketCors permission")
    print("2. The bucket name in .env is correct")
    print("3. You have network connectivity to AWS")
