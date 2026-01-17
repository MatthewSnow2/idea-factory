"""S3 storage integration for build delivery.

Uploads completed builds to S3 and generates presigned download URLs.
"""

import io
import logging
import os
import zipfile
from datetime import timedelta
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Default presigned URL expiration (7 days)
DEFAULT_URL_EXPIRATION = timedelta(days=7)


class S3StorageService:
    """Service for uploading builds to S3."""

    def __init__(self):
        """Initialize S3 service."""
        self._client = None
        self._bucket_name = os.environ.get("S3_BUCKET_NAME")
        self._region = os.environ.get("AWS_REGION", "us-east-1")
        self._url_expiration = int(
            os.environ.get("S3_URL_EXPIRATION_DAYS", "7")
        )

    @property
    def client(self):
        """Get S3 client (lazy initialization)."""
        if self._client is None:
            self._authenticate()
        return self._client

    @property
    def bucket_name(self) -> str:
        """Get the configured bucket name."""
        if not self._bucket_name:
            raise RuntimeError(
                "S3_BUCKET_NAME environment variable not set. "
                "Configure it in your .env file."
            )
        return self._bucket_name

    def _authenticate(self):
        """Initialize S3 client with credentials."""
        # boto3 automatically uses:
        # 1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        # 2. ~/.aws/credentials file
        # 3. IAM role (if running on EC2)
        config = Config(
            region_name=self._region,
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self._client = boto3.client("s3", config=config)
        logger.info(f"S3 client initialized for region: {self._region}")

    def upload_file(
        self,
        file_path: str | Path,
        key: str | None = None,
        content_type: str | None = None,
    ) -> dict:
        """Upload a single file to S3.

        Args:
            file_path: Path to the file to upload
            key: S3 object key (defaults to filename)
            content_type: MIME type of the file

        Returns:
            Dict with key, bucket, and download_url
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        object_key = key or file_path.name

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self.client.upload_file(
            str(file_path),
            self.bucket_name,
            object_key,
            ExtraArgs=extra_args if extra_args else None,
        )

        download_url = self.get_download_url(object_key)
        logger.info(f"Uploaded file: {file_path.name} -> s3://{self.bucket_name}/{object_key}")

        return {
            "key": object_key,
            "bucket": self.bucket_name,
            "download_url": download_url,
        }

    def upload_directory_as_zip(
        self,
        directory_path: str | Path,
        zip_name: str,
        prefix: str = "builds",
    ) -> dict:
        """Zip a directory and upload to S3.

        Args:
            directory_path: Path to directory to zip
            zip_name: Name for the zip file (without .zip extension)
            prefix: S3 key prefix (folder)

        Returns:
            Dict with key, bucket, and download_url
        """
        directory_path = Path(directory_path)
        if not directory_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory_path}")

        # Create zip in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in directory_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(directory_path)
                    zf.write(file_path, arcname)

        zip_buffer.seek(0)
        zip_size = zip_buffer.getbuffer().nbytes
        logger.info(f"Created zip archive: {zip_name}.zip ({zip_size / 1024:.1f} KB)")

        # Upload zip
        object_key = f"{prefix}/{zip_name}.zip"

        self.client.upload_fileobj(
            zip_buffer,
            self.bucket_name,
            object_key,
            ExtraArgs={"ContentType": "application/zip"},
        )

        download_url = self.get_download_url(object_key)
        logger.info(f"Uploaded zip: {zip_name}.zip -> s3://{self.bucket_name}/{object_key}")

        return {
            "key": object_key,
            "bucket": self.bucket_name,
            "download_url": download_url,
        }

    def get_download_url(self, key: str, expiration_days: int | None = None) -> str:
        """Generate a presigned download URL for an object.

        Args:
            key: S3 object key
            expiration_days: URL expiration in days (default from config)

        Returns:
            Presigned download URL
        """
        days = expiration_days or self._url_expiration
        expiration_seconds = days * 24 * 60 * 60

        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expiration_seconds,
        )

        return url

    def delete_file(self, key: str) -> bool:
        """Delete a file from S3.

        Args:
            key: S3 object key

        Returns:
            True if deleted successfully
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info(f"Deleted file: s3://{self.bucket_name}/{key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete {key}: {e}")
            return False

    def file_exists(self, key: str) -> bool:
        """Check if a file exists in S3.

        Args:
            key: S3 object key

        Returns:
            True if file exists
        """
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False


# Singleton instance
_s3_service: S3StorageService | None = None


def get_s3_service() -> S3StorageService:
    """Get singleton S3 service instance."""
    global _s3_service
    if _s3_service is None:
        _s3_service = S3StorageService()
    return _s3_service
