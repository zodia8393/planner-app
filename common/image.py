"""Common image validation utilities shared across planner apps."""

__all__ = [
    "MAGIC_BYTES",
    "_check_image_magic",
]

MAGIC_BYTES = {b'\x89PNG': '.png', b'\xff\xd8\xff': '.jpg', b'GIF87a': '.gif', b'GIF89a': '.gif'}


def _check_image_magic(data: bytes, ext: str) -> bool:
    if ext == '.jpeg':
        ext = '.jpg'
    for magic, expected_ext in MAGIC_BYTES.items():
        if data[:len(magic)] == magic:
            return ext == expected_ext
    if ext == '.webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    return False
