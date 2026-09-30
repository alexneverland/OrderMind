"""Bound ZIP-based Office content before XML/DOM/DataFrame parsing."""
from io import BytesIO
import zipfile
import zlib

MAX_OFFICE_EXPANDED_BYTES = 30 * 1024 * 1024
MAX_OFFICE_ARCHIVE_ENTRIES = 1000


class OfficeArchiveError(ValueError):
    pass


def validate_office_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_OFFICE_ARCHIVE_ENTRIES:
                raise OfficeArchiveError("Office file has too many archive entries (maximum 1,000)")
            if sum(entry.file_size for entry in entries) > MAX_OFFICE_EXPANDED_BYTES:
                raise OfficeArchiveError("Office file exceeds the 30 MB expanded-size limit")
            total = 0
            for entry in entries:
                if entry.flag_bits & 1:
                    raise OfficeArchiveError("Encrypted Office archives are not supported")
                # Stream before handing the archive to parsers. This also checks
                # CRC/truncation and bounds actual readable bytes, not only metadata.
                with archive.open(entry) as member:
                    while chunk := member.read(64 * 1024):
                        total += len(chunk)
                        if total > MAX_OFFICE_EXPANDED_BYTES:
                            raise OfficeArchiveError("Office file exceeds the 30 MB expanded-size limit")
    except OfficeArchiveError:
        raise
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error, OSError) as exc:
        raise OfficeArchiveError("Invalid or unsupported Office archive") from exc
