import numpy as np
import pytest
from atlas_science.baseline import calibration_radius, regression_metrics
from atlas_science.features import feature_matrix
from atlas_science.importer import normalize_row


def test_features_are_independent_of_observed_yield() -> None:
    row = {
        "plate": "synthetic",
        "row": "1",
        "col": "1",
        "aryl_halide_smiles": "Clc1ccccc1",
        "base_smiles": "N",
        "ligand_smiles": "P",
        "additive_smiles": "",
        "yield": "1",
    }
    first, _ = normalize_row(row, "synthetic")
    second, _ = normalize_row({**row, "yield": "99"}, "synthetic")
    np.testing.assert_array_equal(feature_matrix([first]), feature_matrix([second]))
    assert feature_matrix([first]).shape == (1, 1280)


def test_metrics_use_percentage_points_and_calibration_residuals() -> None:
    actual, predicted = np.array([10.0, 20.0]), np.array([13.0, 16.0])
    metrics = regression_metrics(actual, predicted, 3)
    assert metrics["mae_pct_points"] == 3.5
    assert metrics["rmse_pct_points"] == pytest.approx(np.sqrt(12.5))
    assert metrics["interval_coverage"] == 0.5
    assert calibration_radius(actual, predicted) == 4


def test_nonfinite_metrics_fail_closed() -> None:
    with pytest.raises(ValueError, match="Nonfinite"):
        regression_metrics(np.array([1.0, 2.0]), np.array([1.0, np.nan]), 1)
