import hashlib
import os
import re
import sys
from term import Term
import math

class FileItem:
    def __init__(self, root, name):
        self.name = name
        self.path = os.path.join(root, name)
        self.assigned = []

    def __repr__(self):
        return f"FileItem(name={self.name}, path={self.path})"
    
    def _get_compare_key(self, name, path=None):
        if path is None:
            path = ""
        else:
            path = "/".join(path.split(os.sep)[-2:-1]).lower() + "/"
        
        name = name.replace(' ', '_').lower()
        if name.endswith('.stl'):
            name = name[:-4]
        compare_key = path + "_".join([x for x in name.split('_') if not x.startswith('x') and x != '[a]']) + ".stl"
        return compare_key

    def __eq__(self, value):
        if isinstance(value, FileItem):
            compare_key = self._get_compare_key(value.name)
        elif isinstance(value, str):
            compare_key = self._get_compare_key(value)
        
        if "/" in compare_key:
            return compare_key == self._get_compare_key(self.name, self.path)
        else:
            return compare_key == self._get_compare_key(self.name)

def str2hash(string: str) -> str:
    hash = hashlib.md5(string.encode()).hexdigest()
    return f"{hash[:8]}-{hash[8:12]}-{hash[12:16]}-{hash[16:20]}-{hash[20:]}"

errors = []
warnings = []
def error(message):
    global errors
    if not message in errors:
        errors.append(message)

def warning(message):
    global warnings
    if not message in warnings:
        warnings.append(message)

class Materials:
    base_material = None
    accent_material = None
def match_with_files(data:dict, folder:str, base_material:str, accent_material:str) -> dict:
    global errors, warnings
    errors = []
    warnings = []
    Materials.base_material = base_material
    Materials.accent_material = accent_material
    
    if not os.path.exists(folder):
        raise FileNotFoundError(f"Folder '{folder}' does not exist.")

    if not isinstance(data, dict):
        raise TypeError("Data must be a dictionary with component names as keys.")

    def clean_name(name):
        result = re.sub(r'(^\[a\]_|_x\d+( \(\d+\))?$|( \(\d+\))$)', '', name).lower()
        result = result.replace(' ', '_').lower()
        return result

    def get_name(component, body, count, material) -> str:
        if material == Materials.base_material:
            result = ""
        elif material == Materials.accent_material:
            result = "[a]_"
        else:
            return "/* unknown material */"

        c_name = clean_name(component)
        b_name = clean_name(body)
        if b_name == c_name or b_name.startswith("body"):
            result += c_name
        else:
            result += c_name
            result = f"{b_name}/{result}"
        
        if count > 1:
            result += f"_x{count}"
        return f"{result}.stl"

    fileItems = []
    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith('.stl'):
                fileItems.append(FileItem(root=root, name=name))

    suggested_names = {}
    printable = []
    for component in data.values():
        component_url = Term.url(component['name'], '/select', id=component['id'])
        if 'name' not in component:
            raise ValueError(f"{component_url} does not have a 'name' attribute.")
        if 'bodies' not in component:
            raise ValueError(f"{component_url} does not have a 'bodies' attribute.")
        component['is_printed'] = True

        for body in component['bodies']:
            body_url = Term.url(component['name'] + ' - ' + body['name'], '/select', id=component['id'])
            if 'id' not in body:
                raise ValueError(f"{body_url} does not have an 'id' attribute.")
            if 'name' not in body:
                raise ValueError(f"{body_url} does not have a 'name' attribute.")
            if 'material' not in body:
                raise ValueError(f"{body_url} does not have a 'material' attribute.")
            
            if body['material'] not in [Materials.base_material, Materials.accent_material]:
                body['is_printed'] = False
                continue
            if 'orientation' not in body or len(body['orientation']) == 0:
                error(f"{body_url} does not have an 'orientation'.")
                body['is_printed'] = False
            if 'orientation' in body and len(body['orientation']) > 1:
                error(f"{body_url} has more than one orientation.")
                body['is_printed'] = False
            
            name = get_name(component['name'], body['name'], component['count'], body['material'])
            matches = [fileItem for fileItem in fileItems if fileItem == name]
            suggested_names[name] = 0 if name not in suggested_names else suggested_names[name] + 1
            body['suggested_name'] = name
            body['fixes'] = []
            names = [name]

            if len(matches) == 0 and "/" in name:
                name = name.split("/")[-1]
                names.append(name)
                matches = [fileItem for fileItem in fileItems if fileItem == name]

            if len(matches) == 0:
                name =  get_name(body['name'], body['name'], component['count'], body['material'])
                names.append(name)
                matches = [fileItem for fileItem in fileItems if fileItem == name]
                
            if len(matches) == 0:
                warning(f"No matching file found for {body_url} - {body['name']} -> {name}")
                name = get_name(component['name'], body['name'], component['count'], body['material'])
                fileItem = FileItem(folder, name)
                fileItems.append(fileItem)
                matches = [fileItem]
            
            if len(matches) == 1:
                fileItem = matches[0]
                # if component['id'] in [x['id'] for x in fileItem.assigned]:
                #     for key in list(body.keys()):
                #         del body[key]
                # else:
                #     fileItem.assigned.append(component)
                #     body['path'] = fileItem.path
                fileItem.assigned.append(component)
                body['path'] = fileItem.path
                    
            else:
                m = "\n".join([f"- {match.path}" for match in matches])
                error(f"Multiple matching files found for {body_url} - {body['name']} -> {names}:\n{m}")

            component['bodies'] = [b for b in component['bodies'] if 'id' in b]

        printable_bodies = [x for x in component['bodies'] if x.get('is_printed', True)]
        if len(printable_bodies) > 0:
            printable.append(component)
            printable[-1].update({
                'bodies': printable_bodies,
            })

    for fileItem in [x for x in fileItems if len(x.assigned) > 1]:
        assigned = ", ".join([Term.url(x["name"], "/select", id=x["id"]) for x in fileItem.assigned])
        warning(f"File {fileItem.path} is already assigned multiple times: {assigned}")

    for fileItem in [x for x in fileItems if len(x.assigned) == 0]:
        warning(f"File {fileItem.path} was not assigned to any component.")

    for component in printable:
        for body in component['bodies']:
            if 'suggested_name' not in body:
                error(f"Body {body['name']} in component {component['name']} does not have a 'suggested_name' attribute.")
            elif os.path.basename(body.get('path', '')).lower() != os.path.basename(body['suggested_name']).lower():
                url = Term.url(os.path.basename(body['suggested_name']), "/select", id=component['id'])
                warning(f"Suggested name {url} does not match file name {os.path.basename(body.get('path', ''))}.")
                path = os.path.abspath(body.get('path', ''))
                new_path = os.path.join(os.path.dirname(path), os.path.basename(body['suggested_name']))
                body['fixes'].append(f"mv \"{path}\" \"{new_path}\"")

    for name in [x for x in suggested_names if suggested_names[x] > 1]:
        error(f"File name {name} is suggested for multiple components. Please rename the part to avoid conflicts.")

    ######## ########  ########   #######  ########   ######          ###    ##    ## ########       ##      ##    ###    ########  ##    ## #### ##    ##  ######    ######  
    ##       ##     ## ##     ## ##     ## ##     ## ##    ##        ## ##   ###   ## ##     ##      ##  ##  ##   ## ##   ##     ## ###   ##  ##  ###   ## ##    ##  ##    ## 
    ##       ##     ## ##     ## ##     ## ##     ## ##             ##   ##  ####  ## ##     ##      ##  ##  ##  ##   ##  ##     ## ####  ##  ##  ####  ## ##        ##       
    ######   ########  ########  ##     ## ########   ######       ##     ## ## ## ## ##     ##      ##  ##  ## ##     ## ########  ## ## ##  ##  ## ## ## ##   ####  ######  
    ##       ##   ##   ##   ##   ##     ## ##   ##         ##      ######### ##  #### ##     ##      ##  ##  ## ######### ##   ##   ##  ####  ##  ##  #### ##    ##        ## 
    ##       ##    ##  ##    ##  ##     ## ##    ##  ##    ##      ##     ## ##   ### ##     ##      ##  ##  ## ##     ## ##    ##  ##   ###  ##  ##   ### ##    ##  ##    ## 
    ######## ##     ## ##     ##  #######  ##     ##  ######       ##     ## ##    ## ########        ###  ###  ##     ## ##     ## ##    ## #### ##    ##  ######    ######  

    for item in warnings:
        sys.stderr.write(Term.yellow(f"Warning: {item}\n"))
    for item in errors:
        sys.stderr.write(Term.red(f"Error: {item}\n"))
    sys.stderr.write("\nSummary: " + Term.green(f"{len(data)} processed") + ", " + Term.yellow(f"{len(warnings)} warnings") + ", " + Term.red(f"{len(errors)} errors") + ".\n")



    ########  ########  ######  ##     ## ##       ######## 
    ##     ## ##       ##    ## ##     ## ##          ##    
    ##     ## ##       ##       ##     ## ##          ##    
    ########  ######    ######  ##     ## ##          ##    
    ##   ##   ##             ## ##     ## ##          ##    
    ##    ##  ##       ##    ## ##     ## ##          ##    
    ##     ## ########  ######   #######  ########    ##    

    result = {}
    for component in printable:
        for body in component['bodies']:
            key = str2hash(body.get('path', '')) + ".json"

            def vector_to_rotation_deg(vec):
                # vec: [x, y, z], normal vector to rotate to [0, 0, -1]
                # Only use standard library, no numpy
                target = [0, 0, -1]
                v = list(vec)
                v_norm = math.sqrt(sum(x*x for x in v))
                if v_norm == 0:
                    return [0, 0, 0]
                v = [x / v_norm for x in v]
                dot = sum(v[i]*target[i] for i in range(3))
                dot = max(min(dot, 1.0), -1.0)
                if all(abs(v[i] - target[i]) < 1e-6 for i in range(3)):
                    return [0, 0, 0]
                if all(abs(v[i] + target[i]) < 1e-6 for i in range(3)):
                    return [180, 0, 0]
                axis = [
                    v[1]*target[2] - v[2]*target[1],
                    v[2]*target[0] - v[0]*target[2],
                    v[0]*target[1] - v[1]*target[0]
                ]
                axis_norm = math.sqrt(sum(x*x for x in axis))
                if axis_norm == 0:
                    return [0, 0, 0]
                axis = [x / axis_norm for x in axis]
                angle = math.acos(dot)
                angle_deg = math.degrees(angle)
                # Euler conversion is non-trivial; fallback to axis-angle
                return [round(axis[0]*angle_deg, 3), round(axis[1]*angle_deg, 3), round(axis[2]*angle_deg, 3)]

            orientation = body['orientation'][0] if len(body['orientation']) > 0 else [0, 0, 1]
            rotation = vector_to_rotation_deg(orientation)
            
            item = { 
                'id': key.replace('.json', ''),
                'path': body.get('path', ''),
                'bodies': [body['name']],
                'body_hashes': [body['hash']],
                'rotation': f"-rx {rotation[0]} -ry {rotation[1]} -rz {rotation[2]}",
                'component_id': component['id'],
                'component_name': component['name'],
                'suggested_name': body['suggested_name'],
            }
            if len(body['fixes']) > 0:
                item['fixes'] = body['fixes']

            
            if not key in result:
                result[key] = item
            elif item['component_id'] == result[key]['component_id'] and item['rotation'] == result[key]['rotation']:
                result[key]['bodies'].append(body['name'])
                result[key]['body_hashes'].append(body['hash'])
            elif item['component_id'] != result[key]['component_id']:
                sys.stderr.write(Term.red(f"Error: component_id mismatch\n- {item}\n- {result[key]}\n"))
                sys.exit(1)
            elif item['rotation'] != result[key]['rotation']:
                sys.stderr.write(Term.red(f"Error: rotation mismatch\n- {item}\n- {result[key]}\n"))
                sys.exit(1)
            else:
                sys.stderr.write(Term.red(f"Error: unknown error !!!\n"))
                sys.exit(1)

    return result

if __name__ == "__main__":
    import json
    from my_printer import pprint

    Term.initialize("localhost", 5000)
    baseFolder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    with open(os.path.join(baseFolder, 'obj', 'components.json'), "r") as f:
        data = json.load(f)

    result = match_with_files(data, folder=os.path.join(baseFolder, 'STLs'), base_material="ABS Plastic (Voron Black)", accent_material="ABS Plastic (Voron Red)")

    pprint(result)