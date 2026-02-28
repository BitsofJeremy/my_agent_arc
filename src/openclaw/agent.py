"""Core agentic loop for the OpenClaw agent framework.

Orchestrates multi-turn conversations with tool use by iteratively calling
Ollama, dispatching tool calls, and feeding results back into the context
until the model produces a final text answer or the iteration cap is reached.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import ollama

from openclaw.config import get_settings
from openclaw.context_manager import build_context, log_message, maybe_compact
from openclaw.tools import execute_tool, get_tool_schemas

logger = logging.getLogger("openclaw.agent")

# Fallback returned when the iteration budget is exhausted.
_MAX_ITERATIONS_REPLY = (
    "I've been thinking about this for a while and need to stop here. "
    "Could you rephrase or simplify your request?"
)

# User-facing message when the LLM backend is unreachable / broken.
_LLM_ERROR_REPLY = "I'm having trouble thinking right now. Please try again."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_tool_calls(
    message: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return a normalised list of tool-call dicts from a response message.

    Each item has ``"name"`` and ``"arguments"`` keys.  Returns an empty list
    when the model did not request any tool calls.
    """
    raw_calls: list[dict[str, Any]] | None = message.get("tool_calls")
    if not raw_calls:
        return []

    normalised: list[dict[str, Any]] = []
    for call in raw_calls:
        func = call.get("function", {})
        normalised.append({
            "name": func.get("name", ""),
            "arguments": func.get("arguments", {}),
        })
    return normalised


def _safe_parse_arguments(raw: Any) -> dict[str, Any]:
    """Coerce tool-call arguments into a ``dict``.

    Ollama normally returns arguments as a dict, but some model responses may
    emit a JSON string instead.  This helper handles both cases gracefully and
    raises :class:`ValueError` when the payload is truly unparseable.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    raise ValueError(f"Unexpected arguments type: {type(raw).__name__}")


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


async def run_agent(
    user_input: str,
    source: str = "telegram",
    session_id: str | None = None,
) -> str:
    """Run the agentic loop to produce a response for *user_input*.

    Parameters
    ----------
    user_input:
        The latest message from the user.
    source:
        Channel that originated the message (e.g. ``"telegram"``).
        Currently informational only.
    session_id:
        Optional session scope for multi-tenant conversation isolation.

    Returns
    -------
    str
        The agent's final text response.
    """
    settings = get_settings()

    # --- 1. Persist the incoming user message ------------------------------
    await log_message("user", user_input, session_id=session_id)

    # --- 2. Compact history if the token budget is exceeded ----------------
    await maybe_compact(session_id)

    # --- 3. Build the prompt context (system + history) --------------------
    messages: list[dict[str, Any]] = await build_context(session_id)

    tool_schemas = get_tool_schemas()

    # --- 4. Agentic loop ---------------------------------------------------
    for iteration in range(1, settings.max_agent_iterations + 1):
        logger.info(
            "Iteration %d/%d (session=%s)",
            iteration,
            settings.max_agent_iterations,
            session_id,
        )

        # Call Ollama (synchronous) on a background thread.
        try:
            response = await asyncio.to_thread(
                ollama.chat,
                model=settings.ollama_model,
                messages=messages,
                tools=tool_schemas,
            )
        except ollama.ResponseError as exc:
            logger.error("Ollama ResponseError: %s", exc)
            return _LLM_ERROR_REPLY
        except Exception:
            logger.exception("Unexpected error calling ollama.chat()")
            return _LLM_ERROR_REPLY

        assistant_message: dict[str, Any] = response["message"]
        tool_calls = _extract_tool_calls(assistant_message)

        # ----- Branch A: model requested tool calls -------------------------
        if tool_calls:
            # Append the assistant's message (with tool_calls) to context.
            messages.append(assistant_message)

            # Serialise the assistant tool-call request for the log.
            tool_call_summary = json.dumps(
                [{"name": tc["name"], "arguments": tc["arguments"]} for tc in tool_calls],
                default=str,
            )
            await log_message(
                "assistant",
                tool_call_summary,
                session_id=session_id,
            )

            for tc in tool_calls:
                name: str = tc["name"]

                # Parse / validate arguments.
                try:
                    arguments = _safe_parse_arguments(tc["arguments"])
                except (ValueError, json.JSONDecodeError) as exc:
                    error_result = (
                        f"Error: malformed arguments for tool '{name}': {exc}"
                    )
                    logger.error(error_result)
                    tool_result = error_result
                else:
                    logger.info("Calling tool %s(%s)", name, arguments)
                    tool_result = await execute_tool(name, arguments)

                # Feed the tool result back into the conversation.
                tool_message: dict[str, Any] = {
                    "role": "tool",
                    "content": tool_result,
                }
                messages.append(tool_message)

                await log_message(
                    "tool",
                    tool_result,
                    tool_name=name,
                    session_id=session_id,
                )

            # Continue the loop so the model can process tool results.
            continue

        # ----- Branch B: final text answer ----------------------------------
        content: str = assistant_message.get("content", "")
        logger.info("Agent produced final answer (session=%s)", session_id)

        await log_message("assistant", content, session_id=session_id)
        return content

    # --- 5. Iteration budget exhausted -------------------------------------
    logger.warning(
        "Max agent iterations (%d) reached without a final answer (session=%s)",
        settings.max_agent_iterations,
        session_id,
    )
    await log_message("assistant", _MAX_ITERATIONS_REPLY, session_id=session_id)
    return _MAX_ITERATIONS_REPLY
