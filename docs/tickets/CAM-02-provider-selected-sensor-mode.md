# CAM-02: Delegate sensor-mode selection to Picamera2

Status: TODO. Remove the linked temporary code comments when this ticket is
implemented.

## Context

The camera adapter currently enumerates every raw sensor mode during startup
and accepts an explicit `sensor_resolution` only when it exactly matches one of
those modes. This makes the service's discovery snapshot the authority for
selection even though Picamera2 and libcamera already validate configurations
and choose the best available sensor mode.

Eager enumeration is also not a safe universal prerequisite. Picamera2 obtains
the detailed `sensor_modes` list by repeatedly reconfiguring the camera. That
can consume enough memory to fail on constrained Raspberry Pi systems, while
the same camera may still be able to configure and stream normally.

## Intended behavior

- Treat a non-null `sensor_resolution` as a best-match request, not an exact
  hardware-mode requirement.
- Pass the requested size to Picamera2/libcamera and allow the provider to
  select the actual sensor mode using its own scoring and constraints.
- Preserve `null` as fully provider-managed sensor selection.
- Report the requested value in camera settings and the applied value in
  `stream.sensor_resolution`. The applied value must come from the validated or
  active Picamera2 configuration, not from the request.
- Continue requiring `output_resolution` to be applied exactly. Sensor-mode
  substitution must not weaken the encoded-output contract.
- Translate a provider rejection into the existing capability error and retain
  transactional rollback behavior.

Picamera2's closest match is not necessarily the numerically nearest
resolution. Selection may also account for aspect ratio, raw format, bit depth,
frame rate, crop, and pipeline limitations. Consequently, API documentation
must describe the requested sensor size as a hint and avoid promising a
particular sensor mode.

## Why

Delegating selection improves compatibility with cameras whose modes cannot be
enumerated reliably, avoids duplicating libcamera's mode-selection policy, and
allows requests that libcamera can satisfy through a nearby mode. Reporting
both requested and effective resolutions keeps the substitution observable.

## Acceptance criteria

- A well-formed sensor resolution is not rejected merely because it is absent
  from the service's discovered mode list.
- Tests demonstrate that a provider may substitute a different sensor mode and
  that `stream.sensor_resolution` reports the substituted value.
- Exact and substituted sensor requests both preserve the requested
  `output_resolution` exactly.
- Provider rejection leaves the previous running configuration and settings
  intact.
- Operation remains possible when detailed sensor-mode enumeration is empty or
  fails.
- OpenAPI and camera documentation distinguish requested sensor resolution from
  effective stream sensor resolution.
