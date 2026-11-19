# Mic2 dropped-frame recovery (2026-11-19)

The reported `Basler frame sequence skipped from 30 to 32` was raised by
the timed-projection callback. Frame 31 was absent from the delivered sequence;
the outer subprocess errors only propagated that exception. No transport
counters were captured in the failure, so the original loss cannot be assigned
conclusively to USB bandwidth, driver buffers, or host processing.

The callback previously retained a Pylon buffer while waiting for a stage
position sample and computing projection extrema. The stream now copies the
image and releases that buffer first. Its temporary buffer pool is enlarged
to at most 64 frames within a 128 MiB payload budget (an already larger pool
is preserved), and the original setting is restored afterward. This absorbs
brief stalls; it does not guarantee that an overloaded host will never drop
another frame.

Missing frame IDs, failed grab results and individual retrieval timeouts print
warnings and continue. Completed scans with insufficient coverage or camera
loss are saved immediately with quality flags, avoiding repeated exposures
just to meet the coverage threshold. Timing-only retries remain bounded; when
exhausted, the last completed scan is saved with a warning instead of aborting
the measurement. Images and extrema index maps contain only received frames;
missing data is never fabricated.

Each TIFF includes `ProjectionQualityPassed`, `ProjectionWarnings`, and
`MissingFrameCount`. `TimedContinuousProjection` contains exact frame gaps,
exposure coverage, stage samples, callback duration, failed-grab descriptions,
and available Pylon transport counters before/after acquisition. Compare
buffer-underrun and missed-frame counts with callback duration and frame
retrieval latency to investigate future loss. Unsupported counters are omitted.

The subsequent long-measurement audit also removes hard quality stops for
dark brightfield previews, exposure duty below 95%, reduced readout rate,
incomplete pre-roll coverage, and a legacy calibration missing its timing
tolerance. These conditions warn and are recorded in image metadata. Quality
warnings remain nonfatal even with `PYTHONWARNINGS=error`.

Single images, precise stacks, and both projection recording paths catch an
explicit `RecoverableAcquisitionError` after hardware cleanup. Basler capture
timeouts/SDK acquisition errors, no usable exposures, or missing crossing-time
samples skip that acquisition, append its filename and reason to
`acquisition_warnings.jsonl` beside the images, wait one second, and allow the
next scheduled repetition. Failed captures never produce placeholder images.
Optimized sessions restore the reference Z and discard cached preflight after
a skipped scan. Camera buffers and precise-stack Z/shutter state are released
or restored on failure; a worker that cannot stop is not treated as recoverable.

Live-preview publishing errors disable that preview and warn without stopping
TIFF writes. Optimized series now return only the latest 1024 compact summaries
(with repetition numbers and filenames), instead of retaining every frame and
stage sample for the entire measurement; full successful-scan diagnostics
remain in the TIFFs.

Stage/control/cleanup errors, invalid geometry or calibration identity, failed
disk writes, unexpected programming errors and operator interruption still
surface as errors. This is not a blanket exception handler or a guarantee of
recovery from a disconnected device. No moving hardware test is part of deployment.

Validation uses simulated cameras and stages, including real stream-loop tests
with fake Pylon results. Deployment replaces `microscope.py`, `camera_basler.py`
and adds `recording_resilience.py` in the Mic2 installation; its configuration
and velocity model are preserved. Mic3 is not updated.
