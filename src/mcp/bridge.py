"""MCP Tool Bridge - Python to TypeScript MCP server communication.

The key innovation: spawn TypeScript MCP servers as subprocesses and
communicate via stdio JSON-RPC. Same persona works both interactively
(Claude Desktop) and in pipeline mode (Python orchestrator).
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MCPToolResult:
    """Result from an MCP tool call."""

    success: bool
    content: Any = None
    error: str | None = None


class MCPToolBridge:
    """Bridge for Python to call TypeScript MCP server tools.

    Usage:
        async with MCPToolBridge("/path/to/mcp-server") as bridge:
            result = await bridge.call_tool("analyze_decision", {"scenario": "..."})
    """

    def __init__(self, mcp_path: str | Path, node_command: str = "node") -> None:
        """Initialize the bridge.

        Args:
            mcp_path: Path to the MCP server directory (must have dist/index.js)
            node_command: Node.js command to use (default: "node")
        """
        self.mcp_path = Path(mcp_path)
        self.node_command = node_command
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "MCPToolBridge":
        """Start the MCP server process and initialize."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Shut down the MCP server process."""
        await self.stop()

    async def start(self) -> None:
        """Start the MCP server subprocess."""
        index_path = self.mcp_path / "dist" / "index.js"
        if not index_path.exists():
            raise FileNotFoundError(
                f"MCP server not built: {index_path}. Run 'npm run build' in {self.mcp_path}"
            )

        logger.info(f"Starting MCP server: {self.mcp_path}")

        self.process = await asyncio.create_subprocess_exec(
            self.node_command,
            str(index_path),
            cwd=str(self.mcp_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Initialize the MCP connection
        await self._initialize()
        logger.info(f"MCP server started: {self.mcp_path.name}")

    async def stop(self) -> None:
        """Stop the MCP server subprocess."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            finally:
                self.process = None
                logger.info("MCP server stopped")

    async def _initialize(self) -> dict[str, Any]:
        """Send MCP initialize request."""
        return await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "idea-factory", "version": "0.1.0"},
            },
        )

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        response = await self._send_request("tools/list", {})
        return response.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPToolResult:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            MCPToolResult with success status and content or error
        """
        try:
            response = await self._send_request(
                "tools/call", {"name": tool_name, "arguments": arguments}
            )

            # Parse the response content
            content = response.get("content", [])
            if content and len(content) > 0:
                # MCP returns content as array of content blocks
                text_content = next(
                    (c.get("text") for c in content if c.get("type") == "text"), None
                )
                if text_content:
                    # Try to parse as JSON if it looks like JSON
                    if text_content.strip().startswith("{"):
                        try:
                            return MCPToolResult(success=True, content=json.loads(text_content))
                        except json.JSONDecodeError:
                            pass
                    return MCPToolResult(success=True, content=text_content)

            return MCPToolResult(success=True, content=content)

        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return MCPToolResult(success=False, error=str(e))

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP server not running")

        async with self._lock:
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params,
            }

            # Send request
            request_bytes = json.dumps(request).encode() + b"\n"
            self.process.stdin.write(request_bytes)
            await self.process.stdin.drain()

            # Read response (MCP uses newline-delimited JSON)
            response_line = await asyncio.wait_for(
                self.process.stdout.readline(), timeout=30.0
            )

            if not response_line:
                raise RuntimeError("No response from MCP server")

            response = json.loads(response_line.decode())

            # Check for errors
            if "error" in response:
                error = response["error"]
                raise RuntimeError(f"MCP error: {error.get('message', error)}")

            return response.get("result", {})


# Pre-configured bridges for known MCP servers
CHRISTENSEN_MCP_PATH = Path.home() / "projects" / "christensen-mcp"


async def get_christensen_bridge() -> MCPToolBridge:
    """Get a bridge to the Christensen MCP server."""
    bridge = MCPToolBridge(CHRISTENSEN_MCP_PATH)
    await bridge.start()
    return bridge


# Context manager for convenient usage
class ChristensenAnalyzer:
    """Convenience wrapper for Christensen MCP analysis.

    Usage:
        async with ChristensenAnalyzer() as analyzer:
            result = await analyzer.analyze_decision("Should we build X?")
    """

    def __init__(self) -> None:
        self.bridge: MCPToolBridge | None = None

    async def __aenter__(self) -> "ChristensenAnalyzer":
        self.bridge = MCPToolBridge(CHRISTENSEN_MCP_PATH)
        await self.bridge.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.bridge:
            await self.bridge.stop()

    async def analyze_decision(
        self,
        scenario: str,
        context: str | None = None,
        constraints: list[str] | None = None,
    ) -> MCPToolResult:
        """Analyze a decision using Christensen frameworks.

        Args:
            scenario: The decision scenario to analyze
            context: Optional additional context
            constraints: Optional list of constraints

        Returns:
            MCPToolResult with Christensen analysis
        """
        if not self.bridge:
            raise RuntimeError("Analyzer not started")

        arguments: dict[str, Any] = {"decision": scenario}  # MCP expects "decision"
        if context:
            arguments["context"] = context
        # Note: constraints not supported by Christensen MCP, use context instead
        if constraints:
            arguments["context"] = (
                f"{context}\n\nConstraints/Tags: {', '.join(constraints)}"
                if context
                else f"Constraints/Tags: {', '.join(constraints)}"
            )

        return await self.bridge.call_tool("analyze_decision", arguments)

    async def evaluate_disruption(
        self,
        idea: str,
        market: str,
        incumbents: list[str] | None = None,
    ) -> MCPToolResult:
        """Evaluate disruption potential of an idea.

        Args:
            idea: The idea to evaluate
            market: Target market
            incumbents: Optional list of incumbent players

        Returns:
            MCPToolResult with disruption analysis
        """
        if not self.bridge:
            raise RuntimeError("Analyzer not started")

        arguments: dict[str, Any] = {"idea": idea, "market": market}
        if incumbents:
            arguments["incumbents"] = incumbents

        return await self.bridge.call_tool("evaluate_disruption", arguments)
