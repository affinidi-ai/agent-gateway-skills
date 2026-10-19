"""Evaluate a case's check expression over a JSON document without Python's full `eval`.

An expression is Python syntax limited to what checks need: literals, `doc` and `env`, subscripts,
comparisons, boolean logic, arithmetic, comprehensions and generator expressions, a few built-in
functions and a few read-only string and mapping methods. Anything else, such as an import, a lambda,
an assignment, a dunder name or an unlisted call, is refused before the expression runs.

    python3 expr.py check FILE EXPR    exit 0 when EXPR is true over the first JSON document in FILE
    python3 expr.py get FILE EXPR      print EXPR's value over the JSON document in FILE
"""

import ast
import json
import os
import sys

FUNCTIONS = {
    "all": all, "any": any, "bool": bool, "dict": dict, "float": float, "int": int, "isinstance": isinstance,
    "len": len, "list": list, "max": max, "min": min, "next": next, "set": set, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple,
}
METHODS = {
    "count", "endswith", "find", "get", "index", "items", "keys", "lower", "lstrip", "replace", "rstrip",
    "split", "startswith", "strip", "upper", "values",
}
NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add,
    ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn, ast.IfExp, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.Subscript, ast.Slice, ast.Attribute, ast.Call, ast.keyword, ast.List, ast.Tuple, ast.Set, ast.Dict,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
)
if hasattr(ast, "Index"):  # Python 3.8 wraps subscripts in Index
    NODES += (ast.Index,)


class Refused(ValueError):
    pass


def compile_expr(expr):
    """The compiled expression, after checking every node against the allowed grammar."""
    tree = ast.parse(expr, mode="eval")
    bound = set()
    for node in ast.walk(tree):
        if not isinstance(node, NODES):
            raise Refused("not allowed in a check expression: %s" % type(node).__name__)
        if isinstance(node, ast.comprehension):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in FUNCTIONS and node.id not in ("doc", "env") and node.id not in bound:
                raise Refused("unknown name in a check expression: %s" % node.id)
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr not in METHODS):
            raise Refused("method not allowed in a check expression: %s" % node.attr)
        if isinstance(node, ast.Call):
            func = node.func
            if not (isinstance(func, ast.Attribute) or (isinstance(func, ast.Name) and func.id in FUNCTIONS)):
                raise Refused("call not allowed in a check expression")
    return compile(tree, "<check>", "eval")


def evaluate(expr, doc):
    # One namespace for everything, so generator expressions and comprehensions can see doc and env.
    scope = dict(FUNCTIONS, doc=doc, env=dict(os.environ), __builtins__={})
    return eval(compile_expr(expr), scope)


def first_json(text):
    """The first JSON object or array in TEXT, which may hold other output around it."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return decoder.raw_decode(text, i)[0]
            except ValueError:
                continue
    return None


def main(argv):
    if len(argv) != 4 or argv[1] not in ("check", "get"):
        sys.exit("usage: expr.py check|get FILE EXPR")
    mode, path, expr = argv[1:]
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if mode == "check":
        doc = first_json(text)
        if doc is None:
            sys.exit("no JSON document in the output")
    else:
        doc = json.loads(text)
    try:
        value = evaluate(expr, doc)
    except Refused as error:
        sys.exit(str(error))
    if mode == "check":
        sys.exit(0 if value else 1)
    print(value if isinstance(value, str) else json.dumps(value))


if __name__ == "__main__":
    main(sys.argv)
