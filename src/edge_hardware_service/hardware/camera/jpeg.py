"""Small JPEG utilities shared by camera adapters and the frame broker."""

from io import BytesIO


def jpeg_dimensions(jpeg: bytes) -> tuple[int, int]:
    """Read JPEG dimensions without an image-processing dependency."""
    if not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("camera frame is not a JPEG image")
    index = 2
    while index + 4 <= len(jpeg):
        if jpeg[index] != 0xFF:
            index += 1
            continue
        marker = jpeg[index + 1]
        index += 2
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(jpeg):
            break
        segment_length = int.from_bytes(jpeg[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(jpeg):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                break
            height = int.from_bytes(jpeg[index + 3 : index + 5], "big")
            width = int.from_bytes(jpeg[index + 5 : index + 7], "big")
            if width and height:
                return width, height
            break
        index += segment_length
    raise ValueError("JPEG frame does not contain image dimensions")


def set_exif_orientation(jpeg: bytes, rotation_degrees: int) -> bytes:
    """Set the EXIF orientation while preserving fixed encoded pixel geometry."""
    import piexif

    orientation_by_rotation = {0: 1, 90: 6, 180: 3, 270: 8}
    try:
        exif = piexif.load(jpeg)
    except (ValueError, piexif.InvalidImageDataError):
        exif = {key: {} for key in piexif.TAGS if key in {"0th", "Exif", "GPS", "1st"}}
    exif["0th"][piexif.ImageIFD.Orientation] = orientation_by_rotation[rotation_degrees]
    exif_bytes = piexif.dump(exif)
    output = BytesIO()
    try:
        piexif.insert(exif_bytes, jpeg, output)
    except piexif.InvalidImageDataError as error:
        raise ValueError("cannot write EXIF orientation to invalid JPEG") from error
    return output.getvalue()
