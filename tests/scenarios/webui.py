"""Simple Web UI for E2E Scenario Testing.

A lightweight FastAPI application to run and visualize scenario tests
with an interactive interface instead of CLI output.

Run with:
    cd tests/scenarios && python webui.py
    
Then open http://localhost:8765
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.llm.provider_factory import ProviderFactory
from app.llm.base_provider import Message
from app.mcp.registry import registry
from app.prompts import default_assembler


app = FastAPI(title="Albion Helper E2E Scenarios")


# ==================== Data Models ====================

@dataclass
class ScenarioDefinition:
    """A scenario that can be run."""
    id: str
    name: str
    description: str
    category: str
    initial_message: str
    follow_ups: list[str] = field(default_factory=list)


@dataclass
class TurnResult:
    """Result of a single conversation turn."""
    role: str
    content: str
    time_ms: float = 0
    tools_called: list[dict] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)  # ReAct reasoning chain


@dataclass
class ScenarioResult:
    """Result of running a scenario."""
    scenario_id: str
    provider: str
    model: str
    turns: list[TurnResult] = field(default_factory=list)
    system_prompt: str = ""
    total_time_ms: float = 0
    success: bool = True
    error: str | None = None


# ==================== Scenario Definitions ====================

SCENARIOS = [
    # Market Queries
    ScenarioDefinition(
        id="simple_price",
        name="Simple Price Query",
        description="Ask for the price of a single item",
        category="Market",
        initial_message="What's the current price of T4 leather in Caerleon?",
    ),
    ScenarioDefinition(
        id="city_comparison",
        name="City Price Comparison",
        description="Compare prices across different cities",
        category="Market",
        initial_message="Which city has the cheapest T5 Crossbow?",
    ),
    ScenarioDefinition(
        id="trading_tips",
        name="Trading Opportunities",
        description="Ask about profitable trading",
        category="Market",
        initial_message="What items have good profit margins for flipping?",
    ),
    ScenarioDefinition(
        id="craft_and_price",
        name="Crafting + Price (Multi-Tool)",
        description="Ask about crafting materials AND prices in one query",
        category="Market",
        initial_message="I want to craft T5 leather. What materials do I need and what's the current price of T5 leather in Caerleon?",
    ),
    ScenarioDefinition(
        id="profit_analysis",
        name="Profit Analysis (Multi-Tool)",
        description="Compare crafting cost vs selling price",
        category="Market",
        initial_message="Is it profitable to craft and sell T6 Bags? Show me the material costs and selling prices.",
    ),
    
    # Multi-Turn
    ScenarioDefinition(
        id="price_followup",
        name="Price → Crafting Follow-up",
        description="Ask about price, then follow up about crafting",
        category="Multi-Turn",
        initial_message="What's the price of T6 leather?",
        follow_ups=["What materials do I need to craft T6 leather?"],
    ),
    ScenarioDefinition(
        id="clarification",
        name="Clarification Conversation",
        description="Ask ambiguous question, then clarify",
        category="Multi-Turn",
        initial_message="What's the price of a bag?",
        follow_ups=["I meant a T5 bag"],
    ),
    
    # General Chat
    ScenarioDefinition(
        id="greeting",
        name="New Player Greeting",
        description="Greet as a new player",
        category="General",
        initial_message="Hello! I'm new to Albion Online.",
    ),
    ScenarioDefinition(
        id="game_knowledge",
        name="Game Mechanics Question",
        description="Ask about game mechanics",
        category="General",
        initial_message="What's the difference between gathering and refining?",
    ),
    ScenarioDefinition(
        id="off_topic",
        name="Off-Topic Question",
        description="Ask something unrelated to the game",
        category="General",
        initial_message="What's the capital of France?",
    ),
    
    # Edge Cases
    ScenarioDefinition(
        id="typo_handling",
        name="Typo Tolerance",
        description="Ask with typos in item name",
        category="Edge Cases",
        initial_message="What's the price of t4 lether?",
    ),
    ScenarioDefinition(
        id="detailed_question",
        name="Detailed Question",
        description="Ask a long, detailed question",
        category="Edge Cases",
        initial_message="I'm a new player trying to figure out the best way to make silver. I've been gathering T4 resources but heard prices are better elsewhere. Should I focus on gathering, crafting, or trading?",
    ),
]


# ==================== Provider Config ====================

def get_available_providers() -> dict[str, dict]:
    """Get available providers with their models."""
    providers = {
        "ollama": {
            "available": True,
            "models": [],
            "default": os.getenv("E2E_OLLAMA_MODEL", "qwen2.5:7b-instruct-q5_K_M"),
        },
        "anthropic": {
            "available": bool(os.getenv("ANTHROPIC_API_KEY")),
            "models": ["claude-3-haiku-20240307", "claude-3-sonnet-20240229"],
            "default": os.getenv("E2E_ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
        },
    }
    
    # Try to get Ollama models
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            providers["ollama"]["models"] = [m["name"] for m in data.get("models", [])]
    except:
        providers["ollama"]["available"] = False
    
    return providers


# ==================== Scenario Runner ====================

from app.mcp.protocol import extract_tool_call, format_tool_result

MAX_TOOL_CALLS = 15


async def _execute_tool(tool_name: str, args: dict) -> tuple[Any, bool]:
    """Execute a tool and return (result, success)."""
    tool = registry.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}, False

    try:
        result = await tool.handler(args)
        return result, True
    except Exception as e:
        return {"error": str(e)}, False


async def run_scenario(
    scenario: ScenarioDefinition,
    provider_name: str,
    model: str,
) -> ScenarioResult:
    """Run a single scenario with unified tool loop."""
    import time

    result = ScenarioResult(
        scenario_id=scenario.id,
        provider=provider_name,
        model=model,
    )

    start_time = time.time()

    try:
        api_key = os.getenv("ANTHROPIC_API_KEY") if provider_name == "anthropic" else None
        provider = ProviderFactory.create(provider_name, api_key=api_key)

        async with provider:
            conversation: list[Message] = []
            all_messages = [scenario.initial_message] + scenario.follow_ups

            for i, user_msg in enumerate(all_messages):
                result.turns.append(TurnResult(role="user", content=user_msg))
                conversation.append(Message(role="user", content=user_msg))

                assembled = default_assembler.assemble(
                    tools=registry.list_tools(),
                )
                if i == 0:
                    result.system_prompt = assembled.system_prompt

                allowed_tools = {t["name"] for t in registry.list_tools()}
                tools_called: list[dict] = []
                tool_context: list[str] = []
                response_text: str | None = None

                turn_start = time.time()

                # Unified tool loop
                for _iteration in range(MAX_TOOL_CALLS):
                    messages = [
                        Message(role="system", content=assembled.system_prompt),
                        *conversation,
                    ]
                    for ctx in tool_context:
                        messages.append(Message(role="system", content=ctx))

                    raw_response = await provider.chat(messages, model=model)
                    text = _extract_response(raw_response, provider_name)
                    call = extract_tool_call(text)

                    if not call.wants_tool:
                        response_text = text
                        break

                    tool_name = call.tool or ""
                    if tool_name not in allowed_tools:
                        tool_context.append(f"Unknown tool: {tool_name}")
                        continue

                    tool_result, success = await _execute_tool(tool_name, call.arguments)
                    tools_called.append({
                        "tool": tool_name,
                        "arguments": call.arguments,
                        "result": tool_result,
                        "success": success,
                    })
                    tool_context.append(format_tool_result(tool_name, tool_result, success=success))

                # If loop exhausted without text, make a final response call
                if response_text is None:
                    messages = [
                        Message(role="system", content=assembled.system_prompt),
                        *conversation,
                    ]
                    for ctx in tool_context:
                        messages.append(Message(role="system", content=ctx))
                    messages.append(Message(
                        role="system",
                        content="Now respond to the user based on the tool results above.",
                    ))
                    raw_response = await provider.chat(messages, model=model)
                    response_text = _extract_response(raw_response, provider_name)

                turn_time = (time.time() - turn_start) * 1000

                result.turns.append(TurnResult(
                    role="assistant",
                    content=response_text,
                    time_ms=turn_time,
                    tools_called=tools_called,
                ))
                conversation.append(Message(role="assistant", content=response_text))

    except Exception as e:
        result.success = False
        result.error = str(e)
        import traceback
        traceback.print_exc()

    result.total_time_ms = (time.time() - start_time) * 1000
    return result


def _extract_response(response: Any, provider: str) -> str:
    """Extract text from provider response."""
    if provider == "anthropic":
        if isinstance(response, dict):
            content = response.get("content", [])
            if content and isinstance(content, list):
                return content[0].get("text", "")
    elif provider == "ollama":
        if isinstance(response, dict):
            return response.get("message", {}).get("content", "")
    return str(response)


# ==================== API Routes ====================

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI."""
    return HTML_TEMPLATE


@app.get("/api/scenarios")
async def list_scenarios():
    """List all available scenarios."""
    return [asdict(s) for s in SCENARIOS]


@app.get("/api/providers")
async def list_providers():
    """List available providers and models."""
    return get_available_providers()


@app.post("/api/run")
async def run_scenario_endpoint(request: Request):
    """Run a scenario."""
    data = await request.json()
    scenario_id = data.get("scenario_id")
    provider = data.get("provider", "ollama")
    model = data.get("model")
    
    # Find scenario
    scenario = next((s for s in SCENARIOS if s.id == scenario_id), None)
    if not scenario:
        return JSONResponse({"error": "Scenario not found"}, status_code=404)
    
    # Run it
    result = await run_scenario(scenario, provider, model)
    return asdict(result)


# ==================== HTML Template ====================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Albion Helper - E2E Scenarios</title>
    <style>
        :root {
            --bg: #0d1117;
            --surface: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-dim: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --error: #f85149;
            --user: #1f6feb;
            --assistant: #238636;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
        }
        
        h1 { color: var(--accent); font-size: 1.5rem; }
        
        .layout {
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 20px;
        }
        
        .panel {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
        }
        
        .panel h2 {
            font-size: 0.9rem;
            color: var(--text-dim);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 16px;
        }
        
        .config-row {
            margin-bottom: 12px;
        }
        
        .config-row label {
            display: block;
            font-size: 0.85rem;
            color: var(--text-dim);
            margin-bottom: 4px;
        }
        
        select, input {
            width: 100%;
            padding: 8px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            color: var(--text);
            border-radius: 4px;
            font-size: 0.9rem;
        }
        
        .scenario-list {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .scenario-item {
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 8px;
            cursor: pointer;
            transition: all 0.15s;
        }
        
        .scenario-item:hover { border-color: var(--accent); }
        .scenario-item.selected { border-color: var(--accent); background: rgba(88, 166, 255, 0.1); }
        
        .scenario-item .name { font-weight: 600; }
        .scenario-item .desc { font-size: 0.8rem; color: var(--text-dim); }
        .scenario-item .category {
            display: inline-block;
            font-size: 0.7rem;
            padding: 2px 6px;
            background: var(--bg);
            border-radius: 3px;
            margin-top: 4px;
        }
        
        .run-btn {
            width: 100%;
            padding: 12px;
            background: var(--accent);
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            margin-top: 16px;
            transition: opacity 0.15s;
        }
        
        .run-btn:hover { opacity: 0.9; }
        .run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .results-panel { min-height: 500px; }
        
        .empty-state {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 300px;
            color: var(--text-dim);
        }
        
        .turn {
            margin-bottom: 16px;
            padding: 16px;
            border-radius: 8px;
            border-left: 3px solid;
        }
        
        .turn.user {
            background: rgba(31, 111, 235, 0.1);
            border-color: var(--user);
        }
        
        .turn.assistant {
            background: rgba(35, 134, 54, 0.1);
            border-color: var(--assistant);
        }
        
        .turn-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            font-size: 0.85rem;
        }
        
        .turn-role {
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .turn-meta { color: var(--text-dim); }
        
        .turn-content {
            white-space: pre-wrap;
            font-size: 0.95rem;
        }
        
        .summary {
            display: flex;
            gap: 20px;
            padding: 16px;
            background: var(--bg);
            border-radius: 6px;
            margin-bottom: 16px;
        }
        
        .summary-item {
            text-align: center;
        }
        
        .summary-value {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--accent);
        }
        
        .summary-label {
            font-size: 0.75rem;
            color: var(--text-dim);
            text-transform: uppercase;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: 600;
        }
        
        .status-badge.success { background: rgba(63, 185, 80, 0.2); color: var(--success); }
        .status-badge.error { background: rgba(248, 81, 73, 0.2); color: var(--error); }
        
        .loading {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 40px;
            justify-content: center;
        }
        
        .spinner {
            width: 24px;
            height: 24px;
            border: 3px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .prompt-toggle {
            font-size: 0.85rem;
            color: var(--accent);
            cursor: pointer;
            margin-bottom: 12px;
        }
        
        .prompt-content {
            background: var(--bg);
            padding: 12px;
            border-radius: 6px;
            font-size: 0.8rem;
            font-family: monospace;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
            display: none;
        }
        
        .prompt-content.visible { display: block; }
        
        .tools-section {
            margin: 12px 0;
            padding: 12px;
            background: var(--bg);
            border-radius: 6px;
            border: 1px solid var(--border);
        }
        
        .tool-call {
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }
        
        .tool-call:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
        
        .tool-header {
            display: flex;
            gap: 8px;
            align-items: center;
            font-size: 0.85rem;
            margin-bottom: 6px;
        }
        
        .tool-args {
            color: var(--text-dim);
            font-family: monospace;
            font-size: 0.75rem;
        }
        
        .tool-result {
            font-family: monospace;
            font-size: 0.75rem;
            color: var(--text-dim);
            max-height: 150px;
            overflow-y: auto;
            white-space: pre-wrap;
            padding: 8px;
            background: rgba(0,0,0,0.2);
            border-radius: 4px;
        }
        
        .thoughts-section {
            margin: 12px 0;
            padding: 12px;
            background: rgba(136, 132, 216, 0.1);
            border-radius: 6px;
            border: 1px solid rgba(136, 132, 216, 0.3);
        }
        
        .thoughts-header {
            font-size: 0.85rem;
            color: #8884d8;
            margin-bottom: 8px;
            font-weight: 500;
        }
        
        .thought {
            font-size: 0.85rem;
            color: var(--text-dim);
            padding: 4px 8px;
            margin: 4px 0;
            border-left: 2px solid #8884d8;
            font-style: italic;
        }
        
        .tool-thought {
            font-size: 0.8rem;
            color: #8884d8;
            margin-bottom: 6px;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎮 Albion Helper - E2E Scenarios</h1>
            <div id="status"></div>
        </header>
        
        <div class="layout">
            <div class="sidebar">
                <div class="panel">
                    <h2>Provider</h2>
                    <div class="config-row">
                        <label>Provider</label>
                        <select id="provider"></select>
                    </div>
                    <div class="config-row">
                        <label>Model</label>
                        <select id="model"></select>
                    </div>
                </div>
                
                <div class="panel" style="margin-top: 16px;">
                    <h2>Scenarios</h2>
                    <div class="scenario-list" id="scenarios"></div>
                    <button class="run-btn" id="runBtn" disabled>Run Scenario</button>
                </div>
            </div>
            
            <div class="panel results-panel" id="results">
                <div class="empty-state">Select a scenario and click Run</div>
            </div>
        </div>
    </div>
    
    <script>
        let providers = {};
        let scenarios = [];
        let selectedScenario = null;
        
        async function init() {
            // Load providers
            providers = await fetch('/api/providers').then(r => r.json());
            const providerSelect = document.getElementById('provider');
            
            for (const [name, config] of Object.entries(providers)) {
                if (config.available) {
                    const opt = document.createElement('option');
                    opt.value = name;
                    opt.textContent = name.charAt(0).toUpperCase() + name.slice(1);
                    providerSelect.appendChild(opt);
                }
            }
            
            providerSelect.addEventListener('change', updateModels);
            updateModels();
            
            // Load scenarios
            scenarios = await fetch('/api/scenarios').then(r => r.json());
            const container = document.getElementById('scenarios');
            
            let currentCategory = '';
            for (const s of scenarios) {
                if (s.category !== currentCategory) {
                    currentCategory = s.category;
                    const header = document.createElement('div');
                    header.style.cssText = 'font-size:0.75rem;color:var(--text-dim);margin:12px 0 6px;text-transform:uppercase;';
                    header.textContent = currentCategory;
                    container.appendChild(header);
                }
                
                const item = document.createElement('div');
                item.className = 'scenario-item';
                item.innerHTML = `
                    <div class="name">${s.name}</div>
                    <div class="desc">${s.description}</div>
                `;
                item.onclick = () => selectScenario(s, item);
                container.appendChild(item);
            }
        }
        
        function updateModels() {
            const provider = document.getElementById('provider').value;
            const modelSelect = document.getElementById('model');
            const config = providers[provider];
            
            modelSelect.innerHTML = '';
            for (const m of config.models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                if (m === config.default) opt.selected = true;
                modelSelect.appendChild(opt);
            }
        }
        
        function selectScenario(scenario, element) {
            document.querySelectorAll('.scenario-item').forEach(e => e.classList.remove('selected'));
            element.classList.add('selected');
            selectedScenario = scenario;
            document.getElementById('runBtn').disabled = false;
        }
        
        document.getElementById('runBtn').onclick = async function() {
            if (!selectedScenario) return;
            
            const btn = this;
            btn.disabled = true;
            btn.textContent = 'Running...';
            
            const results = document.getElementById('results');
            results.innerHTML = '<div class="loading"><div class="spinner"></div>Running scenario...</div>';
            
            try {
                const resp = await fetch('/api/run', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        scenario_id: selectedScenario.id,
                        provider: document.getElementById('provider').value,
                        model: document.getElementById('model').value,
                    })
                });
                
                const result = await resp.json();
                renderResult(result);
            } catch (e) {
                results.innerHTML = `<div class="empty-state" style="color:var(--error)">Error: ${e.message}</div>`;
            }
            
            btn.disabled = false;
            btn.textContent = 'Run Scenario';
        };
        
        function renderResult(result) {
            const container = document.getElementById('results');
            
            const statusClass = result.success ? 'success' : 'error';
            const statusText = result.success ? '✓ Passed' : '✗ Failed';
            const totalTools = result.turns.reduce((sum, t) => sum + (t.tools_called?.length || 0), 0);
            
            let html = `
                <div class="summary">
                    <div class="summary-item">
                        <div class="summary-value">${result.turns.length}</div>
                        <div class="summary-label">Turns</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-value">${totalTools}</div>
                        <div class="summary-label">Tools</div>
                    </div>
                    <div class="summary-item">
                        <div class="summary-value">${(result.total_time_ms / 1000).toFixed(1)}s</div>
                        <div class="summary-label">Total Time</div>
                    </div>
                    <div class="summary-item">
                        <div class="status-badge ${statusClass}">${statusText}</div>
                    </div>
                </div>
                
                <div class="prompt-toggle" onclick="togglePrompt()">📜 Show System Prompt</div>
                <div class="prompt-content" id="promptContent">${escapeHtml(result.system_prompt)}</div>
            `;
            
            if (result.error) {
                html += `<div class="turn" style="border-color:var(--error);background:rgba(248,81,73,0.1)">
                    <div class="turn-content" style="color:var(--error)">${escapeHtml(result.error)}</div>
                </div>`;
            }
            
            for (const turn of result.turns) {
                const time = turn.time_ms ? `${turn.time_ms.toFixed(0)}ms` : '';
                const toolCount = turn.tools_called?.length ? ` | 🔧 ${turn.tools_called.length} tools` : '';
                
                // Show ReAct thoughts chain
                let thoughtsHtml = '';
                if (turn.thoughts?.length) {
                    thoughtsHtml = '<div class="thoughts-section">';
                    thoughtsHtml += '<div class="thoughts-header">💭 Reasoning</div>';
                    for (const thought of turn.thoughts) {
                        thoughtsHtml += `<div class="thought">${escapeHtml(thought)}</div>`;
                    }
                    thoughtsHtml += '</div>';
                }
                
                let toolsHtml = '';
                if (turn.tools_called?.length) {
                    toolsHtml = '<div class="tools-section">';
                    for (const tc of turn.tools_called) {
                        const status = tc.success ? '✓' : '✗';
                        const statusColor = tc.success ? 'var(--success)' : 'var(--error)';
                        const thoughtLine = tc.thought ? `<div class="tool-thought">💭 ${escapeHtml(tc.thought)}</div>` : '';
                        toolsHtml += `
                            <div class="tool-call">
                                ${thoughtLine}
                                <div class="tool-header">
                                    <span style="color:${statusColor}">${status}</span>
                                    <strong>${tc.tool}</strong>
                                    <span class="tool-args">${JSON.stringify(tc.arguments)}</span>
                                </div>
                                <div class="tool-result">${JSON.stringify(tc.result, null, 2)}</div>
                            </div>
                        `;
                    }
                    toolsHtml += '</div>';
                }
                
                html += `
                    <div class="turn ${turn.role}">
                        <div class="turn-header">
                            <span class="turn-role">${turn.role === 'user' ? '👤 User' : '🤖 Assistant'}</span>
                            <span class="turn-meta">${toolCount}${time ? ' | ' + time : ''}</span>
                        </div>
                        ${thoughtsHtml}
                        ${toolsHtml}
                        <div class="turn-content">${escapeHtml(turn.content)}</div>
                    </div>
                `;
            }
            
            container.innerHTML = html;
        }
        
        function togglePrompt() {
            document.getElementById('promptContent').classList.toggle('visible');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        init();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    print("🎮 Albion Helper E2E Scenario Test UI")
    print("=" * 40)
    print("Starting server at http://localhost:8765")
    print("Press Ctrl+C to stop\n")
    
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
