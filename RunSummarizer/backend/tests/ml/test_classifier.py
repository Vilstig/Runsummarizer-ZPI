import numpy as np

from app.domain.enums import LapType
from app.ml.classifier import _lap_type_from_prediction


def test_legacy_warm_up_and_cool_down_predictions_map_to_run():
    assert _lap_type_from_prediction(3) == LapType.RUN
    assert _lap_type_from_prediction(4) == LapType.RUN
    assert _lap_type_from_prediction(np.int64(4)) == LapType.RUN


def test_current_predictions_use_lap_type():
    assert _lap_type_from_prediction(np.int64(1)) == LapType.RECOVERY
