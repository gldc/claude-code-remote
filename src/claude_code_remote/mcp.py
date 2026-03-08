"""MCP server configuration management."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .models import MCPServer, MCPHealthResult

logger = logging.getLogger(__name__)

GLOBAL_MCP_CONFIG = Path.home() / ".claude" / ".mcp.json"


def _read_mcp_config(path: Path) -> dict[str, dict]:
    """Read mcpServers from a .mcp.json file."""
    try:
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("mcpServers", {})
    except Exception as e:
        logger.debug("Failed to read MCP config %s: %s", path, e)
    return {}


def _write_mcp_config(path: Path, servers: dict[str, dict]) -> None:
    """Write mcpServers to a .mcp.json file, preserving other keys."""
    try:
        existing = {}
        if path.exists():
            existing = json.loads(path.read_text())
        existing["mcpServers"] = servers
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2))
    except Exception as e:
        logger.error("Failed to write MCP config %s: %s", path, e)
        raise


def list_mcp_servers(project_dir: str | None = None) -> list[MCPServer]:
    """List all configured MCP servers (global + project)."""
    servers = []

    # Global servers
    global_servers = _read_mcp_config(GLOBAL_MCP_CONFIG)
    for name, cfg in global_servers.items():
        servers.append(
            MCPServer(
                name=name,
                type=cfg.get("type", "stdio"),
                command=cfg.get("command"),
                args=cfg.get("args", []),
                url=cfg.get("url"),
                env=cfg.get("env", {}),
                scope="global",
            )
        )

    # Project servers
    if project_dir:
        project_config = Path(project_dir) / ".mcp.json"
        project_servers = _read_mcp_config(project_config)
        for name, cfg in project_servers.items():
            servers.append(
                MCPServer(
                    name=name,
                    type=cfg.get("type", "stdio"),
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("url"),
                    env=cfg.get("env", {}),
                    scope="project",
                )
            )

    return servers


def add_mcp_server(server: MCPServer, project_dir: str | None = None) -> MCPServer:
    """Add or update an MCP server configuration."""
    if server.scope == "project" and project_dir:
        config_path = Path(project_dir) / ".mcp.json"
    else:
        config_path = GLOBAL_MCP_CONFIG

    servers = _read_mcp_config(config_path)
    cfg: dict = {"type": server.type}
    if server.command:
        cfg["command"] = server.command
    if server.args:
        cfg["args"] = server.args
    if server.url:
        cfg["url"] = server.url
    if server.env:
        cfg["env"] = server.env

    servers[server.name] = cfg
    _write_mcp_config(config_path, servers)
    return server


def remove_mcp_server(
    name: str, scope: str = "global", project_dir: str | None = None
) -> bool:
    """Remove an MCP server from config."""
    if scope == "project" and project_dir:
        config_path = Path(project_dir) / ".mcp.json"
    else:
        config_path = GLOBAL_MCP_CONFIG

    servers = _read_mcp_config(config_path)
    if name in servers:
        del servers[name]
        _write_mcp_config(config_path, servers)
        return True
    return False


async def check_mcp_health(server: MCPServer) -> MCPHealthResult:
    """Health check an MCP server by attempting to spawn/connect."""
    start = time.time()
    try:
        if server.type == "stdio" and server.command:
            proc = await asyncio.create_subprocess_exec(
                server.command,
                *server.args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
            latency = int((time.time() - start) * 1000)
            return MCPHealthResult(
                name=server.name,
                healthy=proc.returncode is not None,
                latency_ms=latency,
            )
        elif server.type == "sse" and server.url:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(server.url)
                latency = int((time.time() - start) * 1000)
                return MCPHealthResult(
                    name=server.name,
                    healthy=resp.status_code < 400,
                    latency_ms=latency,
                )
        return MCPHealthResult(
            name=server.name, healthy=False, error="No command or URL configured"
        )
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return MCPHealthResult(
            name=server.name, healthy=False, latency_ms=latency, error=str(e)
        )
