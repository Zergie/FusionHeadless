class EvalDict(dict):
    def update(self, other):
        super().update(other)
        return self

class EvalList(list):
    pass