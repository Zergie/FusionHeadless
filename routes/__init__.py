from ..route_registry import register
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import status
register("/status", status.handle)

import list
register("/list/components", list.handle)
register("/list/bodies", list.handle)

import export
register("/export/step", export.handle)
register("/export/stl", export.handle)

import list_projects
register("/list/projects", list_projects.handle)

import open
register("/open", open.handle)