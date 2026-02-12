"""Schema definitions for structured prompts and responses."""

from .output_schema import (
    AgentResponse,
    TextResponse,
    DataResponse,
    ActionRequest,
    ErrorResponse,
    ResponseType,
)
from .prompt_schema import (
    PromptMeta,
    PromptDocument,
    PromptType,
)

__all__ = [
    # Output schemas
    "AgentResponse",
    "TextResponse",
    "DataResponse",
    "ActionRequest",
    "ErrorResponse",
    "ResponseType",
    # Prompt schemas
    "PromptMeta",
    "PromptDocument",
    "PromptType",
]
