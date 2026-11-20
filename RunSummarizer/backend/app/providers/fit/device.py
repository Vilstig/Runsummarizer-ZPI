from app.providers.fit.decode import FitMessages

CREATOR_DEVICE_INDEXES = ("creator", 0)  # device_info.device_index of the recording device


def product_name(messages: FitMessages) -> str | None:
    """The name of the device that recorded the file, e.g. ``'Forerunner 965'``: the
    ``product_name`` of its file_id message, else of the recording device's device_info
    message; None when neither has one.
    """
    candidates = [messages.file_id or {}]
    candidates += [
        device
        for device in messages.devices
        if device.get("device_index") in CREATOR_DEVICE_INDEXES
    ]
    for message in candidates:
        name = message.get("product_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None
