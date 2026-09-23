"""
Shared utilities for all cron job runners:
  - CloudWatch log streaming (via watchtower)
  - S3 JSON backup after each successful pull
  - SNS email alert on failure
"""

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

import boto3
from sqlalchemy.orm import Session

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# httpx logs full request URLs at INFO — for Graph API calls that includes the
# access_token query param, which would land in /tmp job logs and CloudWatch.
logging.getLogger("httpx").setLevel(logging.WARNING)


def setup_cloudwatch_logging(job_name: str) -> None:
    """Attach a CloudWatch Logs handler to the root logger.

    Logs go to log group '/niltv-dashboard/jobs' with a stream per job name.
    Falls back silently if watchtower isn't installed or AWS creds are missing.
    Skipped outside production unless ALLOW_SIDE_EFFECTS=1 (see Settings).
    """
    if not settings.side_effects_enabled:
        logger.info(f"[{settings.environment}] CloudWatch logging skipped for {job_name}")
        return
    try:
        import watchtower

        cw_handler = watchtower.CloudWatchLogHandler(
            log_group_name="/niltv-dashboard/jobs",
            stream_name=job_name,
            boto3_client=boto3.client("logs", region_name=settings.aws_region),
        )
        cw_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
        )
        logging.getLogger().addHandler(cw_handler)
        logger.info(f"CloudWatch logging enabled for {job_name}")
    except ImportError:
        logger.warning("watchtower not installed — CloudWatch logging disabled")
    except Exception as e:
        logger.warning(f"CloudWatch logging setup failed: {e}")


def upload_to_s3(data: Any, key: str) -> str:
    """Serialize `data` to JSON and upload to S3. Returns the S3 URI.
    Outside production (unless ALLOW_SIDE_EFFECTS=1) nothing is written."""
    if not settings.side_effects_enabled:
        logger.info(f"[{settings.environment}] S3 backup skipped: {key}")
        return f"skipped://{key}"
    s3 = boto3.client("s3", region_name=settings.aws_region)
    body = json.dumps(data, default=str, indent=2).encode("utf-8")
    s3.put_object(
        Bucket=settings.aws_s3_bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    uri = f"s3://{settings.aws_s3_bucket}/{key}"
    logger.info(f"Backed up to {uri}")
    return uri


def send_sns_alert(subject: str, message: str) -> None:
    """Send an email alert via AWS SNS on job failure.
    Outside production (unless ALLOW_SIDE_EFFECTS=1) the alert is only logged."""
    if not settings.side_effects_enabled:
        logger.warning(f"[{settings.environment}] SNS alert suppressed: {subject} | {message}")
        return
    if not settings.aws_sns_topic_arn:
        logger.warning("AWS_SNS_TOPIC_ARN not set — skipping alert.")
        return
    try:
        sns = boto3.client("sns", region_name=settings.aws_region)
        sns.publish(
            TopicArn=settings.aws_sns_topic_arn,
            Subject=subject[:100],
            Message=message,
        )
        logger.info("SNS alert sent.")
    except Exception as e:
        logger.error(f"Failed to send SNS alert: {e}")


def run_job(job_name: str, db: Session, job_fn: Callable, *args, **kwargs) -> int:
    """
    Wrapper that handles logging, success tracking, and failure alerts.

    job_fn(*args, **kwargs) should return the number of records inserted.
    """
    setup_cloudwatch_logging(job_name)

    try:
        records = job_fn(*args, **kwargs)
        logger.info(f"[{job_name}] completed — {records} records inserted")
        return records or 0

    except Exception as e:
        tb = traceback.format_exc()
        finished_at = datetime.now(tz=timezone.utc)
        logger.error(f"[{job_name}] FAILED: {e}\n{tb}")
        send_sns_alert(
            subject=f"[NILTV Dashboard] {job_name} FAILED",
            message=f"Job: {job_name}\nTime: {finished_at}\n\nError:\n{tb}",
        )
        raise
