import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

import term
import methods
from my_printer import pprint, pprint_hook

def initialize(host:str, port:int):
    term.initialize(host, port)
    methods.initialize(host, port)