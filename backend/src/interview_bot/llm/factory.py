from interview_bot.config import ModelProvider, Settings
from interview_bot.llm.anthropic import AnthropicClient
from interview_bot.llm.base import LLMClient
from interview_bot.llm.echo import EchoClient
from interview_bot.llm.ollama import OllamaClient


def build_llm_client(settings: Settings, model_provider: ModelProvider | None = None) -> LLMClient:
    model_provider = model_provider or settings.default_model_provider
    if model_provider == "ollama":
        return OllamaClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if model_provider == "anthropic":
        return AnthropicClient(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if model_provider == "echo":
        return EchoClient()
    raise ValueError(f"Unknown model provider: {model_provider}")


def build_llm_clients(settings: Settings) -> dict[str, LLMClient]:
    """Every provider the interview can be switched to, by name.

    All of them are built up front because none of them reaches the network
    until it is asked for a completion: an Anthropic client with no key costs
    nothing until a session actually picks it.
    """
    return {provider: build_llm_client(settings, provider) for provider in settings.model_providers}
