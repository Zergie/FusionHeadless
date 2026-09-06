# Local STL preparation

`match_with_files.py` restores the local printable-body matching and export
manifest workflow. It uses only Python's standard library and works offline.
It accepts the unwrapped component JSON written by `fusion_cli components
--output ...`, or the old `{"status":"ok","result":...}` envelope.

Run from the YAMMU root after obtaining `obj/components.json`:

```sh
py -3 FusionAddons/FusionHeadless/cli/match_with_files.py \
  --file obj/components.json \
  --match-with-files STLs \
  --base-material 'ABS Plastic (Voron Black)' \
  --accent-material 'ABS Plastic (Voron Red)' \
  --output obj/components.printed.json \
  --outdir obj/STLs
```

`--file -` reads stdin. Omit both output options to print the combined JSON.
Both outputs can be written in one invocation; identical files retain their
timestamps. Existing STL geometry is never modified, and stale manifests are
not deleted.

Records retain `id`, `path`, `bodies`, `body_hashes`, `rotation`, `component_id`,
`component_name` and `suggested_name`. IDs use the legacy hash of the selected
path, so use the same relative folder spelling and working directory across
builds. Bodies with the same component, target path, suggested name and rotation
share a record. Base/accent materials, quantity suffixes and body subfolders
follow the original naming conventions. Missing files produce suggested paths;
unused files and naming differences are reported on stderr.

Ambiguous matches, conflicting output assignments and missing or invalid Build
Plate orientations fail before writing manifests. Unlike the old helper, input
component objects are not mutated and invalid printed bodies are not silently
omitted. Rotation metadata describes sequential X then Y rotations to put the
Build Plate normal along negative Z; oblique normals use Euler rotations rather
than the old axis-angle approximation. This metadata remains available for
legacy consumers; the oriented export endpoint reads the marked faces directly.

This helper prepares metadata. Export each component/body group through
`fusion_cli export --orient "Build Plate"` to rotate, center X/Y, and place the
contact plane at Z=0. There is no default appearance name in the export API.
YAMMU's `make obj/STLs` integrates matching, oriented export, and incremental
publication through its `tools/build_stls.py` helper. No external STL tools or
local Python `--eval` expressions are needed.
