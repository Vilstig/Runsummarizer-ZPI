"""fit_from_zip: the FIT file in a Garmin activity download."""

import pytest

from app.providers.garmin.archive import fit_from_zip
from app.providers.garmin.errors import (
    GarminInvalidResponseError,
    GarminUnsupportedFileError,
)
from tests.providers.fit.fit_builder import build_zip


def test_the_fit_file_is_taken_out():
    assert fit_from_zip(build_zip({"123_ACTIVITY.fit": b"fit", "notes.txt": b"x"})) == b"fit"


def test_the_extension_is_matched_in_any_case():
    assert fit_from_zip(build_zip({"123_ACTIVITY.FIT": b"fit"})) == b"fit"


@pytest.mark.parametrize(
    "files", [{"123.gpx": b"<gpx/>"}, {"123.tcx": b"<tcx/>"}, {}], ids=["gpx", "tcx", "empty"]
)
def test_an_original_file_that_isnt_fit_is_unsupported(files):
    with pytest.raises(GarminUnsupportedFileError) as raised:
        fit_from_zip(build_zip(files))
    assert raised.value.files == list(files)


def test_several_fit_files_are_an_invalid_response():
    with pytest.raises(GarminInvalidResponseError, match="2 FIT files"):
        fit_from_zip(build_zip({"a.fit": b"1", "b.fit": b"2"}))


def test_a_download_that_isnt_a_zip_is_an_invalid_response():
    with pytest.raises(GarminInvalidResponseError, match="isn't a ZIP"):
        fit_from_zip(b"<html>maintenance</html>")


def test_a_fit_file_over_the_cap_once_decompressed_is_refused():
    with pytest.raises(GarminInvalidResponseError, match="over 100 bytes"):
        fit_from_zip(build_zip({"run.fit": bytes(101)}), max_bytes=100)


def test_a_fit_file_at_the_cap_is_kept():
    assert fit_from_zip(build_zip({"run.fit": bytes(100)}), max_bytes=100) == bytes(100)
