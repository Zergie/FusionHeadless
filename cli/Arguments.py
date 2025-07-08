import re

class ListArgument:
    def __init__(self, argument):
        self.items = [item.strip() for item in argument.split(',')]
    def __repr__(self):
        return f"ListArgument({self.items})"
    def __str__(self):
        return self.__repr__()
    def __iter__(self):
        return iter(self.items)

class GroupArgument:
    def __init__(self, argument):
        args = argument.split(',')
        if len(args) == 1:
            self.selector = args[0]
            self.regex = None
            self.name = None
        elif len(args) == 3:
            self.selector, self.regex, self.name = args
            self.regex = re.compile(self.regex.strip(), re.IGNORECASE)
            self.name = self.name.strip()
        else:
            raise ValueError("GroupArgument must be in the format 'selector,regex,name' or 'selector'.")

    def __repr__(self):
        return f"GroupArgument(selector={self.selector}, regex={self.regex}, name={self.name})"

    def __str__(self):
        return self.__repr__()

    def _iter_(self, obj):
        for item in obj:
            if self.regex is None:
                yield item
            elif self.regex.match(item[self.selector]):
                item[self.selector] = self.regex.sub(self.name, item[self.selector])
                yield item

    def __call__(self, obj):
        group = {}

        for item in self._iter_(obj):
            key = item[self.selector]
            if key not in group:
                group[key] = {
                    'name': key,
                    'items': [],
                    'count': 0
                }
            group[key]['items'].append(item)
            if 'count' in item:
                group[key]['count'] += item['count']
            else:
                group[key]['count'] += 1
        return [x for x in group.values()]