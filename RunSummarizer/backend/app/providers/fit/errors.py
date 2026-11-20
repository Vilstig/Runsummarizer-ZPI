class InvalidFitFileError(ValueError):
    """A FIT file the activity can't be built from: not a FIT file, a failed CRC check,
    or a session without a start time.
    """
