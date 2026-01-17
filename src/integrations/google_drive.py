"""Google Drive integration for build delivery.

Uses a service account to upload completed builds and share with users.
"""

import io
import logging
import os
import zipfile
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

logger = logging.getLogger(__name__)

# Scopes required for Drive API
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class GoogleDriveService:
    """Service for uploading builds to Google Drive."""

    def __init__(self):
        """Initialize Google Drive service."""
        self._service = None
        self._credentials = None
        self._folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    @property
    def service(self):
        """Get authenticated Drive service (lazy initialization)."""
        if self._service is None:
            self._authenticate()
        return self._service

    def _authenticate(self):
        """Authenticate with Google Drive using service account."""
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if not creds_path:
            # Try default location
            creds_path = str(Path.home() / ".secrets" / "gdrive-service-account.json")

        if not os.path.exists(creds_path):
            raise RuntimeError(
                f"Google Drive credentials not found at {creds_path}. "
                "Set GOOGLE_APPLICATION_CREDENTIALS environment variable."
            )

        self._credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=self._credentials)
        logger.info("Google Drive service authenticated")

    def upload_file(
        self,
        file_path: str | Path,
        name: str | None = None,
        mime_type: str | None = None,
    ) -> dict:
        """Upload a single file to Drive.

        Args:
            file_path: Path to the file to upload
            name: Name for the file in Drive (defaults to original name)
            mime_type: MIME type of the file

        Returns:
            Dict with id, name, and webViewLink
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_name = name or file_path.name

        file_metadata = {"name": file_name}
        if self._folder_id:
            file_metadata["parents"] = [self._folder_id]

        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()

        logger.info(f"Uploaded file: {file_name} -> {file['id']}")
        return file

    def upload_directory_as_zip(
        self,
        directory_path: str | Path,
        zip_name: str,
    ) -> dict:
        """Zip a directory and upload to Drive.

        Args:
            directory_path: Path to directory to zip
            zip_name: Name for the zip file (without .zip extension)

        Returns:
            Dict with id, name, and webViewLink
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
        file_metadata = {"name": f"{zip_name}.zip"}
        if self._folder_id:
            file_metadata["parents"] = [self._folder_id]

        media = MediaIoBaseUpload(
            zip_buffer,
            mimetype="application/zip",
            resumable=True
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()

        logger.info(f"Uploaded zip: {zip_name}.zip -> {file['id']}")
        return file

    def share_with_user(self, file_id: str, email: str, role: str = "reader") -> dict:
        """Share a file with a specific user.

        Args:
            file_id: Drive file ID
            email: User's email address
            role: Permission role (reader, writer, commenter)

        Returns:
            Permission resource
        """
        permission = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }

        result = self.service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=True,
            emailMessage="Your Idea Factory build is ready!",
            supportsAllDrives=True
        ).execute()

        logger.info(f"Shared file {file_id} with {email} as {role}")
        return result

    def get_file_link(self, file_id: str) -> str:
        """Get the web view link for a file.

        Args:
            file_id: Drive file ID

        Returns:
            Web view URL
        """
        file = self.service.files().get(
            fileId=file_id,
            fields="webViewLink",
            supportsAllDrives=True
        ).execute()
        return file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}")

    def delete_file(self, file_id: str) -> bool:
        """Delete a file from Drive.

        Args:
            file_id: Drive file ID

        Returns:
            True if deleted successfully
        """
        try:
            self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            logger.info(f"Deleted file: {file_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_id}: {e}")
            return False


# Singleton instance
_drive_service: GoogleDriveService | None = None


def get_drive_service() -> GoogleDriveService:
    """Get singleton Drive service instance."""
    global _drive_service
    if _drive_service is None:
        _drive_service = GoogleDriveService()
    return _drive_service
