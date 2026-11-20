"""Real TIFF writes/readback with simulated camera/stage; no hardware access."""
import json
from unittest.mock import Mock, patch

import numpy as np
import pytest
import tifffile

from leica_microscope.microscope import Microscope
from test_timed_projection import recording_microscope, microscope_module


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_normal_projections_write_original_pixels_and_indices_across_repetitions(tmp_path, dtype):
    mic = recording_microscope()
    mic.isFluo = Mock(return_value=False)
    mic.preaccelerated_projection_model = None
    mic.projection_calibration = {"success": False, "status": "max_iterations"}
    frames = np.random.RandomState(3).randint(0, 200, (5, 7, 9)).astype(dtype)
    mic.recordFastStackToBuffer = Mock(return_value=frames)
    for rep in range(3):
        mic.rec_projection(str(tmp_path / ("rep%d_{z}.tif" % rep)), 0, 5, 10.0)
        expected = {
            "MinProj": frames.min(axis=0), "MaxProj": frames.max(axis=0),
            "MinIndices5": frames.argmin(axis=0).astype(np.uint8),
            "MaxIndices5": frames.argmax(axis=0).astype(np.uint8),
        }
        for suffix, pixels in expected.items():
            with tifffile.TiffFile(tmp_path / ("rep%d_%s.tif" % (rep, suffix))) as saved:
                np.testing.assert_array_equal(saved.asarray(), pixels)
                assert saved.asarray().dtype == pixels.dtype
                metadata = json.loads(saved.pages[0].description)
                assert metadata["MicroscopeName"] == "Mic3"
                assert metadata["ProjectionQualityPassed"] is False
    assert len(list(tmp_path.glob("*.tif"))) == 12
    assert mic.used_disk_space == sum(p.stat().st_size for p in tmp_path.glob("*.tif"))


def test_background_tiff_writer_preserves_pixels_and_metadata(tmp_path):
    mic = recording_microscope()
    pixels = np.arange(63, dtype=np.uint16).reshape(7, 9)
    path = tmp_path / "background.tif"
    Microscope._save_timed_projection_files(mic, [(str(path), pixels, {"Exposure": "19.74"})])
    with tifffile.TiffFile(path) as saved:
        np.testing.assert_array_equal(saved.asarray(), pixels)
        assert json.loads(saved.pages[0].description)["Exposure"] == "19.74"


@pytest.mark.parametrize("background", [False, True])
def test_tiff_write_failure_is_reported_not_counted_as_saved(tmp_path, background):
    mic = recording_microscope()
    image = np.zeros((3, 4), np.uint8)
    with patch.object(microscope_module.tifffile, "imsave", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            if background:
                mic._save_timed_projection_files([(str(tmp_path / "image.tif"), image, {})])
            else:
                mic.saveImage(str(tmp_path / "image.tif"), image)
    assert mic.used_disk_space == 0
