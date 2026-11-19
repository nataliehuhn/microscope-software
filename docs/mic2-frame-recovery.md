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

This is recovery for transient acquisition and completed-scan quality problems,
not a blanket exception handler: absent usable images, disconnected hardware,
stage errors and failed disk writes still surface as errors. No automatic
restart or moving hardware test is part of deployment.

Validation uses simulated cameras and stages, including real stream-loop tests
with fake Pylon results. Deployment replaces only `microscope.py` and
`camera_basler.py` in the Mic2 installation; its configuration and velocity
model are preserved. Mic3 is not updated.
