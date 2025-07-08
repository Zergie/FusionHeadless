import urllib.parse

def initialize(host_value, port_value):
    Term.initialize(host_value, port_value)

class Term:
    RESET = '\033[0m'

    @classmethod
    def initialize(cls, host_value, port_value):
        cls.host = host_value
        cls.port = port_value
    
    @classmethod
    def url(cls, text, route, **kwargs):
        url = f"FusionHeadless://{cls.host}:{cls.port}{route}"
        if kwargs:
            url += "?" + urllib.parse.urlencode(kwargs)
        return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"

    @classmethod
    def red(cls, text):
        return f"\033[91m{text}{cls.RESET}"

    @classmethod
    def green(cls, text):
        return f"\033[92m{text}{cls.RESET}"

    @classmethod
    def yellow(cls, text):
        return f"\033[93m{text}{cls.RESET}"
    
    @classmethod
    def blue(cls, text):
        return f"\033[94m{text}{cls.RESET}"