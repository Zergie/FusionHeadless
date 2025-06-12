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
- `app` = `adsk.core.Application.get()` is automatically injected
- `adsk` = Fusion 360 Python API module
- Use `"result = ..."` in `exec` mode to return a value


## 🧪 Test from curl
```bash
curl -X POST http://localhost:5000/eval \
  -H "Content-Type: application/json" \
  -d '{"mode": "eval", "code": "app.activeDocument.name"}'
```


## 🔐 Security
This server runs arbitrary code in your Fusion 360 session.  
Make sure:
- You run it only on localhost
- You don’t expose it via port forwarding or firewalls

## 📚 Additional Endpoints

### `GET /list/bodies`
Returns a list of all bodies of the active document.

### `GET /list/components`
Returns a list of all components of the active document.

### `POST /export/step` and `POST /export/stl`
Exports the active document or component/body to a STEP file or STL file. Returns the file path.

#### 🧠 Parameters:
- `filename`:  optional, the name of the file to export to (with extension)
- `component`: optional, the name of the component to export (if not specified, exports the active document)
- `body`: optional, the name of the body to export (if not specified, exports the entire component)
