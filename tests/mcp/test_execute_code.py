"""Tests for the sandboxed execute_code MCP tool."""

import asyncio

import pytest

from app.mcp.tools.execute_code import execute_code


@pytest.fixture
def run():
    """Helper to run the async tool."""

    def _run(code: str, **kwargs):
        args = {"code": code, **kwargs}
        return asyncio.run(execute_code(args))

    return _run


class TestBasicExecution:
    def test_simple_arithmetic(self, run):
        result = run("2 + 2")
        assert result["success"] is True
        assert result["result"] == "4"
        assert result["result_type"] == "int"
        assert "Final expression produced" in result["observation"]
        assert result["error"] is None

    def test_print_output(self, run):
        result = run("print('hello world')")
        assert result["success"] is True
        assert "hello world" in result["output"]

    def test_multiline_code(self, run):
        code = "x = 10\ny = 20\nprint(x + y)"
        result = run(code)
        assert result["success"] is True
        assert "30" in result["output"]

    def test_last_expression_captured(self, run):
        code = "x = 5\ny = 3\nx * y"
        result = run(code)
        assert result["success"] is True
        assert result["result"] == "15"

    def test_variable_assignment_no_result(self, run):
        code = "x = 42"
        result = run(code)
        assert result["success"] is True
        # Assignment doesn't produce a result value
        assert result["result"] is None

    def test_empty_code(self, run):
        result = run("")
        assert result["success"] is False
        assert "No code" in result["error"]

    def test_whitespace_only_code(self, run):
        result = run("   \n  ")
        assert result["success"] is False
        assert "No code" in result["error"]


class TestPreImportedModules:
    def test_import_math_allowed(self, run):
        result = run("import math\nmath.factorial(6)")
        assert result["success"] is True
        assert result["result"] == "720"

    def test_from_import_decimal_allowed(self, run):
        result = run("from decimal import Decimal\nDecimal('1.2') + Decimal('0.3')")
        assert result["success"] is True
        assert result["result"] == "Decimal('1.5')"

    def test_math_sqrt(self, run):
        result = run("math.sqrt(144)")
        assert result["success"] is True
        assert result["result"] == "12.0"

    def test_math_pi(self, run):
        result = run("round(math.pi, 4)")
        assert result["success"] is True
        assert result["result"] == "3.1416"

    def test_statistics_mean(self, run):
        result = run("statistics.mean([10, 20, 30])")
        assert result["success"] is True
        assert result["result"] == "20"

    def test_statistics_median(self, run):
        result = run("statistics.median([1, 3, 5, 7, 9])")
        assert result["success"] is True
        assert result["result"] == "5"

    def test_decimal_precision(self, run):
        code = "decimal.Decimal('0.1') + decimal.Decimal('0.2')"
        result = run(code)
        assert result["success"] is True
        assert "0.3" in result["result"]

    def test_collections_counter(self, run):
        code = "dict(collections.Counter(['a', 'b', 'a', 'c', 'a']))"
        result = run(code)
        assert result["success"] is True
        assert "'a': 3" in result["result"]

    def test_json_dumps(self, run):
        code = 'print(json.dumps({"key": "value"}))'
        result = run(code)
        assert result["success"] is True
        assert '"key"' in result["output"]

    def test_itertools(self, run):
        code = "list(itertools.chain([1, 2], [3, 4]))"
        result = run(code)
        assert result["success"] is True
        assert result["result"] == "[1, 2, 3, 4]"


class TestSandboxSecurity:
    def test_import_os_blocked(self, run):
        result = run("import os")
        assert result["success"] is False
        assert "not allowed" in result["error"].lower()

    def test_import_subprocess_blocked(self, run):
        result = run("import subprocess")
        assert result["success"] is False
        assert "import" in result["error"].lower()

    def test_import_socket_blocked(self, run):
        result = run("import socket")
        assert result["success"] is False
        assert "import" in result["error"].lower()

    def test_dunder_import_blocked(self, run):
        result = run("__import__('os')")
        assert result["success"] is False
        assert "import" in result["error"].lower()

    def test_open_blocked(self, run):
        result = run("open('/etc/passwd')")
        assert result["success"] is False
        assert result["error"] is not None

    def test_exec_blocked(self, run):
        result = run("exec('print(1)')")
        assert result["success"] is False
        assert result["error"] is not None

    def test_eval_blocked(self, run):
        result = run("eval('1+1')")
        assert result["success"] is False
        assert result["error"] is not None

    def test_compile_blocked(self, run):
        result = run("compile('1', '', 'eval')")
        assert result["success"] is False
        assert result["error"] is not None

    def test_breakpoint_blocked(self, run):
        result = run("breakpoint()")
        assert result["success"] is False
        assert result["error"] is not None


class TestRelaxedBuiltins:
    """Verify builtins that should be available in the relaxed sandbox."""

    def test_getattr_setattr(self, run):
        code = "class Foo: pass\nf = Foo()\nsetattr(f, 'x', 42)\ngetattr(f, 'x')"
        result = run(code)
        assert result["success"] is True
        assert result["result"] == "42"

    def test_hasattr(self, run):
        result = run("hasattr([], 'append')")
        assert result["success"] is True
        assert result["result"] == "True"

    def test_dir(self, run):
        result = run("'append' in dir([])")
        assert result["success"] is True
        assert result["result"] == "True"

    def test_chr_ord(self, run):
        result = run("chr(65)")
        assert result["success"] is True
        assert result["result"] == "'A'"

    def test_hex_oct_bin(self, run):
        result = run("hex(255)")
        assert result["success"] is True
        assert result["result"] == "'0xff'"

    def test_isinstance_issubclass(self, run):
        result = run("issubclass(bool, int)")
        assert result["success"] is True
        assert result["result"] == "True"

    def test_frozenset(self, run):
        result = run("frozenset({1, 2, 3})")
        assert result["success"] is True
        assert "frozenset" in result["result"]

    def test_complex_numbers(self, run):
        result = run("complex(3, 4)")
        assert result["success"] is True
        assert result["result"] == "(3+4j)"

    def test_bytes(self, run):
        result = run("bytes([72, 101, 108, 108, 111])")
        assert result["success"] is True
        assert "Hello" in result["result"]

    def test_format(self, run):
        result = run("format(1234567, ',')")
        assert result["success"] is True
        assert result["result"] == "'1,234,567'"

    def test_property_and_classmethod(self, run):
        code = """\
class Item:
    def __init__(self, name, price):
        self.name = name
        self._price = price
    @property
    def price(self):
        return self._price
i = Item("Sword", 5000)
i.price
"""
        result = run(code)
        assert result["success"] is True
        assert result["result"] == "5000"

    def test_list_comprehension(self, run):
        result = run("[x**2 for x in range(5)]")
        assert result["success"] is True
        assert result["result"] == "[0, 1, 4, 9, 16]"

    def test_dict_comprehension(self, run):
        result = run("{k: v for k, v in enumerate('abc')}")
        assert result["success"] is True
        assert "0: 'a'" in result["result"]


class TestTimeout:
    def test_infinite_loop_timeout(self, run):
        result = run("while True: pass", timeout=2)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_timeout_clamped_to_max(self, run):
        # timeout=100 should be clamped to 30
        result = run("1 + 1", timeout=100)
        assert result["success"] is True


class TestErrorHandling:
    def test_syntax_error(self, run):
        result = run("def foo(")
        assert result["success"] is False
        assert "SyntaxError" in result["error"]

    def test_name_error(self, run):
        result = run("undefined_var")
        assert result["success"] is False
        assert "NameError" in result["error"]

    def test_zero_division(self, run):
        result = run("1 / 0")
        assert result["success"] is False
        assert "ZeroDivisionError" in result["error"]

    def test_type_error(self, run):
        result = run("'hello' + 5")
        assert result["success"] is False
        assert "TypeError" in result["error"]


class TestRealisticUseCases:
    def test_crafting_profit(self, run):
        code = """\
materials = 4500 * 16
return_rate = 0.369
effective_cost = materials * (1 - return_rate)
sell_price = 85000
tax = sell_price * 0.04
profit = sell_price - effective_cost - tax
print(f"Material cost: {materials:,}")
print(f"Effective cost (after returns): {effective_cost:,.0f}")
print(f"Tax (4%): {tax:,.0f}")
print(f"Profit: {profit:,.0f}")
profit
"""
        result = run(code)
        assert result["success"] is True
        assert "Material cost: 72,000" in result["output"]
        assert "Profit:" in result["output"]
        assert result["result"] is not None

    def test_ip_scaling(self, run):
        code = """\
base_stat = 100
ip = 1200
progression = 1.005
scaled = base_stat * (progression ** (ip / 100))
print(f"Base: {base_stat}")
print(f"At IP {ip}: {scaled:.2f}")
round(scaled, 2)
"""
        result = run(code)
        assert result["success"] is True
        assert "At IP 1200:" in result["output"]

    def test_arbitrage_comparison(self, run):
        code = """\
buy_price = 3200
sell_price = 4800
tax_rate = 0.065
setup_fee = 0.025

net_sell = sell_price * (1 - tax_rate - setup_fee)
profit = net_sell - buy_price
roi = (profit / buy_price) * 100

print(f"Buy: {buy_price:,}")
print(f"Sell: {sell_price:,}")
print(f"Net after fees: {net_sell:,.0f}")
print(f"Profit per item: {profit:,.0f}")
print(f"ROI: {roi:.1f}%")
"""
        result = run(code)
        assert result["success"] is True
        assert "ROI:" in result["output"]
        assert "Profit per item:" in result["output"]

    def test_price_statistics(self, run):
        code = """\
prices = [3200, 3400, 3100, 3500, 3300, 8900, 3250]
avg = statistics.mean(prices)
med = statistics.median(prices)
stdev = statistics.stdev(prices)
print(f"Mean: {avg:.0f}")
print(f"Median: {med}")
print(f"Std Dev: {stdev:.0f}")
"""
        result = run(code)
        assert result["success"] is True
        assert "Mean:" in result["output"]
        assert "Median:" in result["output"]
