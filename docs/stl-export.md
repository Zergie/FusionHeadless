# Print-oriented STL export

[← FusionHeadless](../README.md)

Apply an appearance to the planar face of each printable body that should
contact the print bed. Pass its name explicitly in `orient`, for example:

```
{"format": "stl", "component": "Bracket", "body": ["Body1"], "orient": "Print Bed"}
```

Send this JSON to `POST /export`, or use the generated CLI option:

```
cli/fusion_cli.cmd export --format stl --component Bracket --body Body1 --orient "Print Bed" --output bracket.stl
```

Matching uses a case-sensitive substring, so `Print Bed Blue` also matches.
There is no default appearance name. Omit `orient` or use `"orient": null`
to export an STL in its original orientation. Booleans and blank appearance
names are rejected.
String values are always appearance names, including `"true"` and `"false"`.

PowerShell accepts `-Orient 'Print Bed'`.
Refresh an existing CLI schema
cache with `cli --refresh` after updating the add-in. Git Bash can call the
CLI Python script using its Windows virtual-environment interpreter directly.

The face's outward normal is rotated to negative Z (including reversed Fusion
surface normals). The exported mesh is centered in X/Y and its minimum Z is
placed at zero. The marked face must actually lie on that supporting plane;
geometry protruding below it is rejected. The output is binary STL with
millimeter coordinates, unchanged scale and triangle ordering. X then Y
rotation follows the existing printable-body convention; no extra yaw or
automatic packing is applied.

All exports restore body and occurrence visibility after success or failure.
Component and body selections are validated before visibility changes begin.
Other formats ignore `orient` and preserve their existing export geometry.
Oriented STL export supports a single body or a rigid
group of bodies in one component.
Omitting `body` includes the component's own bodies only when it has no child
occurrences. For assemblies, choose explicit body names in one component.
Each selected body needs a marked planar face. Multiple marked faces must have
matching outward normals and lie on the same plane within mesh precision;
otherwise export the bodies separately. Curved contact faces and missing
markings produce contextual errors.

Fusion reads the markings and exports the selected native geometry on its UI
thread. The existing child then processes the temporary STL with `numpy-stl`;
the model is never rotated, and temporary visibility changes are restored even
on failure. Install/update the repository's `requirements.txt` in `.venv` to
enable this feature. No `stl_cmd`, global Python packages, or NumPy installation
inside Fusion is required. Changes to the new context callback support require
restarting the add-in once; subsequent route changes use the normal restart.

The reusable child-side module is `stl_orientation.orient_stl(data, planes)`.
It accepts binary STL bytes and contact-plane dictionaries containing an
outward `normal`, a `point` in STL millimeters, and an optional diagnostic
`label`, then returns oriented binary STL bytes. It has no Fusion dependency.
