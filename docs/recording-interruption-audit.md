# Recording interruption audit - 20 November 2026

## Evidence and cause

The reported 19 November `IndexError` occurred in `split_code`, called by
`PersistentCommandSession.query("71023", int)` during a normal projection.
The old parser indexed character 2 without requiring a complete reply. A short
serial read could therefore crash; a partial numeric reply could also be accepted
as a truncated position. The raw serial bytes were not logged, so their exact
contents and the transport-level reason for fragmentation cannot be reconstructed.

The preserved original software used `rec_stack` for normal projections. The
pre-acceleration update redirected `rec_projection` to a new method with repeated
serial Z queries and timestamp-based frame selection. The historical
[31 August report](history/projection_calibration_report_20260831.md) explicitly
documents this automatic redirection. It is already present in imported Mic3
commit `0820440` and Mic2 commit `dd7577f`; repository history does not identify a
separate earlier implementation commit. This added acquisition path exposed the
reply-parsing weakness during ordinary recording. It was not a TIFF writer change.

The two saved restart stderr logs were also inspected:

- `Restart_20261119-165851/stderr.log`: `KeyboardInterrupt` in `np.argmax`.
- `Restart_20261119-170339_SerialFix/stderr.log`: `KeyboardInterrupt` in
  `tifffile`/`numpy.tofile` while saving a TIFF.

These are interrupts from stopping the runs, not spontaneous calculation or disk
exceptions. An interrupt inside a write can leave the current TIFF incomplete.
Existing experimental data were not modified. The two `CalledProcessError`
tracebacks in the original report are parent processes reporting the recording
process's nonzero exit; they are not two additional root failures.

`Microscope.saveImage` and `getMetadata` were compared with the preserved original
installation. Their implementation is unchanged. Optimized mode does have a newer
background writer, but the posted crash used normal projection acquisition and
did not reach a TIFF write. Both writing paths are covered by real file roundtrip
tests, using simulated pixels rather than microscope hardware.

## Corrections and remaining stop conditions

- The serial reader assembles CR-terminated frames, ignores malformed/empty frames,
  and tests every split boundary of a position reply. Duplicate/unrelated replies
  cannot satisfy another command's response.
- Normal projections again use the original continuous-stack path. They no longer
  require a velocity model, acceleration lead-in, or burst-time position telemetry.
  Explicit pre-accelerated and optimized recording remain available.
- Ordinary camera bursts again require only pixels, not timestamps or the added
  post-capture frame-rate query. Buffer release and camera cleanup remain.
- The 19 November framing changes (`5129168` / `5e94e48`) also introduced an abort
  for every missing batch reply. For setters, the original timeout-and-return
  behavior is restored with a warning. State-changing commands are not replayed;
  existing movement/status checks remain. Missing required typed data still fails.
- Existing recovery keeps preview failures, saturation, calibration tolerance,
  coverage/timing warnings and recoverable camera misses from ending the schedule.
  Missing acquisitions are logged rather than represented as valid images.

Invalid settings, persistent missing required controller data, controller/cleanup
failures, disk/write failures and operator interruption still stop the run.
Unexpected software defects remain possible. This audit is not a guarantee of
uninterrupted hardware acquisition; the planned long measurement is still needed.

## Verification scope

Automated tests exercise fragmented replies, missing acknowledgements, controller
errors, normal/explicit projection dispatch, camera cleanup, repeated simulated
acquisitions, duration/position scheduling, and GUI generation. TIFF tests write
and reopen real files and compare uint8/uint16 pixels, min/max index maps, metadata,
and byte accounting. Disk failures must propagate and cannot count as saved files.
No specimen measurement was started for this audit.
