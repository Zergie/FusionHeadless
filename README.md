# FusionHeadless

**FusionHeadless** is a developer-focused add-in for Autodesk Fusion 360 that launches a local REST server, allowing you to run arbitrary Python code (via `eval()` or `exec()`) against the Fusion API in real time.

Ideal for automation, testing, and headless control of your Fusion instance from external scripts or systems.

## 🚀 Features
- Exposes Fusion 360's full Python API over HTTP
- Supports `eval()` for expressions and `exec()` for full scripts
- Exposes an MCP-compatible JSON-RPC endpoint at `POST /mcp` for tool discovery and calls
- Automatically injects `app` and `adsk` into the global context
- Runs locally on `http://localhost:5000`
- Designed for internal/local use — **not intended for public deployment**


## ⚠️ Warning
This add-in executes raw Python code via REST — it is **inherently unsafe**.
Only use it on **trusted machines** and restrict access to `localhost`.


## 📦 Installation
1. Locate your Fusion 360 **Add-ins folder**:

   - Windows:
     `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\`

   - macOS:
     `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`

2. Clone or download this repo into that folder:
   ```bash
   git clone https://github.com/Zergie/FusionHeadless.git
   cd FusionHeadless
   python -m pip install -r requirements.txt # for development only, e.g. send.py
   ```

3. Launch Fusion 360 and go to:
   **Tools > Add-Ins > Scripts and Add-Ins**

4. Select `FusionHeadless` from the list and click **Run**.


## 🔌 How It Works
FusionHeadless starts an HTTP server on `localhost:5000` and exposes the following endpoint:

### `POST /eval`
Send a JSON payload to evaluate or execute Python code inside Fusion.

#### 🧠 Parameters:
- `code`: the Python code to run (as a string)
- `depth`: optional, the maximum recursion depth for object serialization

#### ✅ Example: `eval`
```http
POST /eval
Content-Type: application/json

{
  "code": "app.activeDocument.name"
}
```

#### ✅ Example: `exec`
```http
POST /exec
Content-Type: application/json

{
  "code": "app.activeDocument.name"
}
```

#### ✅ Example: `exec` with result
```json
{
  "code": "
comp = app.activeProduct.rootComponent
sk = comp.sketches.add(comp.xYConstructionPlane)
sk.name = 'API Sketch'
result = sk.name
"
}
```

#### 🔁 Response
```json
{
  "status": "ok",
  "result": "API Sketch"
}
```

### `POST /mcp`
Exposes MCP-compatible JSON-RPC 2.0 endpoint for MCP clients (for example VS Code MCP integrations).

Current MCP tools include:
- `list_open_documents`: Lists open top-level Fusion documents and marks the active one.
- `get_api_documentation`: Searches Fusion API classes, members, and docstrings in `adsk`.
- `search_components`: Finds and counts matching components/occurrences by name (plain text or regex).

#### ⚙️ VS Code MCP configuration example
Add the following to your VS Code MCP configuration file (for example `.vscode/mcp.json`) to register FusionHeadless:

```json
{
  "servers": {
    "fusionheadless": {
      "type": "http",
      "url": "http://localhost:5000/mcp"
    }
  }
}
```

After saving, refresh MCP servers in VS Code and use `tools/list` to confirm the server is reachable.


## 💡 Tips
- automatically injects into the global context:
  - `adsk` = Fusion 360 Python API module
  - `app` = `adsk.core.Application.get()`
  - `ui` = `adsk.core.Application.get().userInterface`
  - `os` = Python's `os` module
  - `sys` = Python's `sys` module
- Use `"result = ..."` in `exec` mode to return a value


## 🧪 Test from curl
```bash
curl -X POST http://localhost:5000/eval \
  -H "Content-Type: application/json" \
  -d '{"code": "app.activeDocument.name"}'
```

Note on wsl: If you are using WSL, you might want to setup `Mirrored Mode WSL2 Networking`.



## 🔐 Security
This server runs arbitrary code in your Fusion 360 session.
Make sure:
- You run it only on localhost
- You don’t expose it via port forwarding or firewalls

## 📚 All Endpoints
### `GET /bodies`
Returns a list of all bodies in the active document.

### `GET /components`
Returns a list of all components in the active document.

### `POST /document`
Returns metadata about the currently active document.

#### 🧠 Parameters:
- `POST /document?open=<id>`: Opens a document by ID.
- `POST /document?close=<saveChanges>`: Closes the active document, optionally saving changes.

### `POST /eval`
Evaluates a Python expression and returns the result.

#### 🧠 Parameters:
- `code`: the Python code to evaluate (as a string)
- `depth`: optional, the maximum recursion depth for object serialization

### `POST /exec`
Executes Python code in the Fusion 360 environment.

#### 🧠 Parameters:
- `code`: the Python code to execute (as a string)
- `depth`: optional, the maximum recursion depth for object serialization

### `POST /mcp`
MCP-compatible JSON-RPC 2.0 endpoint for tool discovery and execution.

#### 🧠 Notes:
- Use `tools/list` to discover available tools.
- Use `tools/call` to run a tool with arguments.
- Tool names are filename-derived from `routes/mcp/*.py`.

### `GET /files`
Returns a list of all files in all projects.

#### 🧠 Parameters:
- `GET /files?active`: returns only the active document
- `GET /files?id=<id>`: Returns a file by its ID.
- `GET /files?name=<name>`: Returns only files with that name.

### `GET /parameter`
Returns a list of all parameters in the active document.

#### 🧠 Parameters:
- `<nothing>`: Without parameters, returns all available parameters.
- `<name>=<value>`: Returns a specific parameter by name.

### `POST /parameter`
Updates parameters in the active document.

#### 🧠 Parameters:
- `<name of parameter>`: the name of the parameter to update
- `<value>`: the new value for the parameter (e.g., `d81="32 mm"`)

### `GET /projects`
Returns a list of all projects in the application.

### `POST /reload`
Reloads the FusionHeadless add-in.

### `GET /render`
Renders the current view or document and returns the image.

#### 🧠 Parameters:
- `quality`: `25` to `100` for rendering, `Shaded`, `ShadedWithHiddenEdges`, `ShadedWithVisibleEdgesOnly`, `Wireframe`, `WireframeWithHiddenEdges`, `WireframeWithVisibleEdgesOnly` for Screen Capture
- `exposure`: optional, the camera exposure value for the render
- `focalLength`: optional, the focal length for the camera
- `height`: optional, the height of the rendered image
- `hide`: optional, what bodies/components to hide in the render (e.g., `all` or `<body/component name>`)
- `isAntiAliased`: optional, whether the Screen Capture should be anti-aliased (default is `true`, not available for rendering)
- `isBackgroundTransparent`: optional, whether the background should be transparent (default is `false`)
- `isolate`: optional, what bodies/components to isolate in the render
- `show`: optional, what bodies/components to show in the render (e.g., `all` or `<body/component name>`)
- `view`: optional, the camera view to use (e.g., `Home` or any custom named view)
- `width`: optional, the width of the rendered image

### `POST /restart`
Restarts the FusionHeadless server.

### `POST /select`
Selects an entity in the Fusion 360 UI by ID or name.

#### 🧠 Parameters:
- `id`: the ID of the entity to select
- `name`: the name of the entity to select

### `POST /export`
Exports the active document, component, or body to file.

#### 🧠 Parameters:
- `component`: optional, the name of the component to export (if not specified, exports the active document)
- `body`: optional, the name of the body to export (if not specified, exports the entire component)
- `format`: the format to export to (e.g., `stl`, `step`, `f3d`, `3mf`, `obj`)

### `GET /status`
Returns the status of FusionHeadless.
