"""Pytest configuration for E2E scenario tests.

Provides fixtures for:
- Provider configuration (Ollama, Anthropic, etc.)
- Conversation helpers for multi-turn tests
- Rich logging and output formatting
"""

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest
import pytest_asyncio
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.markdown import Markdown

from app.llm.base_provider import BaseLLMProvider, Message
from app.llm.provider_factory import ProviderFactory
from app.mcp.registry import registry
from app.prompts import default_assembler


# ==================== Logging Setup ====================

console = Console(record=True)

def setup_rich_logging():
    """Configure rich logging for scenario tests."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )
    # Suppress noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


setup_rich_logging()
logger = logging.getLogger("e2e_scenarios")


# ==================== Data Classes ====================

@dataclass
class Turn:
    """A single conversation turn."""
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Response metadata
    task_detected: str | None = None
    tools_called: list[dict] = field(default_factory=list)
    response_time_ms: float = 0
    
    def to_message(self) -> Message:
        return Message(role=self.role, content=self.content)


@dataclass
class Scenario:
    """An E2E test scenario with conversation history."""
    name: str
    description: str
    turns: list[Turn] = field(default_factory=list)
    provider: str = "ollama"
    model: str = "llama3:latest"
    
    def add_user_turn(self, content: str) -> Turn:
        turn = Turn(role="user", content=content)
        self.turns.append(turn)
        return turn
    
    def add_assistant_turn(
        self,
        content: str,
        task_detected: str | None = None,
        tools_called: list[dict] | None = None,
        response_time_ms: float = 0,
    ) -> Turn:
        turn = Turn(
            role="assistant",
            content=content,
            task_detected=task_detected,
            tools_called=tools_called or [],
            response_time_ms=response_time_ms,
        )
        self.turns.append(turn)
        return turn
    
    def get_messages(self) -> list[Message]:
        """Get all turns as Message objects."""
        return [turn.to_message() for turn in self.turns]


@dataclass
class ScenarioResult:
    """Result of running a scenario."""
    scenario: Scenario
    success: bool
    error: str | None = None
    total_time_ms: float = 0
    system_prompt: str = ""
    

# ==================== Display Helpers ====================

def display_scenario_header(scenario: Scenario):
    """Display scenario header with rich formatting."""
    console.print()
    console.print(Panel(
        f"[bold cyan]{scenario.name}[/bold cyan]\n\n{scenario.description}",
        title="🎯 Scenario",
        subtitle=f"Provider: {scenario.provider} | Model: {scenario.model}",
    ))
    console.print()


def display_turn(turn: Turn, index: int):
    """Display a single conversation turn."""
    if turn.role == "user":
        console.print(Panel(
            turn.content,
            title=f"[bold blue]👤 User (Turn {index})[/bold blue]",
            border_style="blue",
        ))
    else:
        # Build metadata string
        meta_parts = []
        if turn.task_detected:
            meta_parts.append(f"Task: {turn.task_detected}")
        if turn.tools_called:
            tool_names = [t.get("tool", "?") for t in turn.tools_called]
            meta_parts.append(f"Tools: {', '.join(tool_names)}")
        if turn.response_time_ms:
            meta_parts.append(f"Time: {turn.response_time_ms:.0f}ms")
        
        meta_str = " | ".join(meta_parts) if meta_parts else ""
        
        console.print(Panel(
            Markdown(turn.content),
            title=f"[bold green]🤖 Assistant (Turn {index})[/bold green]",
            subtitle=meta_str if meta_str else None,
            border_style="green",
        ))


def display_system_prompt(prompt: str, show_full: bool = False):
    """Display the system prompt."""
    if show_full:
        console.print(Panel(
            Syntax(prompt, "markdown", theme="monokai", word_wrap=True),
            title="[bold yellow]📜 System Prompt[/bold yellow]",
            border_style="yellow",
        ))
    else:
        # Show summary
        lines = prompt.split("\n")
        preview = "\n".join(lines[:20])
        if len(lines) > 20:
            preview += f"\n... ({len(lines) - 20} more lines)"
        console.print(Panel(
            preview,
            title=f"[bold yellow]📜 System Prompt ({len(lines)} lines)[/bold yellow]",
            border_style="yellow",
        ))


def display_tool_call(tool_name: str, args: dict, result: Any, success: bool):
    """Display a tool call with result."""
    status = "[green]✓[/green]" if success else "[red]✗[/red]"
    
    table = Table(title=f"{status} Tool: {tool_name}")
    table.add_column("Arguments", style="cyan")
    table.add_column("Result", style="green" if success else "red")
    
    table.add_row(
        json.dumps(args, indent=2),
        json.dumps(result, indent=2) if isinstance(result, dict) else str(result),
    )
    
    console.print(table)


def display_scenario_summary(result: ScenarioResult):
    """Display final scenario summary."""
    status = "[green]✓ PASSED[/green]" if result.success else "[red]✗ FAILED[/red]"
    
    table = Table(title=f"Scenario Result: {status}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("Total Turns", str(len(result.scenario.turns)))
    table.add_row("Total Time", f"{result.total_time_ms:.0f}ms")
    
    total_tools = sum(len(t.tools_called) for t in result.scenario.turns)
    table.add_row("Tools Called", str(total_tools))
    
    if result.error:
        table.add_row("Error", f"[red]{result.error}[/red]")
    
    console.print(table)
    console.print()


# ==================== Fixtures ====================

@pytest.fixture(scope="session")
def provider_config() -> dict[str, Any]:
    """Get provider configuration from environment."""
    return {
        "ollama": {
            "model": os.getenv("E2E_OLLAMA_MODEL", "qwen2.5:7b-instruct-q5_K_M"),
            "base_url": os.getenv("E2E_OLLAMA_URL", "http://localhost:11434"),
        },
        "anthropic": {
            "model": os.getenv("E2E_ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
            "api_key": os.getenv("ANTHROPIC_API_KEY"),
        },
        "openai": {
            "model": os.getenv("E2E_OPENAI_MODEL", "gpt-3.5-turbo"),
            "api_key": os.getenv("OPENAI_API_KEY"),
        },
    }


@pytest.fixture
def scenario_runner(provider_config):
    """Create a scenario runner with configured provider."""
    return ScenarioRunner(provider_config)


class ScenarioRunner:
    """Helper class to run E2E scenarios with actual LLM calls."""
    
    def __init__(self, provider_config: dict[str, Any]):
        self.provider_config = provider_config
        self.assembler = default_assembler
        
    async def run_scenario(
        self,
        scenario: Scenario,
        show_prompts: bool = True,
        show_full_prompt: bool = False,
    ) -> ScenarioResult:
        """Run a complete scenario with all turns."""
        import time
        
        display_scenario_header(scenario)
        
        start_time = time.time()
        result = ScenarioResult(scenario=scenario, success=True)
        
        config = self.provider_config.get(scenario.provider, {})
        model = config.get("model", scenario.model)
        
        try:
            provider = ProviderFactory.create(
                scenario.provider,
                api_key=config.get("api_key"),
                base_url=config.get("base_url"),
            )
            
            async with provider:
                # Process user turns and get responses
                turn_index = 0
                while turn_index < len(scenario.turns):
                    turn = scenario.turns[turn_index]
                    
                    if turn.role == "user":
                        display_turn(turn, turn_index + 1)
                        
                        # Get all messages up to this point
                        history = scenario.get_messages()[:turn_index + 1]
                        
                        # Assemble system prompt
                        assembled = self.assembler.assemble(
                            tools=registry.list_tools(),
                        )
                        
                        if show_prompts and turn_index == 0:  # Show prompt on first turn
                            result.system_prompt = assembled.system_prompt
                            display_system_prompt(assembled.system_prompt, show_full_prompt)
                        
                        # Make LLM call
                        turn_start = time.time()
                        messages = [
                            Message(role="system", content=assembled.system_prompt),
                            *history,
                        ]
                        
                        response = await provider.chat(messages, model=model)
                        turn_time = (time.time() - turn_start) * 1000
                        
                        # Extract response text
                        response_text = self._extract_response_text(response, scenario.provider)
                        
                        # Add assistant turn
                        scenario.add_assistant_turn(
                            content=response_text,
                            task_detected=assembled.task,
                            response_time_ms=turn_time,
                        )
                        display_turn(scenario.turns[-1], turn_index + 2)
                        
                    turn_index += 1
                    
        except Exception as e:
            logger.error(f"Scenario failed: {e}")
            result.success = False
            result.error = str(e)
        
        result.total_time_ms = (time.time() - start_time) * 1000
        display_scenario_summary(result)
        
        return result
    
    def _extract_response_text(self, response: Any, provider: str) -> str:
        """Extract text from provider-specific response format."""
        if provider == "anthropic":
            if isinstance(response, dict):
                content = response.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
            return str(response)
        elif provider == "ollama":
            if isinstance(response, dict):
                return response.get("message", {}).get("content", "")
            return str(response)
        else:
            # Generic extraction
            if isinstance(response, dict):
                for key in ["content", "text", "message"]:
                    if key in response:
                        val = response[key]
                        if isinstance(val, str):
                            return val
                        if isinstance(val, list) and val:
                            return val[0].get("text", str(val[0]))
                        if isinstance(val, dict):
                            return val.get("content", val.get("text", str(val)))
            return str(response)
