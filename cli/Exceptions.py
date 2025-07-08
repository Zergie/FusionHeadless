import json
suppress_errors = False

class HttpException(Exception):
    def __init__(self, status, reason):
        super().__init__(f"HttpException {status}: {reason}")
        self.status = status
        self.reason = reason
    def __str__(self):
        return f"HttpException {self.status}: {self.reason}"

def raise_error(resp_status, resp_reason, resp_data, file_path_hint=None):
    global suppress_errors
    try:
        error_data = json.loads(resp_data)
    except json.JSONDecodeError:
        error_data = resp_data.decode()

    if isinstance(error_data, dict):
        if 'traceback' in error_data:
            traceback = error_data['traceback'].strip()
            if file_path_hint:
                traceback = traceback.replace("<string>", file_path_hint)
            print(f"{traceback}")
        elif 'message' in error_data:
            print(f"{error_data['message'].strip()}")
    else:
        if file_path_hint:
            error_data = error_data.replace("<string>", file_path_hint)
        print(f"{error_data}")
    
    if suppress_errors:
        print(f"HttpException {resp_status}: {resp_reason}")
        return ""
    else:
        raise HttpException(resp_status, resp_reason)