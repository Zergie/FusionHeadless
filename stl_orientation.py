"""Orient exported STL geometry without importing or modifying Fusion objects.

Coordinates and contact-plane points are in millimeters. Import this module
only in the child or in a standalone environment with the child requirements.
"""

from __future__ import annotations

import io
import math
import struct
from typing import Sequence

import numpy as np
from stl import Mode, mesh


def orient_stl(data: bytes, planes: Sequence[dict]) -> bytes:
    """Return a binary STL centered in XY with marked contact planes on Z=0.

Each plane contains an outward ``normal``, a ``point`` on the plane, and a
human-readable ``label``. All planes must describe the same supporting plane.
The rotation applies X then Y, retaining the legacy printable-body convention.
No scaling, triangle removal, or independent repositioning of bodies occurs.
"""
    if not planes:
        raise ValueError("Oriented STL export requires a marked Build Plate face")
    normals, points = [], []
    for plane in planes:
        label = plane.get("label", "Build Plate face")
        normal = np.asarray(plane["normal"], dtype=np.float64)
        point = np.asarray(plane["point"], dtype=np.float64)
        if (normal.shape != (3,) or point.shape != (3,)
                or not np.isfinite(normal).all() or not np.isfinite(point).all()
                or np.linalg.norm(normal) == 0):
            raise ValueError(f"{label}: invalid contact-plane normal or point")
        normal = normal / np.linalg.norm(normal)
        if normals and not np.allclose(normal, normals[0], atol=1e-6, rtol=0):
            raise ValueError(f"{label}: conflicting Build Plate face directions; export these bodies separately")
        normals.append(normal)
        points.append(point)

    # Fusion is explicitly asked for binary STL. Validate length ourselves:
    # the mesh reader may otherwise accept a truncated file as a partial mesh.
    if len(data) < 84:
        raise ValueError("Oriented export received an incomplete binary STL")
    count = struct.unpack_from("<I", data, 80)[0]
    if count == 0 or len(data) != 84 + count * 50:
        raise ValueError("Oriented export requires a nonempty, complete binary STL")
    model = mesh.Mesh.from_file(None, fh=io.BytesIO(data), mode=Mode.BINARY)
    vertices = model.vectors.astype(np.float64)
    if not np.isfinite(vertices).all():
        raise ValueError("Exported STL contains non-finite coordinates")

    x, y, z = normals[0]
    radius = math.hypot(y, z)
    rx = math.atan2(y, z) + math.pi if radius else 0.0
    ry = math.atan2(x, radius)
    cx, sx, cy, sy = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry)
    rotation = np.array([[cy, sy * sx, sy * cx], [0, cx, -sx],
                         [-sy, cy * sx, cy * cx]])
    vertices = vertices @ rotation.T
    contact_z = (np.asarray(points) @ rotation.T)[:, 2]
    minimum, maximum = vertices.min(axis=(0, 1)), vertices.max(axis=(0, 1))
    # Cover binary STL float32 rounding without masking a real bed collision.
    tolerance = max(1e-4, float(np.abs(vertices).max()) * np.finfo(np.float32).eps * 8)
    label = planes[0].get("label", "Build Plate face")
    if np.ptp(contact_z) > tolerance:
        raise ValueError(f"{label}: Build Plate faces are not coplanar; export these bodies separately")
    if abs(minimum[2] - contact_z[0]) > tolerance:
        raise ValueError(f"{label}: marked face is not the lowest supporting plane of the exported mesh")
    translation = np.array([-(minimum[0] + maximum[0]) / 2,
                            -(minimum[1] + maximum[1]) / 2, -minimum[2]])
    model.vectors[:] = vertices + translation
    output = io.BytesIO()
    # A stable header keeps unchanged exports byte-identical across builds.
    model.save("oriented.stl", fh=output, mode=Mode.BINARY)
    result = output.getvalue()
    return b"FusionHeadless oriented STL".ljust(80, b"\0") + result[80:]
