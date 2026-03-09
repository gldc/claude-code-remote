"""MCP server configuration management."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .models import MCPServer, MCPHealthResult

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"
GLOBAL_MCP_CONFIG = CLAUDE_DIR / ".mcp.json"
SETTINGS_PATH = CLAUDE_DIR / "settings.json"
INSTALLED_PLUGINS_PATH = CLAUDE_DIR / "plugins" / "installed_plugins.json"
USER_CONFIG_PATH = Path.home() / ".claude.json"


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


def _read_plugin_mcp_config(path: Path) -> dict[str, dict]:
    """Read plugin .mcp.json which uses flat structure (no mcpServers wrapper)."""
    try:
        if path.exists():
            data = json.loads(path.read_text())
            # Plugin .mcp.json is flat: { "server_name": { "command": ..., "args": [...] } }
            # Unlike global/project .mcp.json which wraps in { "mcpServers": { ... } }
            if "mcpServers" in data:
                return data["mcpServers"]
            return data
    except Exception as e:
        logger.debug("Failed to read plugin MCP config %s: %s", path, e)
    return {}


def _make_server(name: str, cfg: dict, scope: str) -> MCPServer:
    """Create an MCPServer from a config dict."""
    return MCPServer(
        name=name,
        type=cfg.get("type", "stdio"),
        command=cfg.get("command"),
        args=cfg.get("args", []),
        url=cfg.get("url"),
        env=cfg.get("env", {}),
        scope=scope,
    )


def _discover_user_config_servers(
    project_dir: str | None = None,
) -> list[MCPServer]:
    """Discover MCP servers from ~/.claude.json (user-level and per-project)."""
    servers = []
    try:
        if not USER_CONFIG_PATH.exists():
            return servers
        data = json.loads(USER_CONFIG_PATH.read_text())

        # User-level mcpServers (top-level key)
        for name, cfg in data.get("mcpServers", {}).items():
            servers.append(_make_server(name, cfg, "user"))

        # Per-project mcpServers (inside projects[project_dir].mcpServers)
        if project_dir:
            projects = data.get("projects", {})
            project_cfg = projects.get(project_dir, {})
            for name, cfg in project_cfg.get("mcpServers", {}).items():
                servers.append(_make_server(name, cfg, "local"))
    except Exception as e:
        logger.debug("Failed to discover user config MCP servers: %s", e)
    return servers


def _discover_plugin_servers() -> list[MCPServer]:
    """Discover MCP servers provided by enabled Claude Code plugins."""
    servers = []
    try:
        settings = (
            json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
        )
        enabled = settings.get("enabledPlugins", {})

        installed = (
            json.loads(INSTALLED_PLUGINS_PATH.read_text())
            if INSTALLED_PLUGINS_PATH.exists()
            else {}
        )
        plugins = installed.get("plugins", {})

        for plugin_id in enabled:
            entries = plugins.get(plugin_id, [])
            if not entries:
                continue
            install_path = entries[0].get("installPath")
            if not install_path:
                continue
            mcp_path = Path(install_path) / ".mcp.json"
            # Plugin .mcp.json uses flat structure (no mcpServers wrapper)
            for name, cfg in _read_plugin_mcp_config(mcp_path).items():
                servers.append(
                    MCPServer(
                        name=name,
                        type=cfg.get("type", "stdio"),
                        command=cfg.get("command"),
                        args=cfg.get("args", []),
                        url=cfg.get("url"),
                        env=cfg.get("env", {}),
                        scope="plugin",
                    )
                )
    except Exception as e:
        logger.debug("Failed to discover plugin MCP servers: %s", e)
    return servers


def list_mcp_servers(project_dir: str | None = None) -> list[MCPServer]:
    """List all configured MCP servers from all sources."""
    servers = []

    # Global servers (.mcp.json)
    for name, cfg in _read_mcp_config(GLOBAL_MCP_CONFIG).items():
        servers.append(_make_server(name, cfg, "global"))

    # Project servers ({project_dir}/.mcp.json)
    if project_dir:
        project_config = Path(project_dir) / ".mcp.json"
        for name, cfg in _read_mcp_config(project_config).items():
            servers.append(_make_server(name, cfg, "project"))

    # User + per-project servers from ~/.claude.json
    servers.extend(_discover_user_config_servers(project_dir))

    # Plugin servers
    servers.extend(_discover_plugin_servers())

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
