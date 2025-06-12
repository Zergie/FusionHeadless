from ..route_registry import register


from . import status
register("/status", status.handle)

from . import list
register("/list/components", list.handle)
register("/list/bodies", list.handle)

from . import export
register("/export/step", export.handle)
register("/export/stl", export.handle)