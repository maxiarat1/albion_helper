"""MCP tool for sandboxed Python code execution.

Runs user-provided Python snippets in an isolated subprocess with
restricted builtins, pre-imported safe modules, and a hard timeout.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from typing import Any

from app.mcp.registry import Param, tool
from app.mcp.tool_templates import READ_ONLY_LOCAL

_MAX_TIMEOUT = 30
_DEFAULT_TIMEOUT = 5
_MAX_OUTPUT_CHARS = 50_000
_RESULT_DELIMITER = "__SANDBOX_RESULT_7f3a__"

# Builtins blocked in the sandbox (everything else is allowed).
_BLOCKED_BUILTINS = {
    "open",          # file I/O
    "exec",          # arbitrary code execution
    "eval",          # arbitrary code evaluation
    "compile",       # code compilation
    "breakpoint",    # debugger
    "input",         # stdin (would hang the subprocess)
    "exit",          # ungraceful termination
    "quit",          # ungraceful termination
}

# Modules pre-imported in the sandbox namespace.
_SAFE_MODULES = ["math", "statistics", "decimal", "collections", "json", "itertools", "functools"]


def _build_wrapper_script(user_code: str) -> str:
    """Build the Python script that runs inside the subprocess."""
    # Escape the user code for embedding in a triple-quoted string.
    # We use base64 to avoid any quoting issues.
    import base64

    code_b64 = base64.b64encode(user_code.encode()).decode()

    return textwrap.dedent(f"""\
        import ast as _ast, base64 as _b64, io as _io, json as _json, sys as _sys

        # Decode user code
        _user_code = _b64.b64decode("{code_b64}").decode()

        # Import safe modules before restricting builtins
        import math, statistics, decimal, collections, json, itertools, functools

        # Build restricted builtins: start with all, remove dangerous ones
        _blocked = {_BLOCKED_BUILTINS!r}
        _builtins_src = __builtins__ if isinstance(__builtins__, dict) else __builtins__.__dict__
        _original_import = _builtins_src["__import__"]
        _safe = {{k: v for k, v in _builtins_src.items() if k not in _blocked}}
        _allowed_imports = set({_SAFE_MODULES!r})

        def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                raise ImportError("relative imports are disabled in the sandbox")
            root = str(name).split(".", 1)[0]
            if root not in _allowed_imports:
                _allowed = ", ".join(sorted(_allowed_imports))
                raise ImportError(
                    f"module '{{name}}' is not allowed in sandbox; allowed imports: {{_allowed}}"
                )
            return _original_import(name, globals, locals, fromlist, level)

        _safe["__import__"] = _safe_import

        # Prepare namespace
        _ns = {{
            "__builtins__": _safe,
            "math": math,
            "statistics": statistics,
            "decimal": decimal,
            "collections": collections,
            "json": json,
            "itertools": itertools,
            "functools": functools,
        }}

        # Capture stdout
        _captured = _io.StringIO()
        _sys.stdout = _captured
        _sys.stderr = _captured

        _error = None
        _error_type = None
        _result = None

        try:
            # Parse once with AST so we can reliably evaluate the final expression.
            _module = _ast.parse(_user_code, filename="<code>", mode="exec")
            if _module.body and isinstance(_module.body[-1], _ast.Expr):
                _expr = _module.body.pop().value
                if _module.body:
                    _stmt_module = _ast.Module(body=_module.body, type_ignores=[])
                    exec(compile(_stmt_module, "<code>", "exec"), _ns)
                _expr_module = _ast.Expression(_expr)
                _result = eval(compile(_expr_module, "<code>", "eval"), _ns)
            else:
                exec(compile(_module, "<code>", "exec"), _ns)
        except Exception as _e:
            _error = f"{{type(_e).__name__}}: {{_e}}"
            _error_type = type(_e).__name__

        # Output delimiter + JSON result
        _sys.stdout = _sys.__stdout__
        _output = _captured.getvalue()
        _result_repr = repr(_result) if _result is not None else None
        _result_type = type(_result).__name__ if _result is not None else None
        print("{_RESULT_DELIMITER}")
        print(_json.dumps({{
            "output": _output[:50000],
            "result": _result_repr,
            "result_type": _result_type,
            "error": _error,
            "error_type": _error_type,
        }}))
    """)


def _build_observation(
    *,
    success: bool,
    output: str,
    result: str | None,
    result_type: str | None,
    error: str | None,
) -> str:
    """Create a concise execution summary for LLM reasoning."""
    if not success:
        return f"Execution failed with error: {error}"

    parts: list[str] = []
    if result is not None:
        type_prefix = f"{result_type} " if result_type else ""
        parts.append(f"Final expression produced {type_prefix}result {result}.")
    else:
        parts.append("No final expression result was produced.")

    if output:
        first_line = output.splitlines()[0].strip()
        parts.append(f"Printed output is available (first line: {first_line!r}).")
    else:
        parts.append("No printed output.")

    return " ".join(parts)


@tool(
    name="execute_code",
    description=(
        "Execute Python code for calculations and data analysis. "
        "Use for math, statistics, comparisons, and formatting that "
        "benefit from precise computation. Safe modules are pre-imported and "
        "also importable: math, statistics, decimal, collections, json, "
        "itertools, functools. "
        "No file I/O or network access."
    ),
    params=[
        Param("code", "string", "Python code to execute. Use print() for output. "
              "The result of the last expression is also captured.", required=True, min_length=1),
        Param("timeout", "integer", "Max execution time in seconds (default: 5, max: 30).", minimum=1, maximum=_MAX_TIMEOUT),
    ],
    annotations=READ_ONLY_LOCAL,
    output_schema={
        "type": "object",
        "required": ["success", "output", "result", "result_type", "error", "observation"],
        "additionalProperties": False,
        "properties": {
            "success": {"type": "boolean"},
            "output": {"type": "string"},
            "result": {"type": ["string", "null"]},
            "result_type": {"type": ["string", "null"]},
            "error": {"type": ["string", "null"]},
            "observation": {"type": "string"},
        },
    },
)
async def execute_code(args: dict[str, Any]) -> dict[str, Any]:
    """Execute Python code in a sandboxed subprocess."""
    code = args["code"]
    timeout = max(1, min(args.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

    if not code.strip():
        return {"success": False, "output": "", "result": None, "error": "No code provided"}

    wrapper = _build_wrapper_script(code)

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", wrapper,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return {
            "success": False,
            "output": "",
            "result": None,
            "error": f"Execution timed out after {timeout}s",
        }
    except Exception as exc:
        return {
            "success": False,
            "output": "",
            "result": None,
            "error": f"Failed to run subprocess: {exc}",
        }

    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")

    # Parse the delimiter-separated output
    if _RESULT_DELIMITER in raw_stdout:
        parts = raw_stdout.split(_RESULT_DELIMITER, 1)
        user_output = parts[0]
        try:
            result_data = json.loads(parts[1].strip())
            output = result_data.get("output", user_output)
            result_val = result_data.get("result")
            result_type = result_data.get("result_type")
            error = result_data.get("error")
        except (json.JSONDecodeError, IndexError):
            output = user_output
            result_val = None
            result_type = None
            error = None
    else:
        # Subprocess crashed or didn't reach the delimiter
        output = raw_stdout
        result_val = None
        result_type = None
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        error = stderr_text if stderr_text else "Execution failed (no result produced)"

    # Truncate output if needed
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS] + f"\n... (truncated at {_MAX_OUTPUT_CHARS} chars)"

    success = error is None
    return {
        "success": success,
        "output": output.rstrip("\n") if output else "",
        "result": result_val,
        "result_type": result_type,
        "error": error,
        "observation": _build_observation(
            success=success,
            output=output.rstrip("\n") if output else "",
            result=result_val,
            result_type=result_type,
            error=error,
        ),
    }
