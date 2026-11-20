"""product_name: the recording device named in a FIT file."""

from app.providers.fit.decode import decode_fit
from app.providers.fit.device import product_name
from tests.providers.fit.fit_builder import build_fit


def test_the_file_ids_product_name_names_the_device():
    messages = decode_fit(build_fit(file_id={"product_name": "Forerunner 965"}))

    assert product_name(messages) == "Forerunner 965"


def test_the_recording_devices_info_names_it_without_a_file_id_name():
    fit = build_fit(
        devices=(
            {"device_index": 1, "manufacturer": "garmin", "product_name": "HRM-Pro"},
            {"device_index": "creator", "manufacturer": "garmin", "product_name": "fenix 8"},
        )
    )

    assert product_name(decode_fit(fit)) == "fenix 8"


def test_a_sensors_name_is_never_the_device():
    fit = build_fit(devices=({"device_index": 1, "product_name": "HRM-Pro"},))

    assert product_name(decode_fit(fit)) is None


def test_a_file_naming_no_product_has_no_device():
    assert product_name(decode_fit(build_fit())) is None
