"""calculator: safe AST evaluator — no names, attributes or arbitrary calls (docs/22 §11.1)."""

from __future__ import annotations

import ast
import json
import math
import operator
from decimal import Decimal, getcontext
from typing import Any

from pydantic import Field

from app.tools.base import Tool, ToolArgs, ToolContext, ToolError, ToolResult

getcontext().prec = 50
BIN: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UN: dict[type, Any] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "factorial": math.factorial,
}
CONSTS = {"pi": math.pi, "e": math.e}


def _num(v: Any) -> Any:
    return Decimal(str(v)) if isinstance(v, int | float) and not isinstance(v, bool) else v


def evaluate(expr: str) -> Any:
    tree = ast.parse(expr.replace("^", "**"), mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name) and node.id in CONSTS:
            return Decimal(str(CONSTS[node.id]))
        if isinstance(node, ast.BinOp) and type(node.op) in BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ToolError("INVALID_ARGUMENTS", "Exponent too large.")
            return BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in UN:
            return UN[type(node.op)](ev(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCS
            and not node.keywords
        ):
            args = [ev(a) for a in node.args]
            if node.func.id == "factorial" and (args[0] > 170 or args[0] < 0):
                raise ToolError("INVALID_ARGUMENTS", "factorial argument must be 0..170.")
            fn = FUNCS[node.func.id]
            if fn in (abs, round, min, max):
                return fn(*args)
            if fn is math.factorial:
                return Decimal(math.factorial(int(args[0])))
            return Decimal(str(fn(*[float(a) for a in args])))
        raise ToolError("INVALID_ARGUMENTS", "Only arithmetic and math functions are allowed.")

    try:
        result = ev(tree)
    except (ZeroDivisionError, ArithmeticError, ValueError, OverflowError) as e:
        raise ToolError("INVALID_ARGUMENTS", f"Math error: {e}") from e
    if abs(result) > Decimal("1e308"):
        raise ToolError("INVALID_ARGUMENTS", "Result too large.")
    return result.normalize() if isinstance(result, Decimal) else result


class CalculatorTool(Tool):
    name = "calculator"
    display_name = "Calculator"
    description = (
        "Evaluate an arithmetic expression exactly. Supports + - * / // % ** and "
        "sqrt, log, log10, log2, exp, sin, cos, tan, asin, acos, atan, floor, ceil, "
        "abs, round, min, max, factorial, pi, e."
    )
    timeout_seconds = 1.0

    class Args(ToolArgs):
        expression: str = Field(min_length=1, max_length=500)

    def label(self, args: Any) -> str:
        return f"Calculating {args.expression[:60]}"

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        try:
            value = evaluate(args.expression)
        except SyntaxError as e:
            raise ToolError("INVALID_ARGUMENTS", "That isn't a valid expression.") from e
        text = (
            format(value, "f") if isinstance(value, Decimal) and abs(value) < 10**15 else str(value)
        )
        return ToolResult(
            "succeeded",
            json.dumps({"expression": args.expression, "result": text}),
            f"{args.expression} = {text}",
            display={"expression": args.expression, "result": text},
        )
