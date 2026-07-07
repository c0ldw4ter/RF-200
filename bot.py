import asyncio
import logging
import os
import random
from io import BytesIO
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, MessageOriginChannel
from aiogram.client.session.aiohttp import AiohttpSession

import history
import censor
import media as media_analyzer

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
COMMENTS_CHAT_ID = int(os.environ["COMMENTS_CHAT_ID"])
CENSOR_MODE = os.environ.get("CENSOR_MODE", "random")
CENSOR_MODES = ["paranoid", "unpredictable", "escalating"]
DB_PATH = os.environ.get("DB_PATH", "censor_history.db")
PROXY_URL = os.environ.get("PROXY_URL")

session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()


async def _download(file_id: str) -> bytes:
    buf = BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def build_media_context(msg: Message) -> str | None:
    """Анализирует медиа поста и возвращает текстовое описание."""
    client = censor.get_client()
    parts = []

    try:
        if msg.photo:
            file_bytes = await _download(msg.photo[-1].file_id)
            description = await media_analyzer.describe_image(client, file_bytes)
            caption = msg.caption or ""
            if description:
                parts.append(f"[ФОТО: {description}]" + (f" Подпись: «{caption}»" if caption else ""))
            elif caption:
                parts.append(f"фотография с подписью: «{caption}»")
            else:
                parts.append("фотография")

        if msg.audio:
            file_bytes = await _download(msg.audio.file_id)
            transcript = await media_analyzer.transcribe(client, file_bytes, "audio.mp3")
            title = msg.audio.title or ""
            if transcript:
                parts.append(f"[АУДИО{f' «{title}»' if title else ''}, транскрипт: {transcript}]")
            else:
                parts.append(f"аудиофайл{f' «{title}»' if title else ''}")

        if msg.video:
            file_bytes = await _download(msg.video.file_id)
            transcript = await media_analyzer.transcribe(client, file_bytes, "video.mp4")
            caption = msg.caption or ""
            if transcript:
                parts.append(f"[ВИДЕО, транскрипт: {transcript}]" + (f" Подпись: «{caption}»" if caption else ""))
            else:
                parts.append("видео" + (f" с подписью: «{caption}»" if caption else ""))

        if msg.video_note:
            file_bytes = await _download(msg.video_note.file_id)
            transcript = await media_analyzer.transcribe(client, file_bytes, "circle.mp4")
            if transcript:
                parts.append(f"[КРУЖОК, транскрипт: {transcript}]")
            else:
                parts.append("видеосообщение (кружок)")

        if msg.document:
            parts.append(f"документ: {msg.document.file_name or 'без названия'}")

        if msg.sticker:
            parts.append(f"стикер {msg.sticker.emoji or ''}")

    except Exception as e:
        log.warning("Ошибка анализа медиа: %s", e)

    return "\n".join(parts) if parts else None


def extract_text(msg: Message) -> str | None:
    return msg.text or msg.caption or None


@dp.message(F.chat.id == COMMENTS_CHAT_ID, F.forward_origin)
async def handle_forwarded_channel_post(msg: Message):
    if not isinstance(msg.forward_origin, MessageOriginChannel):
        return
    if msg.forward_origin.chat.id != CHANNEL_ID:
        return

    text = extract_text(msg)
    has_media = any([msg.photo, msg.video, msg.video_note, msg.audio, msg.document, msg.sticker])

    if not text and not has_media:
        log.info("Пост без текста и медиа — пропускаем (message_id=%s)", msg.message_id)
        return

    post_text = text or "[пост без текста]"
    topics = history.detect_topics(post_text)
    await history.save_post(msg.message_id, topics, post_text, DB_PATH)

    ctx = await history.get_context(db_path=DB_PATH)
    delta = 0
    if any(t in history.FOREIGN_TOPICS for t in topics):
        delta += 1
    if ctx.recent_foreign_count >= 3:
        delta += 1
    if any(t in history.INNOCUOUS_TOPICS for t in topics):
        delta = max(delta - 1, -1)

    await history.update_panic_level(delta, DB_PATH)
    ctx = await history.get_context(db_path=DB_PATH)

    mode = random.choice(CENSOR_MODES) if CENSOR_MODE == "random" else CENSOR_MODE
    log.info("Пост id=%s | темы=%s | паника=%s | режим=%s", msg.message_id, topics, ctx.panic_level, mode)

    try:
        placeholder = await msg.reply(text="Изучаю материал, товарищи...")
    except Exception as e:
        log.error("Не удалось отправить плейсхолдер: %s", e)
        return

    # Анализируем медиа параллельно (уже после отправки плейсхолдера)
    media_desc = await build_media_context(msg)

    try:
        response = await censor.generate_censor_response(
            post_text=post_text,
            media_description=media_desc,
            mode=mode,
            ctx=ctx,
        )
    except Exception as e:
        log.error("Все попытки генерации исчерпаны: %s", e)
        await placeholder.edit_text("Материал временно изъят из обращения. Отдел контроля приносит извинения.")
        return

    try:
        await placeholder.edit_text(text=response)
        log.info("Комментарий опубликован к посту %s", msg.message_id)
    except Exception as e:
        log.error("Не удалось отредактировать комментарий: %s", e)


async def main():
    await history.init_db(DB_PATH)
    log.info("Бот запущен | режим цензора: %s", CENSOR_MODE)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
