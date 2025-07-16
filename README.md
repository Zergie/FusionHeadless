# FusionHeadless

**FusionHeadless** is a developer-focused add-in for Autodesk Fusion 360 that launches a local REST server, allowing you to run arbitrary Python code (via `eval()` or `exec()`) against the Fusion API in real time.

Ideal for automation, testing, and headless control of your Fusion instance from external scripts or systems.

## 🚀 Features
- Exposes Fusion 360's full Python API over HTTP
- Supports `eval()` for expressions and `exec()` for full scripts
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

### `GET /files`
Returns a list of all files in all projects.

#### 🧠 Parameters:
- `GET /files?active`: returns only the active document
- `GET /files?id=<id>`: Returns a file by its ID.
- `GET /files?name=<name>`: Returns only files with that name.

### `GET /parameter`
Returns a list of all parameters in the active document.

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
