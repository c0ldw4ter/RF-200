import asyncio
import base64
import logging
from io import BytesIO
from groq import Groq

log = logging.getLogger(__name__)

WHISPER_MODEL = "whisper-large-v3-turbo"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_FILE_MB = 24  # Groq Whisper лимит — 25 MB


def _transcribe(client: Groq, file_bytes: bytes, filename: str) -> str:
    result = client.audio.transcriptions.create(
        file=(filename, file_bytes),
        model=WHISPER_MODEL,
        response_format="text",
        language="ru",
    )
    return str(result).strip()


def _describe_image(client: Groq, file_bytes: bytes) -> str:
    image_b64 = base64.b64encode(file_bytes).decode("utf-8")
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
                {
                    "type": "text",
                    "text": "Опиши подробно что изображено на фото. Отвечай по-русски.",
                },
            ],
        }],
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


async def transcribe(client: Groq, file_bytes: bytes, filename: str) -> str | None:
    size_mb = len(file_bytes) / 1024 / 1024
    if size_mb > MAX_FILE_MB:
        log.warning("Файл %s слишком большой (%.1f MB), пропускаем", filename, size_mb)
        return None
    return await asyncio.to_thread(_transcribe, client, file_bytes, filename)


async def describe_image(client: Groq, file_bytes: bytes) -> str | None:
    return await asyncio.to_thread(_describe_image, client, file_bytes)
