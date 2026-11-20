import io
import zipfile

from app.providers.garmin.constants import MAX_FILE_BYTES
from app.providers.garmin.errors import (
    GarminInvalidResponseError,
    GarminUnsupportedFileError,
)


def fit_from_zip(content: bytes, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
    """The FIT file in a Garmin activity download, a ZIP holding the activity's original file.

    Raises ``GarminInvalidResponseError`` when ``content`` isn't a ZIP, holds several
    ``.fit`` files or a FIT file larger than ``max_bytes`` once decompressed, and
    ``GarminUnsupportedFileError`` when it holds none.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            files = archive.namelist()
            fit_files = [name for name in files if name.lower().endswith(".fit")]
            if not fit_files:
                raise GarminUnsupportedFileError(
                    f"The activity's original file isn't a FIT file: {', '.join(files) or 'none'}",
                    files=files,
                )
            if len(fit_files) > 1:
                raise GarminInvalidResponseError(
                    f"The activity download holds {len(fit_files)} FIT files, not one"
                )
            with archive.open(fit_files[0]) as fit_file:
                fit = fit_file.read(max_bytes + 1)
            if len(fit) > max_bytes:
                raise GarminInvalidResponseError(
                    f"The activity download's FIT file is over {max_bytes} bytes"
                )
            return fit
    except zipfile.BadZipFile as exc:
        raise GarminInvalidResponseError("The activity download isn't a ZIP file") from exc
