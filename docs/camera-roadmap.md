# Generic Picamera2 camera support

## Status and scope

The camera API is implemented as a pre-release capability-driven adapter. It
owns camera index 0 and supports cameras that Picamera2/libcamera can configure
as a YUV420 video stream and encode as MJPEG. It does not keep a sensor-model
allowlist and does not claim that every Picamera2 device has been physically
validated.

The service always exposes one camera contract. Optional settings are rejected
atomically with `invalid_request` when the active device does not
advertise them. Missing metadata remains present as `null` in camera status.

## Runtime discovery

Immediately after opening the device—and before streaming—the adapter reads:

- `camera_controls` for frame-duration and focus controls;
- `camera_properties["Model"]` for informational device identity.

The public `GET /api/v1/camera/capabilities` response is a normalized snapshot
of service-supported features. It deliberately does not expose the complete raw
Picamera2 control map. Metadata capability flags record fields observed in
completed requests and can change from `false` to `true` after streaming begins.

The adapter deliberately does not read Picamera2's `sensor_modes` property.
That property temporarily configures every raw mode and allocates DMA buffers,
which can exhaust or fragment the Raspberry Pi camera heap before the real
stream starts. Physical capabilities therefore return an empty `sensor_modes`
list. The field is informational, not an allowlist; sensor-size preferences are
passed directly to Picamera2/libcamera.

Camera discovery or startup failure does not prevent GPIO from operating. The
camera status remains `unavailable`, while camera operations and capability
inspection return the shared `hardware_unavailable` error.

## Settings and defaults

The initial settings request only a 1280x720 YUV420 encoded stream:

```json
{
  "fps": null,
  "sensor_resolution": null,
  "output_resolution": {
    "width_px": 1280,
    "height_px": 720
  },
  "rotation_degrees": 0,
  "focus": {
    "mode": "unmanaged"
  }
}
```

`null` FPS and sensor resolution leave selection to Picamera2. A non-null sensor
resolution is a best-match hint: libcamera may select a different raw mode based
on aspect ratio, format, frame rate, crop, and pipeline constraints. Camera
settings retain the requested hint, while `stream.sensor_resolution` reports the
applied size when Picamera2 exposes it. Unmanaged focus means the service sends
no focus control. Output dimensions must be positive and even, and the provider
must preserve the exact requested size.

Settings patches are transactions. Capability and schema checks happen before
provider calls. Sensor/output changes and resets to provider-managed controls
restart the pipeline; other supported controls are applied live. Failure restores
the prior complete configuration. The camera becomes unavailable only when that
rollback also fails.

## Focus and metadata

Every camera supports the `unmanaged` focus policy. Other modes are exposed only
when their controls are advertised:

- `manual` requires manual `AfMode` plus `LensPosition`;
- `auto` requires automatic `AfMode` plus `AfTrigger`;
- `continuous` requires continuous `AfMode`.

Calling autofocus on a fixed-focus camera returns `invalid_request`
without changing settings. Autofocus-capable cameras retain the ten-second
operation deadline and metadata-driven completion.

Sensor temperature, focus state, lens position, and the latest autofocus result
are optional. Their response fields are never removed when metadata is absent.

## Streaming and simulation

The physical adapter uses one continuous Picamera2 recording and one process-wide
latest-frame broker. Clients share complete JPEG frames; slow clients skip old
frames rather than creating queues. Rotation is represented by JPEG EXIF
orientation and does not change encoded pixels.

Simulation uses the packaged 1280x720 MJPEG clip. It reports that fixed applied
sensor/output size, accepts any sensor-size hint, uses provider-managed 30 FPS
when `fps` is null, and provides deterministic focus and temperature metadata.
Unsupported output resolutions remain rejected because the fixture cannot
produce them exactly.

## Validation

Portable unit and API tests cover arbitrary model names, fixed-focus devices,
non-enumerating startup, provider sensor-mode substitution, optional metadata,
atomic rollback, exact output dimensions, and simulation behavior.

Physical validation remains opt-in:

```shell
make hw-test
make hw-test-docker
```

These combined native and container hardware commands also test GPIO. Their
camera cases run on Raspberry Pi 5 Bookworm, open the connected camera, stream
1280x720 MJPEG, exercise only advertised controls, verify broker behavior, and
release the device. They do not start the deployed HTTP API. Documentation must
list actual validated models rather than treating generic discovery as proof of
universal compatibility.
