import io
import logging
import uuid
from pathlib import Path

import pdfplumber
from fastapi import HTTPException, UploadFile

from ..core.config import settings

logger = logging.getLogger(__name__)


def validate_and_save(file: UploadFile, temp_dir: Path) -> Path:
    content = file.file.read()
    file.file.seek(0)

    # 1. Not empty
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # 2. Extension check
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are accepted")

    # 3. Size check
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.max_file_size_mb}MB",
        )

    # 4-6. PDF structure validation
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            # 5. Page count
            if len(pdf.pages) == 0:
                raise HTTPException(
                    status_code=422, detail="PDF appears to be empty or corrupt"
                )

            # 6. Extractable text check
            text = ""
            for page in pdf.pages[:3]:
                text += page.extract_text() or ""
            if not text.strip():
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "PDF appears to be a scanned image — text extraction "
                        "not supported in V1. OCR support planned for V2."
                    ),
                )
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg or "incorrect" in msg:
            # 4. Password protected
            raise HTTPException(
                status_code=422,
                detail="PDF is password protected — please provide unlocked file",
            )
        raise HTTPException(status_code=422, detail="PDF appears to be empty or corrupt")

    # Save to temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{Path(filename).name}"
    dest = temp_dir / safe_name
    dest.write_bytes(content)
    return dest


def cleanup(file_path: Path) -> None:
    try:
        file_path.unlink()
    except FileNotFoundError:
        logger.warning("Temp file not found during cleanup: %s", file_path)
