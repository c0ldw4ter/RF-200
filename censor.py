import asyncio
import logging
import os
from history import ChannelContext
from modes import build_system_prompt, build_user_prompt

log = logging.getLogger(__name__)

RETRIES = 3
RETRY_DELAY = 2

# ── ПРОВАЙДЕР ─────────────────────────────────────────────────────────────────
# Активен Groq. Чтобы переключиться на Gemini:
#   1. Закомментируй блок GROQ
#   2. Раскомментируй блок GEMINI
#   3. В requirements.txt замени groq на google-generativeai==0.8.3
#   4. В .env замени GROQ_API_KEY на GEMINI_API_KEY

# ── GROQ ──────────────────────────────────────────────────────────────────────
from groq import Groq

_groq_client = None

def get_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client

def _call_model(system_prompt: str, user_prompt: str) -> str:
    response = get_client().chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.9,
    )
    return response.choices[0].message.content.strip()

# ── GEMINI (закомментировано) ─────────────────────────────────────────────────
# import google.generativeai as genai
#
# def _call_model(system_prompt: str, user_prompt: str) -> str:
#     genai.configure(api_key=os.environ["GEMINI_API_KEY"])
#     model = genai.GenerativeModel(
#         model_name="gemini-2.5-flash",
#         system_instruction=system_prompt,
#         generation_config=genai.GenerationConfig(temperature=0.9),
#     )
#     response = model.generate_content(user_prompt)
#     return response.text.strip()
# ─────────────────────────────────────────────────────────────────────────────

async def generate_censor_response(
    post_text: str,
    media_description: str | None,
    mode: str,
    ctx: ChannelContext,
) -> str:
    system_prompt = build_system_prompt(mode, ctx)
    user_prompt = build_user_prompt(post_text, media_description)

    last_error = None
    for attempt in range(RETRIES):
        try:
            return await asyncio.to_thread(_call_model, system_prompt, user_prompt)
        except Exception as e:
            last_error = e
            if attempt < RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                log.warning("Попытка %d/%d не удалась (%s), повтор через %ds...", attempt + 1, RETRIES, e, delay)
                await asyncio.sleep(delay)

    raise last_error
