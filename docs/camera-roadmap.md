# Generic Picamera2 camera support

## Status and scope

The camera API is implemented as a pre-release capability-driven adapter. It
owns camera index 0 and supports cameras that Picamera2/libcamera can configure
as a YUV420 video stream and encode as MJPEG. It does not keep a sensor-model
allowlist and does not claim that every Picamera2 device has been physically
validated.

The service always exposes one camera contract. Optional settings are rejected
atomically with `capability_unsupported` when the active device does not
advertise them. Missing metadata remains present as `null` in camera status.

## Runtime discovery

Immediately after opening the device—and before streaming—the adapter reads:

- `sensor_modes` for raw resolution, format, bit depth, and maximum FPS;
- `camera_controls` for frame-duration and focus controls;
- `camera_properties["Model"]` for informational device identity.

The public `GET /api/v1/camera/capabilities` response is a normalized snapshot
of service-supported features. It deliberately does not expose the complete raw
Picamera2 control map. Metadata capability flags record fields observed in
completed requests and can change from `false` to `true` after streaming begins.
If sensor-mode enumeration fails with an operating-system error, the adapter
reopens the camera and continues with provider-managed streaming. Capabilities
then contain an empty mode list plus a `discovery_warnings` explanation, and
explicit sensor selection remains unsupported.

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

`null` FPS and sensor resolution leave selection to Picamera2. Unmanaged focus
means the service sends no focus control. Output dimensions must be positive and
even, and the provider must preserve the exact requested size.

An explicit sensor resolution must match an advertised mode. When several raw
modes share that resolution, the adapter removes modes below the requested FPS,
then prefers highest bit depth, highest maximum FPS, and provider order. Cameras
without raw modes can stream with provider selection but reject explicit sensor
selection.

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

Calling autofocus on a fixed-focus camera returns `capability_unsupported`
without changing settings. Autofocus-capable cameras retain the ten-second
operation deadline and metadata-driven completion.

Sensor temperature, focus state, lens position, and the latest autofocus result
are optional. Their response fields are never removed when metadata is absent.

## Streaming and simulation

The physical adapter uses one continuous Picamera2 recording and one process-wide
latest-frame broker. Clients share complete JPEG frames; slow clients skip old
frames rather than creating queues. Rotation is represented by JPEG EXIF
orientation and does not change encoded pixels.

Simulation uses the packaged 1280x720 MJPEG clip. It advertises that single
sensor/output size, provider-managed 30 FPS when `fps` is null, deterministic
focus operations, and deterministic temperature metadata. Unsupported simulated
resolutions are rejected through the same capability error as physical devices.

## Validation

Portable unit and API tests cover discovery, arbitrary model names, fixed-focus
devices, missing raw modes, optional metadata, duplicate-mode selection, atomic
rollback, exact output dimensions, and simulation behavior.

Physical validation remains opt-in:

```shell
make pi-camera-hardware-test
make pi-container-camera-hardware-test
```

The tests run on Raspberry Pi 5 Bookworm, discover the connected camera, stream
1280x720 MJPEG, exercise only advertised sensor/focus capabilities, verify API
broker behavior, and release the device. Documentation must list actual validated
models rather than treating generic discovery as proof of universal compatibility.
