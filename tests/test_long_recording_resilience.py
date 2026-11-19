import json
import warnings
from unittest.mock import Mock, patch

import numpy as np
import pytest

from leica_microscope.microscope import Microscope
from leica_microscope.recording_resilience import RecoverableAcquisitionError
from test_timed_projection import (
    SimulatedMicroscope, recording_microscope, recorder_result, microscope_module,
)


def test_missing_scan_between_good_scans_keeps_series_and_origin(tmp_path):
    mic = recording_microscope()
    mic.recordTimedContinuousProjection.side_effect = [
        recorder_result(), RecoverableAcquisitionError("temporary camera timeout"),
        recorder_result(),
    ]
    mic.waitSinceLast = Mock()
    mic.cam.getImage = Mock(return_value=np.ones((3, 4), np.uint8) * 100)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        results = mic.rec_timed_continuous_projection_series(
            str(tmp_path / "rep{repetition}_{z}.tif"), -10, 10, 1.0, 3,
        )
    assert len(results) == 3 and results[1]["skipped"]
    assert results[0]["quality_passed"] and results[2]["quality_passed"]
    assert len(list(tmp_path.glob("rep0_*.tif"))) == 4
    assert not list(tmp_path.glob("rep1_*.tif"))
    assert len(list(tmp_path.glob("rep2_*.tif"))) == 4
    issues = [json.loads(line) for line in (tmp_path / "acquisition_warnings.jsonl").read_text().splitlines()]
    assert len(issues) == 1 and issues[0]["skipped"]
    assert "rep1_" in issues[0]["filename"]
    assert mic.waitSinceLast.call_count == 3
    calls = mic.recordTimedContinuousProjection.call_args_list
    assert [c.kwargs["center_z_steps"] for c in calls] == [500, 500, 500]
    assert [c.args[:2] for c in calls] == [(-10, 10), (10, -10), (-10, 10)]
    assert (mic.position, mic.speed) == (500, 123)


def test_all_frames_outside_span_skip_and_next_real_scan_succeeds(tmp_path):
    mic = recording_microscope()
    mic.recordTimedContinuousProjection = Microscope.recordTimedContinuousProjection.__get__(mic)
    mic.cam.drop_frames = set(range(1, 500))  # Keep startup/preroll only.
    with patch.object(microscope_module, "PersistentCommandSession", mic.command_session):
        first = mic.rec_timed_continuous_projection(
            str(tmp_path / "missing_{z}.tif"), -10, 10, 0.5,
            cached_preflight={"p99": 100, "saturated_fraction": 0},
        )
        assert first["skipped"] and not list(tmp_path.glob("missing_*.tif"))
        assert (mic.position, mic.speed, mic.cam.exposure()) == (500, 123, 3.0)
        mic.cam.drop_frames = set()
        second = mic.rec_timed_continuous_projection(
            str(tmp_path / "next_{z}.tif"), -10, 10, 0.5,
            cached_preflight={"p99": 100, "saturated_fraction": 0},
        )
    assert second["selected_frame_count"] > 0
    assert len(list(tmp_path.glob("next_*.tif"))) == 4


def test_dark_saturated_and_preview_failure_are_nonfatal_with_warning_errors(tmp_path):
    mic = recording_microscope()
    image, _, indices, _, diagnostics = recorder_result()
    mic.recordTimedContinuousProjection.return_value = (
        image, np.full_like(image, 255), indices, indices.copy(), diagnostics,
    )
    mic.send_command_and_wait = Mock(side_effect=[[0, 0], mic.MODE_TL_BF])
    mic.memmap_writer.store_image.side_effect = OSError("preview mapping closed")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = mic.rec_timed_continuous_projection(
            str(tmp_path / "bright_{z}.tif"), -10, 10, 1.0,
            cached_preflight={"p99": 0, "saturated_fraction": 0.5},
        )
    assert not result["quality_passed"]
    assert len(list(tmp_path.glob("*.tif"))) == 4
    assert mic.memmap_writer is None
    assert any("black" in warning for warning in result["quality_warnings"])
    assert any("saturated" in warning for warning in result["quality_warnings"])


def test_low_duty_cycle_and_reduced_rate_warn_and_return_images():
    mic = SimulatedMicroscope()
    mic.cam.getFramerate = lambda: 45.0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with patch.object(microscope_module, "PersistentCommandSession", mic.command_session):
            result = mic.recordTimedContinuousProjection(-10, 10, 0.5)
    assert result[-1]["selected_frame_count"] > 0
    assert len(result[-1]["acquisition_warnings"]) == 2


def test_single_image_failure_closes_shutter_and_next_image_saves(tmp_path):
    mic = recording_microscope()
    mic.isFluo = Mock(return_value=True)
    mic.cam.getImage = Mock(side_effect=[RecoverableAcquisitionError("image timeout"),
                                        np.ones((3, 4), np.uint8)])
    first = mic.rec_image(str(tmp_path / "first.tif"))
    assert first["skipped"]
    assert mic.setShutter.call_args.args == (False,)
    mic.rec_image(str(tmp_path / "second.tif"))
    assert not (tmp_path / "first.tif").exists()
    assert (tmp_path / "second.tif").exists()


def test_precise_stack_restores_z_when_image_is_missing(tmp_path):
    from contextlib import nullcontext
    mic = recording_microscope()
    mic.isFluo = Mock(return_value=True)
    mic.cam.fast_recording = nullcontext()
    mic.cam.getVideoBuffer = Mock(return_value=np.zeros((2, 3, 4), np.uint8))
    mic.cam.getImage = Mock(side_effect=RecoverableAcquisitionError("slice timeout"))
    result = mic.rec_stack(str(tmp_path / "slice_{z}.tif"), -1, 1, 1.0)
    assert result["skipped"] and mic.getZPos() == 500
    assert mic.setShutter.call_args.args == (False,)
    assert not list(tmp_path.glob("*.tif"))


@pytest.mark.parametrize("error", [OSError("disk full"), RuntimeError("stage failure"),
                                      KeyboardInterrupt()])
def test_real_failures_and_operator_stop_are_not_swallowed(tmp_path, error):
    mic = recording_microscope()
    mic.isFluo = Mock(return_value=True)
    mic.cam.getImage = Mock(side_effect=error)
    with pytest.raises(type(error)):
        mic.rec_image(str(tmp_path / "image.tif"))
    assert mic.setShutter.call_args.args == (False,)


def test_series_retains_bounded_summaries_instead_of_frame_history(tmp_path):
    mic = recording_microscope()
    mic.waitSinceLast = Mock()
    mic.rec_timed_continuous_projection = Mock(return_value={
        "preflight": {}, "quality_passed": True, "frames": [{"large": "history"}],
        "stage_samples": [(1, 2)],
    })
    results = mic.rec_timed_continuous_projection_series(
        str(tmp_path / "rep{repetition}_{z}.tif"), -10, 10, 1.0, 1030,
    )
    assert len(results) == 1024
    assert results[0]["repetition"] == 6 and results[-1]["repetition"] == 1029
    assert all("frames" not in result and "stage_samples" not in result for result in results)
