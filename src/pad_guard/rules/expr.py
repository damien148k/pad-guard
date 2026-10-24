"""Safe evaluator for the small boolean/arithmetic expressions found in profiles.

Profiles contain expressions such as ``"area_pct_max >= 1 and duration_s >= 1"``
or ``"100 - 40*blocking - 10*major - 2*minor"``. They are parsed with :mod:`ast` and
only a whitelist of node types is accepted, so no Python code can be executed.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Iterable, Mapping

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_CMP_OPS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Load,
    *_BIN_OPS, *_UNARY_OPS, *_CMP_OPS,
)


class ExpressionError(ValueError):
    pass


def parse(expr: str, allowed_names: Iterable[str]) -> ast.Expression:
    """Parse ``expr`` and reject anything outside the whitelist."""
    allowed = set(allowed_names)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"syntaxe invalide : {expr!r}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in allowed:
                raise ExpressionError(
                    f"nom inconnu {node.id!r} dans {expr!r} (autorisés : {', '.join(sorted(allowed))})"
                )
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ExpressionError(f"constante non numérique dans {expr!r}")
        elif not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"construction non autorisée ({type(node).__name__}) dans {expr!r}")
    return tree


def evaluate(expr: str, variables: Mapping[str, float]):
    """Evaluate ``expr`` with ``variables``. Raises ExpressionError on any unsupported construct."""
    tree = parse(expr, variables.keys())
    return _eval(tree.body, variables)


def _eval(node: ast.AST, env: Mapping[str, float]):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.BinOp):
        return _BIN_OPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp):
        return _UNARY_OPS[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, env) for v in node.values)
        return any(_eval(v, env) for v in node.values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, env)
            if not _CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ExpressionError(f"construction non autorisée : {type(node).__name__}")
