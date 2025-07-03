"""
Select an occurrence by ID or name.
"""
def find_occurrence(id_or_name: list[str]|str, design) -> any:
    if isinstance(id_or_name, str):
        id_or_name = [id_or_name]
    
    for item in id_or_name:
        for occurrence in design.rootComponent.allOccurrences:
            component = occurrence.component
            if component.name == item:
                return occurrence
            if component.id == item:
                return occurrence
    return None

def handle(app, query:dict) -> any:
    design = app.activeProduct
    
    occurrence = None
    if "id" in query:
        occurrence = find_occurrence(query["id"], design)
    elif "name" in query:
        occurrence = find_occurrence(query["name"], design)

    if not occurrence:
        raise Exception(f"Occurrence with id or name '{query.get('id', query.get('name'))}' not found.")

    occurrence.isIsolated = True
    if not occurrence.isVisible:
        for occ in design.rootComponent.allOccurrences:
            occ.isLightBulbOn = False

        occurrence.isLightBulbOn = True
        occurrence.component.isLightBulbOn = True

    if not occurrence.isVisible:
        assembly_context = occurrence.assemblyContext
        while assembly_context and not assembly_context.isVisible:
            assembly_context.isLightBulbOn = True
            assembly_context = assembly_context.assemblyContext

    occurrence.activate()
    
    viewport = app.activeViewport
    viewport.goHome()
    viewport.fit()

    if query.get("focus", True):
        import win32gui # type: ignore
        result = []
        def winEnumHandler(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                n = win32gui.GetWindowText(hwnd)  
                if n and "Fusion" in n:
                    result.append((hwnd, n))

        win32gui.EnumWindows(winEnumHandler, None)
        hwnd, name = sorted(result, key=lambda x: len(x[1]))[-1]

        # A bit of a hack, but it works to bring the Fusion 360 window to the front
        win32gui.ShowWindow(hwnd, 6)
        win32gui.ShowWindow(hwnd, 9)

    return {
        "id": occurrence.component.id,
        "name": occurrence.component.name,
    }

if __name__ == "__main__":
    import _client_
    _client_.test(__file__, { "query" : { "name": "Top Panel", "focus": False }})