"""Exercise extension file changes in an isolated copy of the source tree."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ExtensionPackageTests(unittest.TestCase):
    def test_restart_loads_changed_helpers_and_added_or_removed_modules(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for path in root.glob("*.py"):
                shutil.copy2(path, copy / path.name)
            for package in ("routes", "mcp"):
                shutil.copytree(root / package, copy / package,
                                ignore=shutil.ignore_patterns("__pycache__"))
            result = subprocess.run(
                [sys.executable, "-S", "-B", "-c", RELOAD_SCENARIO], cwd=copy,
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


RELOAD_SCENARIO = r'''
from pathlib import Path
import sys
import routes
import mcp.tools
from context import registry
from extension_state import extension_fingerprint, reset_extensions
from mcp.registry import tool_definitions
from routing import route_definitions

baseline = extension_fingerprint()
old_route = routes.bodies_route
old_helper = routes._bodies._value
old_tool = mcp.tools.mcp_list_open_documents
route_init = Path('routes/__init__.py')
tool_init = Path('mcp/tools/__init__.py')
original_routes = route_init.read_text()
original_tools = tool_init.read_text()
support = Path('fusion_support.py')
original_support = support.read_text()
support.write_text(original_support.replace('return getattr(item, name)', 'return "changed helper"'))
assert extension_fingerprint() != baseline
reset_extensions()
assert routes._bodies._value(None, 'anything') == 'changed helper'
assert routes.bodies_route is not old_route
assert routes._bodies._value is not old_helper
assert mcp.tools.mcp_list_open_documents is not old_tool
assert sys.modules['mcp.tools'] is mcp.tools

route_file = Path('routes/probe.py')
route_file.write_text('from routing import api_route\n@api_route("/package-probe")\ndef route_probe(context):\n    return "new route"\n')
tool_file = Path('mcp/tools/probe.py')
tool_file.write_text('from mcp.registry import mcp_tool\n@mcp_tool("package_probe", description="Probe", input_schema={})\ndef tool_probe(query, context):\n    return "new tool"\n')
route_init.write_text(original_routes + '\nfrom .probe import route_probe\n')
tool_init.write_text(original_tools + '\nfrom .probe import tool_probe\n')
reset_extensions()
assert routes.route_probe(None) == 'new route'
assert mcp.tools.tool_probe({}, None) == 'new tool'
assert any(d.operation is routes.route_probe for d in route_definitions())
assert any(d.operation is mcp.tools.tool_probe for d in tool_definitions())

# Fail halfway through importing a leaf, after it registered its operation.
tool_file.write_text(tool_file.read_text() + '\nraise RuntimeError("broken leaf")\n')
try:
    reset_extensions()
except RuntimeError as error:
    assert 'broken leaf' in str(error)
else:
    raise AssertionError('broken tool import succeeded')
assert not route_definitions() and not tool_definitions()
assert set(registry.fusion) == {'FusionContext'}
assert 'routes.probe' not in sys.modules and 'mcp.tools.probe' not in sys.modules

# Remove both files and imports, then recover without stale registrations.
route_file.unlink()
tool_file.unlink()
route_init.write_text(original_routes)
tool_init.write_text(original_tools)
support.write_text(original_support)
assert reset_extensions() == baseline
assert not hasattr(routes, 'route_probe')
assert not hasattr(mcp.tools, 'tool_probe')
assert 'route_probe' not in registry.fusion and 'tool_probe' not in registry.fusion
assert routes._bodies._value(type('Item', (), {'value': 42})(), 'value') == 42
'''
