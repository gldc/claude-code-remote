import pytest
import json
from pathlib import Path
from claude_code_remote.mcp import (
    _read_mcp_config,
    _write_mcp_config,
    list_mcp_servers,
    add_mcp_server,
    remove_mcp_server,
)
from claude_code_remote.models import MCPServer


def test_read_mcp_config_empty(tmp_path):
    result = _read_mcp_config(tmp_path / "nonexistent.json")
    assert result == {}


def test_read_mcp_config(tmp_path):
    config_file = tmp_path / ".mcp.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "test-server": {
                        "type": "stdio",
                        "command": "node",
                        "args": ["server.js"],
                    }
                }
            }
        )
    )
    result = _read_mcp_config(config_file)
    assert "test-server" in result
    assert result["test-server"]["command"] == "node"


def test_write_mcp_config(tmp_path):
    config_file = tmp_path / ".mcp.json"
    servers = {
        "my-server": {"type": "stdio", "command": "python", "args": ["-m", "server"]}
    }
    _write_mcp_config(config_file, servers)

    data = json.loads(config_file.read_text())
    assert "mcpServers" in data
    assert "my-server" in data["mcpServers"]


def test_write_preserves_other_keys(tmp_path):
    config_file = tmp_path / ".mcp.json"
    config_file.write_text(json.dumps({"version": 1, "mcpServers": {}}))
    _write_mcp_config(config_file, {"test": {"type": "stdio"}})

    data = json.loads(config_file.read_text())
    assert data["version"] == 1
    assert "test" in data["mcpServers"]


def test_add_and_remove_server(tmp_path, monkeypatch):
    config_file = tmp_path / ".mcp.json"
    monkeypatch.setattr("claude_code_remote.mcp.GLOBAL_MCP_CONFIG", config_file)

    server = MCPServer(name="test-srv", command="echo", args=["hello"])
    add_mcp_server(server)

    servers = list_mcp_servers()
    assert len(servers) == 1
    assert servers[0].name == "test-srv"

    assert remove_mcp_server("test-srv") is True
    servers = list_mcp_servers()
    assert len(servers) == 0


def test_remove_nonexistent(tmp_path, monkeypatch):
    config_file = tmp_path / ".mcp.json"
    monkeypatch.setattr("claude_code_remote.mcp.GLOBAL_MCP_CONFIG", config_file)
    assert remove_mcp_server("nope") is False
