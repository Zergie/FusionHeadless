import route_registry
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
register = route_registry.register

import status
register("/status", status.handle)

import list
register("/components", list.handle)
register("/bodies", list.handle)

import export
register("/export/step", export.handle)
register("/export/stl", export.handle)

import list_projects
register("/projects", list_projects.handle)

import document
register("/document", document.handle)

import files
register("/files", files.handle)

import render
register("/render", render.handle)

import select
register("/select", select.handle)