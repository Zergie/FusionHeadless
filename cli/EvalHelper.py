import re

class EvalDict(dict):
    def update(self, other):
        super().update(other)
        return self
    def remove(self, key):
        if key in self:
            del self[key]
        return self
    def search(self, key, pattern, group=0):
        match = re.search(pattern, self[key])
        if match:
            return match.group(group)
        else:
            return None
    def sub(self, key, pattern, repl):
        if self[key]:
            return re.sub(pattern, repl, self[key])
        else:
            return None
class EvalList(list):
    def __iter__(self):
        for i in super().__iter__():
            if isinstance(i, dict):
                yield EvalDict(i)
            elif isinstance(i, list):
                yield EvalList(i)
            else:
                yield i