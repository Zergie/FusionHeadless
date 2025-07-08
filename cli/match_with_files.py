import os
import re
import sys
from term import Term

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

def match_with_files(data:list, folder:str, accent_color:str) -> list:
    global errors, warnings
    errors = []
    warnings = []
    
    if not os.path.exists(folder):
        raise FileNotFoundError(f"Folder '{folder}' does not exist.")

    if not isinstance(data, list):
        raise TypeError("Data must be a list of items with 'name' attribute.")

    def clean_name(name):
        result = re.sub(r'(^\[a\]_|_x\d+( \(\d+\))?$|( \(\d+\))$)', '', name).lower()
        result = result.replace(' ', '_').lower()
        return result

    def get_name(component, body, count, color):
        result = ""
        if color == accent_color:
            result += f"[a]_"

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

    for component in data:
        if 'name' not in component:
            raise ValueError(f"Each item in data must have a 'name' attribute. ({component})")
        if 'bodies' not in component:
            raise ValueError(f"Each item in data must have a 'bodies' attribute. ({component})")
        if not isinstance(component['bodies'], list):
            raise TypeError(f"'bodies' attribute must be a list. ({component})")

        for body in component['bodies']:
            if 'id' not in body:
                raise ValueError(f"Each body in 'bodies' must have an 'id' attribute. ({body})")
            if 'name' not in body:
                raise ValueError(f"Each body in 'bodies' must have a 'name' attribute. ({body})")
            
            name = get_name(component['name'], body['name'], component['count'], body['color'])
            matches = [fileItem for fileItem in fileItems if fileItem == name]
            body['suggested_name'] = name
            body['fixes'] = []

            if len(matches) == 0 and "/" in name:
                name = name.split("/")[-1]
                matches = [fileItem for fileItem in fileItems if fileItem == name]

            if len(matches) == 0:
                name =  get_name(body['name'], body['name'], component['count'], body['color'])
                matches = [fileItem for fileItem in fileItems if fileItem == name]
                
            if len(matches) == 0:
                url = Term.url(component['name'], '/select', id=component['id'])
                warning(f"No matching file found for {url} - {body['name']} -> {name}")
                name = get_name(component['name'], body['name'], component['count'], body['color'])
                fileItem = FileItem(folder, name)
                fileItems.append(fileItem)
                matches = [fileItem]
            
            if len(matches) == 1:
                fileItem = matches[0]
                if component['id'] in [x['id'] for x in fileItem.assigned]:
                    for key in list(body.keys()):
                        del body[key]
                else:
                    fileItem.assigned.append(component)
                    body['path'] = fileItem.path
                    
            else:
                url = Term.url(component['name'], '/select', id=component['id'])
                m = "\n".join([f"- {match.path}" for match in matches])
                error(f"Multiple matching files found for {url} - {body['name']} -> {name}:\n{m}")

            component['bodies'] = [b for b in component['bodies'] if 'id' in b]

    for fileItem in [x for x in fileItems if len(x.assigned) > 1]:
        assigned = ", ".join([Term.url(x["name"], "/select", id=x["id"]) for x in fileItem.assigned])
        warning(f"File {fileItem.path} is already assigned multiple times: {assigned}")

    for fileItem in [x for x in fileItems if len(x.assigned) == 0]:
        warning(f"File {fileItem.path} was not assigned to any component.")

    for component in [x for x in data if len(x['bodies']) > 0]:
        for body in component['bodies']:
            if 'path' not in body:
                error(f"Body {body['name']} in component {component['name']} does not have a 'path' attribute.")
            elif not os.path.exists(body['path']):
                error(f"File {body['path']} does not exist.")

            if 'suggested_name' not in body:
                error(f"Body {body['name']} in component {component['name']} does not have a 'suggested_name' attribute.")
            elif os.path.basename(body['path']).lower() != os.path.basename(body['suggested_name']).lower():
                url = Term.url(os.path.basename(body['suggested_name']), "/select", id=component['id'])
                warning(f"Suggested name {url} does not match file name {os.path.basename(body['path'])}.")
                path = os.path.abspath(body['path'])
                new_path = os.path.join(os.path.dirname(path), os.path.basename(body['suggested_name']))
                body['fixes'].append(f"mv \"{path}\" \"{new_path}\"")

    for item in warnings:
        sys.stderr.write(Term.yellow(f"Warning: {item}\n"))
    for item in errors:
        sys.stderr.write(Term.red(f"Error: {item}\n"))
    sys.stderr.write("\nSummary: " + Term.green(f"{len(data)} processed") + ", " + Term.yellow(f"{len(warnings)} warnings") + ", " + Term.red(f"{len(errors)} errors") + ".\n")

    result = {}
    for component in [x for x in data if len(x['bodies']) > 0]:
        for body in component['bodies']:
            if not body['path'] in result:
                result[body['path']] = []
            item = { 
                'body_id': body['id'],
                'body_name': body['name'],
                'suggested_name': body['suggested_name'],
                'component_id': component['id'],
                'component_name': component['name'],
                'color': body['color'],
                'count': component['count'],
            }
            if len(body['fixes']) > 0:
                item['fixes'] = body['fixes']
            result[body['path']].append(item)

    return result