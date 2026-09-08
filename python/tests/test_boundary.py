import ast
import re
from pathlib import Path


def test_shipped_rpc_method_set_and_no_execution_dependencies():
    root = Path(__file__).resolve().parents[1]
    source = root / "src" / "wallet_observer"
    tree = ast.parse((source / "evm.py").read_text())
    methods = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("eth_")
    }
    assert methods == {"eth_chainId", "eth_getBalance", "eth_call"}
    text = "\n".join(p.read_text() for p in source.glob("*.py"))
    assert not re.search(r"0x[0-9a-fA-F]{40}", text)
    assert "/Users/" not in text
    metadata = (root / "pyproject.toml").read_text()
    assert 'dependencies = ["httpx>=0.28.1,<1"]' in metadata
