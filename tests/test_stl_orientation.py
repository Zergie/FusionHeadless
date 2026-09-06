from __future__ import annotations

import io
import struct
import unittest

import numpy as np
from stl import Mode, mesh

from stl_orientation import orient_stl


def box_stl(offset=(0, 0, 0), rotation=None):
    vertices = np.array([[0, 0, 0], [2, 0, 0], [2, 3, 0], [0, 3, 0],
                         [0, 0, 4], [2, 0, 4], [2, 3, 4], [0, 3, 4]], dtype=float)
    faces = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
             [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
             [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    if rotation is not None:
        vertices = vertices @ rotation.T
    vertices += offset
    model = mesh.Mesh(np.zeros(len(faces), dtype=mesh.Mesh.dtype))
    model.vectors[:] = vertices[faces]
    output = io.BytesIO()
    model.save("box.stl", fh=output, mode=Mode.BINARY)
    return output.getvalue()


def read_stl(data):
    return mesh.Mesh.from_file(None, fh=io.BytesIO(data), mode=Mode.BINARY)


class StlOrientationTests(unittest.TestCase):
    def test_rotates_contact_face_down_centers_and_preserves_geometry(self):
        # Test identity, opposite direction, every axial direction, and oblique.
        for normal in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0],
                       [0, 1, 0], [0, -1, 0], [1, 2, 3], [-2, -3, -4]):
            with self.subTest(normal=normal):
                normal = np.array(normal, dtype=float)
                normal /= np.linalg.norm(normal)
                # Independently construct an orthonormal frame for the input.
                z = -normal
                guide = np.array([1, 0, 0]) if abs(z[0]) < .9 else np.array([0, 1, 0])
                x = np.cross(guide, z)
                x /= np.linalg.norm(x)
                rotation = np.column_stack([x, np.cross(z, x), z])
                point = [15, -23, 47]
                original = box_stl(point, rotation)
                planes = [{"normal": normal.tolist(), "point": point}]
                result = orient_stl(original, planes)
                before, after = read_stl(original), read_stl(result)
                minimum = after.vectors.min(axis=(0, 1))
                maximum = after.vectors.max(axis=(0, 1))
                np.testing.assert_allclose((minimum + maximum)[:2], 0, atol=1e-5)
                self.assertAlmostEqual(minimum[2], 0, places=5)
                np.testing.assert_allclose(after.vectors[:2, :, 2], 0, atol=1e-5)
                self.assertTrue((after.normals[:2, 2] < 0).all())
                a, b = before.vectors.reshape(-1, 3), after.vectors.reshape(-1, 3)
                np.testing.assert_allclose(
                    np.linalg.norm(a[:, None] - a, axis=2),
                    np.linalg.norm(b[:, None] - b, axis=2), atol=1e-5)
                self.assertEqual(result, orient_stl(original, planes))

    def test_accepts_coplanar_markings_and_rejects_conflicts_and_noncontact(self):
        data = box_stl()
        plane = {"normal": [0, 0, -1], "point": [0, 0, 0], "label": "Bracket"}
        orient_stl(data, [plane, {**plane, "point": [2, 3, 0]}])
        for planes, message in [([], "marked"),
                                ([plane, {**plane, "normal": [0, 1, 0]}], "conflicting"),
                                ([plane, {**plane, "point": [0, 0, 1]}], "coplanar"),
                                ([{**plane, "point": [0, 0, 1]}], "lowest supporting"),
                                ([{**plane, "normal": [0, 0, 0]}], "invalid"),
                                ([{**plane, "normal": [float("nan"), 0, 0]}], "invalid")]:
            with self.subTest(planes=planes), self.assertRaisesRegex(ValueError, message):
                orient_stl(data, planes)

    def test_rejects_truncated_empty_and_nonfinite_meshes(self):
        planes = [{"normal": [0, 0, -1], "point": [0, 0, 0]}]
        data = box_stl()
        invalid = [b"bad", data[:-1], data[:80] + struct.pack("<I", 0)]
        bad_vertex = bytearray(data)
        struct.pack_into("<f", bad_vertex, 96, float("nan"))
        invalid.append(bytes(bad_vertex))
        for item in invalid:
            with self.subTest(size=len(item)), self.assertRaises(ValueError):
                orient_stl(item, planes)


if __name__ == "__main__":
    unittest.main()
