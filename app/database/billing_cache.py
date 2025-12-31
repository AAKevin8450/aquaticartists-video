"""Billing cache operations mixin for database."""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class BillingCacheMixin:
    """Mixin providing billing cache CRUD operations."""

    def cache_billing_data(self, service_code: str, service_name: str,
                          usage_date: str, cost_usd: float):
        """
        Cache billing data for a service and date.
        Uses INSERT OR REPLACE for upserts based on unique index.

        Args:
            service_code: AWS service code (e.g., "AmazonS3")
            service_name: Human-readable service name
            usage_date: Date in YYYY-MM-DD format
            cost_usd: Cost in USD
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO billing_cache
                (service_code, service_name, usage_date, cost_usd, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (service_code, service_name, usage_date, cost_usd))

    def get_cached_billing_data(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Get cached billing data for date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of billing cache records
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM billing_cache
                WHERE usage_date >= ? AND usage_date <= ?
                ORDER BY usage_date, service_code
            ''', (start_date, end_date))
            return [dict(row) for row in cursor.fetchall()]

    def clear_billing_cache(self, start_date: Optional[str] = None,
                           end_date: Optional[str] = None):
        """
        Clear billing cache entries.

        Args:
            start_date: Optional start date to clear from
            end_date: Optional end date to clear until
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if start_date and end_date:
                cursor.execute('''
                    DELETE FROM billing_cache
                    WHERE usage_date >= ? AND usage_date <= ?
                ''', (start_date, end_date))
            elif start_date:
                cursor.execute('''
                    DELETE FROM billing_cache WHERE usage_date >= ?
                ''', (start_date,))
            elif end_date:
                cursor.execute('''
                    DELETE FROM billing_cache WHERE usage_date <= ?
                ''', (end_date,))
            else:
                # Clear all
                cursor.execute('DELETE FROM billing_cache')

    def cache_billing_detail(self, service_code: str, operation: str,
                            usage_type: str, usage_date: str,
                            usage_amount: float, cost_usd: float):
        """
        Cache detailed billing data for a service operation.

        Args:
            service_code: AWS service code
            operation: Operation name (e.g., "Bedrock.ModelInvocation.Lite")
            usage_type: Usage type (e.g., "Tokens", "Requests")
            usage_date: Date in YYYY-MM-DD format
            usage_amount: Quantity of usage
            cost_usd: Cost in USD
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO billing_cache_details
                (service_code, operation, usage_type, usage_date,
                 usage_amount, cost_usd, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (service_code, operation, usage_type, usage_date,
                  usage_amount, cost_usd))

    def get_cached_billing_details(self, start_date: str, end_date: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get cached detailed billing data grouped by service.

        AWS CUR data is cumulative - each day contains month-to-date totals.
        We use the LATEST date's values to avoid triple-counting.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict mapping service_code -> list of operation details
        """
        from collections import defaultdict

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Use subquery to get only the latest date's data for each service/operation/usage_type
            # This avoids summing cumulative CUR data across multiple dates
            cursor.execute('''
                SELECT
                    service_code,
                    operation,
                    usage_type,
                    usage_amount,
                    cost
                FROM (
                    SELECT
                        service_code,
                        operation,
                        usage_type,
                        usage_amount,
                        cost_usd as cost,
                        usage_date,
                        ROW_NUMBER() OVER (
                            PARTITION BY service_code, operation, usage_type
                            ORDER BY usage_date DESC
                        ) as rn
                    FROM billing_cache_details
                    WHERE usage_date >= ? AND usage_date <= ?
                ) ranked
                WHERE rn = 1
                ORDER BY service_code, cost DESC
            ''', (start_date, end_date))

            # Group by service
            result = defaultdict(list)
            for row in cursor.fetchall():
                row_dict = dict(row)
                service_code = row_dict.pop('service_code')
                result[service_code].append(row_dict)

            return dict(result)

    def clear_billing_details(self, start_date: Optional[str] = None,
                             end_date: Optional[str] = None):
        """
        Clear detailed billing cache entries.

        Args:
            start_date: Optional start date
            end_date: Optional end date
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if start_date and end_date:
                cursor.execute('''
                    DELETE FROM billing_cache_details
                    WHERE usage_date >= ? AND usage_date <= ?
                ''', (start_date, end_date))
            elif start_date:
                cursor.execute('''
                    DELETE FROM billing_cache_details WHERE usage_date >= ?
                ''', (start_date,))
            elif end_date:
                cursor.execute('''
                    DELETE FROM billing_cache_details WHERE usage_date <= ?
                ''', (end_date,))
            else:
                cursor.execute('DELETE FROM billing_cache_details')

    def create_billing_sync_log(self, start_date: str, end_date: str) -> int:
        """
        Create a new billing sync log entry.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Sync log ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO billing_sync_log
                (sync_started_at, date_range_start, date_range_end, status)
                VALUES (CURRENT_TIMESTAMP, ?, ?, 'IN_PROGRESS')
            ''', (start_date, end_date))
            return cursor.lastrowid

    def update_billing_sync_log(self, log_id: int, status: str,
                                records_processed: int,
                                error_message: Optional[str] = None):
        """
        Update billing sync log entry.

        Args:
            log_id: Sync log ID
            status: Status (IN_PROGRESS, COMPLETED, FAILED)
            records_processed: Number of records processed
            error_message: Optional error message
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status in ('COMPLETED', 'FAILED'):
                cursor.execute('''
                    UPDATE billing_sync_log
                    SET status = ?,
                        records_processed = ?,
                        error_message = ?,
                        sync_completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, records_processed, error_message, log_id))
            else:
                cursor.execute('''
                    UPDATE billing_sync_log
                    SET status = ?, records_processed = ?, error_message = ?
                    WHERE id = ?
                ''', (status, records_processed, error_message, log_id))

    def get_latest_billing_sync(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recent billing sync log entry.

        Returns:
            Sync log record or None
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM billing_sync_log
                ORDER BY sync_started_at DESC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            return dict(row) if row else None
