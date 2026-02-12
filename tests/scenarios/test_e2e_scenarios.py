"""E2E Scenario Tests for Albion Helper.

These tests run actual conversations with configured LLM providers to validate
the complete user experience across different use cases.

Run with:
    pytest tests/scenarios/ -v -s --log-cli-level=DEBUG

Environment Variables:
    E2E_OLLAMA_MODEL: Ollama model to use (default: llama3:latest)
    E2E_ANTHROPIC_MODEL: Anthropic model to use (default: claude-3-haiku-20240307)
    ANTHROPIC_API_KEY: Required for Anthropic tests

Markers:
    @pytest.mark.e2e: All E2E tests
    @pytest.mark.ollama: Tests that use Ollama
    @pytest.mark.anthropic: Tests that use Anthropic
    @pytest.mark.slow: Long-running tests
"""

import os
import pytest
from .conftest import Scenario, display_scenario_header


# Skip markers
requires_ollama = pytest.mark.skipif(
    os.getenv("SKIP_OLLAMA_TESTS", "").lower() == "true",
    reason="SKIP_OLLAMA_TESTS is set"
)

requires_anthropic = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)


# ==================== Market Query Scenarios ====================

@pytest.mark.e2e
@pytest.mark.ollama
@requires_ollama
class TestMarketScenarios:
    """Market-related query scenarios."""
    
    @pytest.mark.asyncio
    async def test_simple_price_query(self, scenario_runner):
        """User asks for the price of a single item."""
        scenario = Scenario(
            name="Simple Price Query",
            description="User asks for the current price of T4 leather in Caerleon.",
            provider="ollama",
        )
        
        # Turn 1: Initial price question
        scenario.add_user_turn("What's the current price of T4 leather in Caerleon?")
        
        result = await scenario_runner.run_scenario(scenario)
        
        # The test passes if we get a response - actual price data may vary
        assert result.success
        assert any(t.role == "assistant" for t in scenario.turns)
        

    
    @pytest.mark.asyncio
    async def test_price_comparison_multi_city(self, scenario_runner):
        """User wants to compare prices across cities."""
        scenario = Scenario(
            name="Multi-City Price Comparison",
            description="User wants to find the best city to buy T5 Crossbow.",
            provider="ollama",
        )
        
        # Turn 1: Comparison question
        scenario.add_user_turn(
            "I want to buy a T5 Crossbow. Which city has the cheapest price?"
        )
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success
        assert any(t.role == "assistant" for t in scenario.turns)
    
    @pytest.mark.asyncio
    async def test_trading_opportunity_query(self, scenario_runner):
        """User asks about trading/flipping opportunities."""
        scenario = Scenario(
            name="Trading Opportunity Query",
            description="User wants to know about profitable trading opportunities.",
            provider="ollama",
        )
        
        scenario.add_user_turn(
            "What items have good profit margins for flipping right now?"
        )
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success


# ==================== Multi-Turn Conversation Scenarios ====================

@pytest.mark.e2e
@pytest.mark.ollama
@requires_ollama
class TestMultiTurnScenarios:
    """Multi-turn conversation scenarios with follow-up questions."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_price_then_crafting_followup(self, scenario_runner):
        """User asks about prices, then follows up about crafting."""
        scenario = Scenario(
            name="Price to Crafting Follow-up",
            description="User starts with price query, then asks about crafting the item.",
            provider="ollama",
        )
        
        # Turn 1: Price query
        scenario.add_user_turn("What's the price of T6 leather?")
        
        # Run first turn
        result1 = await scenario_runner.run_scenario(scenario)
        assert result1.success
        
        # Turn 2: Follow-up about crafting
        scenario.add_user_turn("What materials do I need to craft T6 leather?")
        
        # Run with updated conversation
        result2 = await scenario_runner.run_scenario(scenario, show_prompts=False)
        
        assert result2.success
        assert len([t for t in scenario.turns if t.role == "assistant"]) >= 2
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_clarification_conversation(self, scenario_runner):
        """User provides clarification after initial query."""
        scenario = Scenario(
            name="Clarification Conversation",
            description="User asks vague question, assistant asks for clarification, user clarifies.",
            provider="ollama",
        )
        
        # Turn 1: Ambiguous query
        scenario.add_user_turn("What's the price of a bag?")
        
        result = await scenario_runner.run_scenario(scenario)
        
        # The AI should either ask for clarification or make a reasonable assumption
        assert result.success
        
        # Turn 2: Clarification
        scenario.add_user_turn("I meant a T5 bag.")
        
        result = await scenario_runner.run_scenario(scenario, show_prompts=False)
        assert result.success


# ==================== General Chat Scenarios ====================

@pytest.mark.e2e
@pytest.mark.ollama
@requires_ollama
class TestGeneralChatScenarios:
    """General conversation scenarios not related to market/crafting."""
    
    @pytest.mark.asyncio
    async def test_greeting(self, scenario_runner):
        """User greets the assistant."""
        scenario = Scenario(
            name="Greeting",
            description="User says hello and assistant responds warmly.",
            provider="ollama",
        )
        
        scenario.add_user_turn("Hello! I'm new to Albion Online.")
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success

    
    @pytest.mark.asyncio
    async def test_game_knowledge_question(self, scenario_runner):
        """User asks general game knowledge question."""
        scenario = Scenario(
            name="Game Knowledge Question",
            description="User asks about game mechanics.",
            provider="ollama",
        )
        
        scenario.add_user_turn("What's the difference between gathering and refining?")
        
        result = await scenario_runner.run_scenario(scenario)
        assert result.success
    
    @pytest.mark.asyncio
    async def test_off_topic_question(self, scenario_runner):
        """User asks a completely off-topic question."""
        scenario = Scenario(
            name="Off-Topic Question",
            description="User asks unrelated question to test assistant's flexibility.",
            provider="ollama",
        )
        
        scenario.add_user_turn("What's the capital of France?")
        
        result = await scenario_runner.run_scenario(scenario)
        
        # Should still respond helpfully
        assert result.success
        assistant_turns = [t for t in scenario.turns if t.role == "assistant"]
        # Should have some response
        assert len(assistant_turns[0].content) > 10


# ==================== Anthropic Provider Scenarios ====================

@pytest.mark.e2e
@pytest.mark.anthropic
@requires_anthropic
class TestAnthropicScenarios:
    """Scenarios specifically for Anthropic provider."""
    
    @pytest.mark.asyncio
    async def test_market_query_anthropic(self, scenario_runner):
        """Market query with Anthropic."""
        scenario = Scenario(
            name="Market Query (Anthropic)",
            description="Test market query with Anthropic Claude.",
            provider="anthropic",
        )
        
        scenario.add_user_turn("What's the price of T4 Cape?")
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success
        assert any(t.role == "assistant" for t in scenario.turns)
    
    @pytest.mark.asyncio
    async def test_multi_turn_anthropic(self, scenario_runner):
        """Multi-turn conversation with Anthropic."""
        scenario = Scenario(
            name="Multi-Turn (Anthropic)",
            description="Test conversation continuity with Anthropic.",
            provider="anthropic",
        )
        
        scenario.add_user_turn("Tell me about Caerleon.")
        
        result = await scenario_runner.run_scenario(scenario)
        assert result.success
        
        scenario.add_user_turn("What items are commonly traded there?")
        
        result = await scenario_runner.run_scenario(scenario, show_prompts=False)
        assert result.success


# ==================== Edge Case Scenarios ====================

@pytest.mark.e2e
@pytest.mark.ollama
@requires_ollama
class TestEdgeCaseScenarios:
    """Edge cases and error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_empty_message(self, scenario_runner):
        """Handle empty or whitespace message."""
        scenario = Scenario(
            name="Empty Message Handling",
            description="Test handling of empty or minimal input.",
            provider="ollama",
        )
        
        scenario.add_user_turn("   ")  # Whitespace only
        
        result = await scenario_runner.run_scenario(scenario)
        # Should handle gracefully, might fail but shouldn't crash
        # We just check it doesn't throw an exception
    
    @pytest.mark.asyncio
    async def test_long_message(self, scenario_runner):
        """Handle very long user message."""
        scenario = Scenario(
            name="Long Message Handling",
            description="Test handling of long, detailed user input.",
            provider="ollama",
        )
        
        long_message = """
        I'm a new player trying to figure out the best way to make silver.
        I've been gathering T4 resources and selling them in Martlock, but
        I've heard that prices are better in Caerleon. I'm also interested
        in crafting, specifically leather working. What would you recommend?
        Should I focus on gathering, crafting, or trading? Also, what tier
        should I be working with at my current skill level?
        """
        
        scenario.add_user_turn(long_message)
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success
        # Should detect market task due to price/trading keywords
        assistant_turns = [t for t in scenario.turns if t.role == "assistant"]
        assert len(assistant_turns[0].content) > 50  # Should give detailed response
    
    @pytest.mark.asyncio
    async def test_typo_handling(self, scenario_runner):
        """Test handling of typos in item names."""
        scenario = Scenario(
            name="Typo Handling",
            description="Test if assistant can handle typos in item names.",
            provider="ollama",
        )
        
        scenario.add_user_turn("What's the price of t4 lether?")  # Typo: lether
        
        result = await scenario_runner.run_scenario(scenario)
        
        assert result.success
        # AI should either correct or ask for clarification


# ==================== Runner Entry Point ====================

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "-s",
        "--log-cli-level=INFO",
        "-m", "not slow",
    ])
