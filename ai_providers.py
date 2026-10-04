"""
AI provider layer: the Groq/Cerebras/Mistral/OpenRouter/local-Ollama
fallback chain, provider cycling on failure, and ask_ai() which builds
the prompt and returns Cortana's answer.
"""

import time

import requests

import config
import state
import permanent_memory
import server_info
import web_search
from logger_setup import logger


def call_groq(messages):
    # openai/gpt-oss-120b is a reasoning model: it spends tokens "thinking"
    # before it writes the actual reply, and those reasoning tokens count
    # against the completion budget. With a low budget it can burn the
    # whole thing on reasoning and return a 200 with an EMPTY content field
    # (finish_reason "length") — that's the blank "Cortana: @name:" bug.
    # reasoning_effort=low keeps it from over-thinking a one-liner, and
    # max_completion_tokens (Groq's current param; max_tokens is deprecated
    # for this model) gives enough room for reasoning + the actual answer.
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {state.GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": "openai/gpt-oss-120b", "messages": messages, "temperature": 0.55,
              "max_completion_tokens": 350, "reasoning_effort": "low"}, timeout=10)
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise Exception("Empty response (reasoning likely ate the token budget)")
        return content.strip()
    raise Exception(f"Groq {r.status_code}")


def call_cerebras(messages):
    # Also serving openai/gpt-oss-120b — same empty-on-truncated-reasoning
    # risk as Groq above, but Cerebras's own reasoning-control params
    # aren't confirmed, so this only guards against the empty result and
    # gives it a larger budget rather than guessing at extra parameters.
    r = requests.post("https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {state.CEREBRAS_API_KEY}", "Content-Type": "application/json"},
        json={"model": "openai/gpt-oss-120b", "messages": messages, "temperature": 0.55, "max_tokens": 350}, timeout=10)
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise Exception("Empty response (reasoning likely ate the token budget)")
        return content.strip()
    raise Exception(f"Cerebras {r.status_code}")


def call_mistral(messages):
    r = requests.post("https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {state.MISTRAL_API_KEY}", "Content-Type": "application/json"},
        json={"model": "mistral-small-latest", "messages": messages, "temperature": 0.55, "max_tokens": 300}, timeout=10)
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise Exception("Empty response")
        return content.strip()
    raise Exception(f"Mistral {r.status_code}")


def call_openrouter(messages):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {state.OPENROUTER_API_KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/cortana-bot-eldewrito", "X-Title": "Cortana Bot"},
        json={"model": "openrouter/free", "messages": messages, "temperature": 0.55, "max_tokens": 300}, timeout=10)
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"].get("content") or ""
        if not content.strip():
            raise Exception("Empty response")
        return content.strip()
    raise Exception(f"OpenRouter {r.status_code}")


def call_local(messages):
    try:
        user_message = ""
        system_message = ""

        for msg in messages:
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
            elif msg.get("role") == "system":
                system_message = msg.get("content", "")

        # The local model is much smaller and given a tighter token
        # budget than the API providers — always use the purpose-built
        # short prompt for it rather than whatever was passed in, since
        # the fuller API prompt would be harder for it to follow well.
        system_message = config.SYSTEM_PROMPT_LOCAL

        full_prompt = f"{system_message}\n\nUser: {user_message}\n\nCortana:"

        r = requests.post(
            f"{config.OLLAMA_API}/api/generate",
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.55,
                    "num_predict": 150,
                    "top_p": 0.85,
                    "repeat_penalty": 1.1,
                    "stop": ["\nUser:", "\n\n"]
                }
            },
            timeout=45
        )

        if r.status_code == 200:
            response = r.json().get("response", "").strip()
            if not response:
                raise Exception("Empty response from model")
            if response.startswith("Cortana:"):
                response = response[8:].strip()
            if response.endswith(","):
                response = response[:-1] + "..."
            return response
        raise Exception(f"Ollama {r.status_code}")
    except requests.exceptions.Timeout:
        logger.info("[LOCAL] Request timed out")
        raise Exception("Local model timeout")
    except Exception as e:
        logger.info(f"[LOCAL] Error: {e}")
        raise


def is_ollama_running() -> bool:
    try:
        r = requests.get(f"{config.OLLAMA_API}/api/tags", timeout=3)
        if r.status_code == 200:
            models = r.json().get("models", [])
            return any(config.OLLAMA_MODEL in m.get("name", "") for m in models)
    except Exception:
        pass
    return False


CLOUD_PROVIDER_CHAIN = [
    ("groq",       call_groq,       lambda: state.GROQ_API_KEY),
    ("cerebras",   call_cerebras,   lambda: state.CEREBRAS_API_KEY),
    ("mistral",    call_mistral,    lambda: state.MISTRAL_API_KEY),
    ("openrouter", call_openrouter, lambda: state.OPENROUTER_API_KEY),
]

PROVIDER_FAILURE_THRESHOLD = 3
PROVIDER_COOLDOWN_SECONDS = 60


def get_next_available_provider():
    """Cycle through providers, skipping failed ones."""
    # If load balancing is disabled, just return the first working provider
    if not state.load_balancing_enabled:
        for name, call_fn, has_key in CLOUD_PROVIDER_CHAIN:
            if has_key():
                if name in state.provider_failures:
                    last_fail, fail_count = state.provider_failures[name]
                    if fail_count >= PROVIDER_FAILURE_THRESHOLD:
                        if time.time() - last_fail < PROVIDER_COOLDOWN_SECONDS:
                            continue
                        else:
                            del state.provider_failures[name]
                return name, call_fn
        return None, None

    # Load balancing is enabled - cycle through providers
    available = []
    for name, call_fn, has_key in CLOUD_PROVIDER_CHAIN:
        if has_key():
            if name in state.provider_failures:
                last_fail, fail_count = state.provider_failures[name]
                if fail_count >= PROVIDER_FAILURE_THRESHOLD:
                    if time.time() - last_fail < PROVIDER_COOLDOWN_SECONDS:
                        continue
                    else:
                        del state.provider_failures[name]
            available.append((name, call_fn))

    if not available:
        return None, None

    if state.current_provider_index >= len(available):
        state.current_provider_index = 0

    provider_name, provider_func = available[state.current_provider_index]
    state.current_provider_index = (state.current_provider_index + 1) % len(available)

    return provider_name, provider_func


def mark_provider_failure(provider_name: str):
    """Mark a provider as failed for cycling."""
    now = time.time()
    if provider_name in state.provider_failures:
        last_fail, count = state.provider_failures[provider_name]
        state.provider_failures[provider_name] = (now, count + 1)
    else:
        state.provider_failures[provider_name] = (now, 1)
    logger.info(f"[API] Marked {provider_name} as failed ({state.provider_failures[provider_name][1]}/{PROVIDER_FAILURE_THRESHOLD})")


def ask_ai(player_name: str, question: str) -> str:
    logger.info(f"[AI] {player_name} asked: {question}")
    try:
        search_ctx = web_search.get_search_context(question)
        memory_ctx = permanent_memory.load_memory() if state.memory_enabled else ""
        system = config.SYSTEM_PROMPT

        if memory_ctx:
            system += f"\n\nPermanent memory:\n{memory_ctx}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"""{server_info.build_game_context()}

{server_info.build_chat_context()}

{f'Info from search:{chr(10)}{search_ctx}{chr(10)}' if search_ctx else ''}
{player_name} asks: {question}"""}
        ]

        def trim(a):
            # Cap at the game's readable chat length, but never slice a word
            # in half — cut back to the last space before the limit instead.
            limit = config.CHAT_TOTAL_LIMIT
            if len(a) <= limit:
                return a
            cut = a.rfind(" ", 0, limit)
            if cut == -1:
                cut = limit
            return a[:cut].rstrip(".,;: ") + "..."

        # Local model first if enabled
        if state.local_enabled and is_ollama_running():
            try:
                return trim(call_local(messages))
            except Exception as e:
                logger.info(f"[AI] Local failed: {e} — falling back to cloud...")

        # Cloud providers with cycling
        attempts = 0
        max_attempts = len([n for n, _, h in CLOUD_PROVIDER_CHAIN if h()]) * 2

        while attempts < max_attempts:
            provider_name, provider_func = get_next_available_provider()
            if not provider_name:
                break

            try:
                answer = provider_func(messages)
                logger.info(f"[AI] Response from {provider_name.capitalize()}")
                if provider_name in state.provider_failures:
                    del state.provider_failures[provider_name]
                return trim(answer)
            except Exception as e:
                logger.info(f"[AI] {provider_name.capitalize()} failed: {e}")
                mark_provider_failure(provider_name)
                attempts += 1

        return "All AI providers are currently unavailable. Try again later."
    except Exception as e:
        logger.info(f"[AI] Unexpected error: {e}")
        return "An error occurred on my end. Try again."


def get_active_provider_name() -> str:
    if state.local_enabled:
        return f"Local ({config.OLLAMA_MODEL})"
    if state.active_provider != "auto":
        return state.active_provider.capitalize()
    for name, _, has_key in CLOUD_PROVIDER_CHAIN:
        if has_key():
            return f"{name.capitalize()} (auto)"
    return "None"
