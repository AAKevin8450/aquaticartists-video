"""
Service for fetching and processing AWS Cost and Usage Report (CUR) data from S3.

This service retrieves hourly billing data from the S3 bucket containing AWS CUR reports,
parses the Parquet files, and aggregates costs by service and date.
"""

import os
import io
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


class BillingError(Exception):
    """Base exception for billing service errors."""
    pass


# Service code to friendly name mapping
SERVICE_NAME_MAP = {
    'AmazonS3': 'Amazon S3',
    'AmazonRekognition': 'Amazon Rekognition',
    'AmazonBedrock': 'Amazon Bedrock (Nova)',
    'AWSDataTransfer': 'Data Transfer',
    'AmazonCloudFront': 'CloudFront',
    'AmazonEC2': 'Amazon EC2',
    'AmazonCloudWatch': 'CloudWatch',
    'AWSLambda': 'AWS Lambda',
    'AmazonDynamoDB': 'DynamoDB',
    'AmazonSNS': 'Amazon SNS',
    'AmazonSQS': 'Amazon SQS',
}

# Operation-level name mapping for detailed drill-down
OPERATION_NAME_MAP = {
    # Bedrock operations
    'Bedrock.ModelInvocation.Lite': 'Nova Lite Invocation',
    'Bedrock.ModelInvocation.Pro': 'Nova Pro Invocation',
    'Bedrock.ModelInvocation.Premier': 'Nova Premier Invocation',
    'Bedrock.Embeddings': 'Embeddings Generation',

    # Rekognition operations
    'RekognitionVideo.DetectLabels': 'Video Label Detection',
    'RekognitionVideo.DetectText': 'Video Text Detection',
    'RekognitionVideo.DetectFaces': 'Video Face Detection',
    'RekognitionVideo.RecognizeCelebrities': 'Celebrity Recognition',
    'RekognitionImage.DetectLabels': 'Image Label Detection',
    'RekognitionImage.DetectText': 'Image Text Detection',
    'RekognitionImage.DetectFaces': 'Image Face Detection',

    # S3 operations
    'PutObject': 'S3 Upload',
    'GetObject': 'S3 Download',
    'ListBucket': 'S3 List',
    'DeleteObject': 'S3 Delete',
}


def get_operation_display_name(operation: str, service_code: str = None, usage_type: str = None) -> str:
    """
    Get human-readable operation name.

    Args:
        operation: Raw operation string (e.g., "InvokeModelInference")
        service_code: Optional service code for context
        usage_type: Optional usage type (e.g., "USE1-Nova2.0Lite-input-tokens")

    Returns:
        Human-readable operation name
    """
    # For Bedrock, extract model name from usage_type
    if service_code == 'AmazonBedrock' and usage_type:
        # Parse model from usage type
        # Nova 2 Lite: "USE1-Nova2.0Lite-input-tokens" or "USE1-Nova2Lite-input-tokens"
        # Nova Pro: "USE1-NovaPro-input-tokens" (version 1, no "2.0")
        # Nova Premier: "USE1-NovaPremier-input-tokens" (version 1, no "2.0")

        if 'Nova2.0Lite' in usage_type or 'Nova2Lite' in usage_type:
            # Nova 2 Lite (version 2)
            if 'input-tokens' in usage_type:
                return 'Nova 2 Lite (Input Tokens)'
            elif 'output-tokens' in usage_type:
                return 'Nova 2 Lite (Output Tokens)'
            else:
                return 'Nova 2 Lite'
        elif 'NovaPro' in usage_type and 'Nova2' not in usage_type:
            # Nova Pro (version 1)
            if 'input-tokens' in usage_type:
                return 'Nova Pro (Input Tokens)'
            elif 'output-tokens' in usage_type:
                return 'Nova Pro (Output Tokens)'
            else:
                return 'Nova Pro'
        elif 'NovaPremier' in usage_type and 'Nova2' not in usage_type:
            # Nova Premier (version 1)
            if 'input-tokens' in usage_type:
                return 'Nova Premier (Input Tokens)'
            elif 'output-tokens' in usage_type:
                return 'Nova Premier (Output Tokens)'
            else:
                return 'Nova Premier'
        elif 'NovaMultiModalEmbeddings' in usage_type or 'NovaEmbeddings' in usage_type:
            return 'Nova Embeddings'
        elif 'Nova' in usage_type:
            # Generic Nova fallback
            return f'Nova ({operation})'

    # Check exact match first
    if operation in OPERATION_NAME_MAP:
        return OPERATION_NAME_MAP[operation]

    # Fallback: Clean up operation string
    # "Bedrock.ModelInvocation.Lite" → "Model Invocation Lite"
    if '.' in operation:
        parts = operation.split('.')
        return ' '.join(parts[1:]).replace('_', ' ').title()

    return operation.replace('_', ' ').title()


class BillingService:
    """Service for AWS CUR data retrieval and processing."""

    def __init__(
        self,
        billing_bucket_name: str,
        region: str,
        prefix: str = 'hourly_reports/',
        aws_access_key: str = None,
        aws_secret_key: str = None
    ):
        """
        Initialize billing service.

        Args:
            billing_bucket_name: S3 bucket containing CUR data
            region: AWS region
            prefix: S3 prefix where CUR files are stored
            aws_access_key: AWS access key (optional, uses env if not provided)
            aws_secret_key: AWS secret key (optional, uses env if not provided)
        """
        self.billing_bucket_name = billing_bucket_name
        self.region = region
        self.prefix = prefix.rstrip('/') + '/'  # Ensure trailing slash

        # Initialize S3 client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.s3_client = boto3.client('s3', **session_kwargs)
        logger.info(f"Initialized BillingService for bucket: {billing_bucket_name}")

    def list_cur_files(self, start_date: str, end_date: str) -> List[str]:
        """
        List CUR files in S3 bucket for the given date range.

        Note: AWS CUR hourly files contain cumulative data for the entire billing period.
        We only need the LATEST file for each month to avoid counting costs multiple times.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            List of S3 keys for CUR files (latest file per billing period only)

        Raises:
            BillingError: If listing files fails
        """
        try:
            logger.info(f"Listing CUR files from {start_date} to {end_date}")

            # Extract year-month from date range for filtering
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            billing_period = start_dt.strftime('%Y-%m')  # e.g., "2025-12"

            # Use paginator for potentially large result sets
            paginator = self.s3_client.get_paginator('list_objects_v2')
            # Look for files in the data directory for the billing period
            data_prefix = f"{self.prefix}AquaticArtists_Hourly_Costs_Detail/data/BILLING_PERIOD={billing_period}/"

            pages = paginator.paginate(
                Bucket=self.billing_bucket_name,
                Prefix=data_prefix
            )

            all_files = []
            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    key = obj['Key']
                    # Filter for Parquet files only
                    if key.endswith('.parquet'):
                        all_files.append({
                            'key': key,
                            'last_modified': obj['LastModified']
                        })

            # IMPORTANT: Only use the latest file to avoid duplicate counting
            # Each hourly CUR file contains cumulative data for the entire month
            if all_files:
                latest_file = max(all_files, key=lambda x: x['last_modified'])
                cur_files = [latest_file['key']]
                logger.info(f"Using latest CUR file: {latest_file['key']} (modified: {latest_file['last_modified']})")
            else:
                cur_files = []
                logger.info("No CUR Parquet files found")

            return cur_files

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchBucket':
                raise BillingError(f"Billing bucket not found: {self.billing_bucket_name}")
            elif error_code == 'AccessDenied':
                raise BillingError(f"Access denied to billing bucket: {self.billing_bucket_name}")
            else:
                raise BillingError(f"Failed to list CUR files: {e}")

    def parse_cur_parquet(self, s3_key: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Parse CUR Parquet file from S3 and extract usage rows.

        Args:
            s3_key: S3 key of the CUR Parquet file
            start_date: Start date for filtering (YYYY-MM-DD)
            end_date: End date for filtering (YYYY-MM-DD)

        Returns:
            List of dicts containing parsed CUR rows

        Raises:
            BillingError: If parsing fails
        """
        try:
            logger.info(f"Parsing CUR Parquet file: {s3_key}")

            # Get object from S3
            response = self.s3_client.get_object(
                Bucket=self.billing_bucket_name,
                Key=s3_key
            )

            # Read Parquet file from S3 body
            parquet_bytes = response['Body'].read()
            parquet_file = pq.read_table(io.BytesIO(parquet_bytes))

            # Convert to pandas-like dict for easier processing
            df_dict = parquet_file.to_pydict()

            rows = []
            num_rows = len(df_dict.get('line_item_line_item_type', []))

            for i in range(num_rows):
                # Filter for usage rows only (exclude credits, discounts, etc.)
                line_item_type = df_dict.get('line_item_line_item_type', [None] * num_rows)[i]
                if line_item_type != 'Usage':
                    continue

                # Extract relevant fields
                try:
                    service_code = df_dict.get('line_item_product_code', [None] * num_rows)[i] or 'Unknown'
                    cost = float(df_dict.get('line_item_blended_cost', [0] * num_rows)[i] or 0)
                    usage_date_obj = df_dict.get('line_item_usage_start_date', [None] * num_rows)[i]

                    # Extract operation details for granular breakdown
                    operation = df_dict.get('line_item_operation', [None] * num_rows)[i] or ''
                    usage_type = df_dict.get('line_item_usage_type', [None] * num_rows)[i] or ''
                    usage_amount = float(df_dict.get('line_item_usage_amount', [0] * num_rows)[i] or 0)

                    # Parse usage date
                    if usage_date_obj:
                        # Convert to string date
                        if hasattr(usage_date_obj, 'strftime'):
                            usage_date = usage_date_obj.strftime('%Y-%m-%d')
                        else:
                            usage_date = str(usage_date_obj).split('T')[0].split(' ')[0]
                    else:
                        continue

                    # Filter by date range
                    if usage_date < start_date or usage_date > end_date:
                        continue

                    rows.append({
                        'service_code': service_code,
                        'cost': cost,
                        'usage_date': usage_date,
                        'operation': operation,
                        'usage_type': usage_type,
                        'usage_amount': usage_amount,
                    })

                except (ValueError, KeyError, IndexError) as e:
                    # Skip malformed rows
                    logger.warning(f"Skipping malformed row in {s3_key}: {e}")
                    continue

            logger.info(f"Parsed {len(rows)} usage rows from {s3_key}")
            return rows

        except ClientError as e:
            raise BillingError(f"Failed to read CUR file {s3_key}: {e}")
        except Exception as e:
            raise BillingError(f"Failed to parse CUR Parquet file {s3_key}: {e}")

    def aggregate_by_service(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregate cost data by service.

        Args:
            rows: List of parsed CUR rows

        Returns:
            List of dicts with service-level aggregation
        """
        service_costs = defaultdict(float)

        for row in rows:
            service_code = row['service_code']
            cost = row['cost']
            service_costs[service_code] += cost

        # Calculate total cost for percentages
        total_cost = sum(service_costs.values())

        # Build result list
        services = []
        for service_code, cost in service_costs.items():
            service_name = SERVICE_NAME_MAP.get(service_code, service_code)
            percent = (cost / total_cost * 100) if total_cost > 0 else 0

            services.append({
                'service_code': service_code,
                'service_name': service_name,
                'cost': cost,
                'percent': percent
            })

        # Sort by cost descending
        services.sort(key=lambda x: x['cost'], reverse=True)

        logger.info(f"Aggregated {len(services)} services with total cost: ${total_cost:.2f}")
        return services

    def calculate_daily_costs(self, rows: List[Dict[str, Any]], start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Calculate daily cost totals and fill gaps.

        Args:
            rows: List of parsed CUR rows
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of dicts with daily cost data
        """
        daily_costs = defaultdict(float)

        for row in rows:
            usage_date = row['usage_date']
            cost = row['cost']
            daily_costs[usage_date] += cost

        # Fill gaps with zeros for all days in range
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        result = []
        current = start
        while current <= end:
            day_str = current.strftime('%Y-%m-%d')
            result.append({
                'day': day_str,
                'cost': daily_costs.get(day_str, 0.0)
            })
            current += timedelta(days=1)

        logger.info(f"Calculated daily costs for {len(result)} days")
        return result

    def aggregate_by_service_and_date(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """
        Aggregate cost data by both service and date.

        Args:
            rows: List of parsed CUR rows

        Returns:
            Dict mapping service_code -> {date -> cost}
        """
        service_date_costs = defaultdict(lambda: defaultdict(float))

        for row in rows:
            service_code = row['service_code']
            usage_date = row['usage_date']
            cost = row['cost']
            service_date_costs[service_code][usage_date] += cost

        logger.info(f"Aggregated by service and date: {len(service_date_costs)} services")
        return dict(service_date_costs)

    def aggregate_by_operation(self, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Aggregate cost data by service and operation.

        Args:
            rows: List of parsed CUR rows

        Returns:
            Dict mapping service_code -> list of operation dicts
        """
        from collections import defaultdict

        # Group by service → operation → usage_type
        service_operations = defaultdict(lambda: defaultdict(lambda: {
            'cost': 0.0,
            'usage_amount': 0.0,
            'usage_type': '',
            'operation': ''
        }))

        for row in rows:
            service_code = row['service_code']
            operation = row.get('operation', 'Unknown')
            usage_type = row.get('usage_type', 'Unknown')
            cost = row['cost']
            usage_amount = row.get('usage_amount', 0)

            # Create unique key for operation + usage_type combination
            key = f"{operation}|{usage_type}"

            service_operations[service_code][key]['operation'] = operation
            service_operations[service_code][key]['usage_type'] = usage_type
            service_operations[service_code][key]['cost'] += cost
            service_operations[service_code][key]['usage_amount'] += usage_amount

        # Convert to structured format
        result = {}
        for service_code, operations in service_operations.items():
            service_total = sum(op['cost'] for op in operations.values())

            ops_list = []
            for op_data in operations.values():
                operation_name = get_operation_display_name(
                    op_data['operation'],
                    service_code,
                    op_data['usage_type']
                )
                percent = (op_data['cost'] / service_total * 100) if service_total > 0 else 0

                ops_list.append({
                    'operation': op_data['operation'],
                    'operation_name': operation_name,
                    'usage_type': op_data['usage_type'],
                    'usage_amount': op_data['usage_amount'],
                    'cost': op_data['cost'],
                    'percent': percent
                })

            # Sort by cost descending
            ops_list.sort(key=lambda x: x['cost'], reverse=True)
            result[service_code] = ops_list

        logger.info(f"Aggregated operations for {len(result)} services")
        return result

    def fetch_cur_data(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Fetch and aggregate CUR data for date range.

        This is the main entry point for retrieving billing data.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict containing aggregated billing data:
            {
                'services': List of service breakdown dicts,
                'daily': List of daily cost dicts,
                'total_cost': Total cost across all services,
                'rows_processed': Number of raw rows processed
            }

        Raises:
            BillingError: If fetching fails
        """
        logger.info(f"Fetching CUR data from {start_date} to {end_date}")

        # List available CUR files
        cur_files = self.list_cur_files(start_date, end_date)

        if not cur_files:
            logger.warning("No CUR files found")
            return {
                'services': [],
                'daily': self.calculate_daily_costs([], start_date, end_date),
                'total_cost': 0.0,
                'rows_processed': 0
            }

        # Parse all CUR files and collect rows
        all_rows = []
        for s3_key in cur_files:
            try:
                rows = self.parse_cur_parquet(s3_key, start_date, end_date)
                all_rows.extend(rows)
            except BillingError as e:
                # Log error but continue with other files
                logger.error(f"Error parsing {s3_key}: {e}")
                continue

        if not all_rows:
            logger.warning("No billing data rows found in CUR files")
            return {
                'services': [],
                'daily': self.calculate_daily_costs([], start_date, end_date),
                'total_cost': 0.0,
                'rows_processed': 0
            }

        # Aggregate data
        services = self.aggregate_by_service(all_rows)
        daily = self.calculate_daily_costs(all_rows, start_date, end_date)
        service_by_date = self.aggregate_by_service_and_date(all_rows)
        operations_by_service = self.aggregate_by_operation(all_rows)
        total_cost = sum(s['cost'] for s in services)

        return {
            'services': services,
            'daily': daily,
            'service_by_date': service_by_date,  # Add detailed breakdown
            'operations_by_service': operations_by_service,  # Operation-level detail
            'total_cost': total_cost,
            'rows_processed': len(all_rows)
        }


def get_billing_service(app=None) -> Optional[BillingService]:
    """
    Factory function to create BillingService instance.

    Args:
        app: Flask app instance (optional)

    Returns:
        BillingService instance or None if not configured

    Raises:
        BillingError: If service initialization fails
    """
    # Get configuration from app or environment
    if app:
        billing_bucket = app.config.get('BILLING_BUCKET_NAME')
        region = app.config.get('AWS_REGION', 'us-east-1')
        prefix = app.config.get('BILLING_CUR_PREFIX', 'hourly_reports/')
        access_key = app.config.get('AWS_ACCESS_KEY_ID')
        secret_key = app.config.get('AWS_SECRET_ACCESS_KEY')
    else:
        billing_bucket = os.getenv('BILLING_BUCKET_NAME')
        region = os.getenv('AWS_REGION', 'us-east-1')
        prefix = os.getenv('BILLING_CUR_PREFIX', 'hourly_reports/')
        access_key = os.getenv('AWS_ACCESS_KEY_ID')
        secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    # Return None if billing bucket not configured (graceful degradation)
    if not billing_bucket:
        logger.info("Billing bucket not configured, billing features disabled")
        return None

    try:
        return BillingService(
            billing_bucket_name=billing_bucket,
            region=region,
            prefix=prefix,
            aws_access_key=access_key,
            aws_secret_key=secret_key
        )
    except Exception as e:
        logger.warning(f"Failed to initialize billing service: {e}")
        return None
