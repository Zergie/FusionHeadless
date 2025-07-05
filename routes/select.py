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

def get_assembly_contexts(occurrence) -> list[any]:
    assembly_contexts = []
    if occurrence.assemblyContext:
        assembly_contexts.append(occurrence.assemblyContext)
        occ = occurrence.assemblyContext
        while occ.assemblyContext:
            assembly_contexts.append(occ.assemblyContext)
            occ = occ.assemblyContext
        assembly_contexts.reverse()
    return assembly_contexts

def handle(app, query:dict) -> any:
    design = app.activeProduct
    
    occurrence = None
    if "id" in query:
        occurrence = find_occurrence(query["id"], design)
    elif "name" in query:
        occurrence = find_occurrence(query["name"], design)

    if not occurrence:
        raise Exception(f"Occurrence with id or name '{query.get('id', query.get('name'))}' not found.")

    if occurrence.assemblyContext:
        assembly_contexts = get_assembly_contexts(occurrence)
        for assembly_context in assembly_contexts:
            assembly_context.isLightBulbOn = True
            assembly_context.isIsolated = True

        for assembly_context in assembly_contexts:
            for occ in assembly_context.childOccurrences:
                if not occ.isVisible:
                    pass
                elif occ.component.id == occurrence.component.id:
                    pass
                elif occ.component.id in [x.component.id for x in assembly_contexts]:
                    pass
                else:
                    occ.isLightBulbOn = False
        
    else:
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
    _client_.test(__file__, { "name": "Moving", "focus": False })