"""Recovery boundaries for missing images, not stage or storage failures."""
from datetime import datetime
from functools import wraps
import json
from pathlib import Path
import time
import warnings


class RecoverableAcquisitionError(RuntimeError):
    """This acquisition has no usable result; hardware cleanup must finish."""


def recording_warning(message, category=RuntimeWarning):
    """Always show a warning, even with ignore/error warning filters."""
    try:
        print("WARNING: " + str(message), flush=True)
    except (OSError, ValueError):
        # A detached console must not terminate an unattended measurement.
        pass
    try:
        warnings.warn(str(message), category, stacklevel=2)
    except Warning:
        # PYTHONWARNINGS=error must not turn quality advice into a run failure.
        pass


def log_acquisition_issue(filename, message, skipped=False):
    entry = {
        "time": datetime.now().astimezone().isoformat(),
        "filename": str(filename), "skipped": bool(skipped),
        "message": str(message),
    }
    try:
        folder = Path(filename).parent
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "acquisition_warnings.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry) + "\n")
    except OSError as error:
        recording_warning("Could not write acquisition warning log: {}".format(error))
    return entry


def continue_after_missing_acquisition(method):
    """Skip only explicitly recoverable acquisition errors after cleanup.

    No blanket Exception catch: stage/cleanup errors, write errors, invalid
    settings, programming errors and the operator's interrupt still propagate.
    """
    @wraps(method)
    def record(self, filename, *args, **kwargs):
        try:
            return method(self, filename, *args, **kwargs)
        except RecoverableAcquisitionError as error:
            message = "{}: {}; skipping this acquisition, recording will continue.".format(
                filename, error
            )
            recording_warning(message)
            entry = log_acquisition_issue(filename, message, skipped=True)
            # Bound repeated camera failure attempts when the schedule has no
            # interval, while allowing the next repetition to recover normally.
            time.sleep(1.0)
            return {"skipped": True, "preflight": None, "quality_passed": False,
                    "quality_warnings": [str(error)], "acquisition_issue": entry}
    return record
