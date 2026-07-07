import os
import json
import aiosqlite
from datetime import datetime, timedelta
from dataclasses import dataclass

DB_PATH = os.environ.get("DB_PATH", "censor_history.db")

FOREIGN_TOPICS = {"заграница", "вена", "запад", "америка", "европа", "туризм", "путешествие",
                  "иностранный", "зарубеж", "visa", "виза", "эмиграция", "лондон",
                  "париж", "берлин", "нью-йорк", "сша", "евросоюз", "нато"}

SUSPICIOUS_TOPICS = {"деньги", "доллар", "евро", "криптовалюта", "биткоин", "акции",
                     "инвестиции", "прибыль", "капитал", "богатство", "бизнес"}

INNOCUOUS_TOPICS = {"кот", "кошка", "собака", "рецепт", "суп", "борщ", "дача",
                    "огород", "погода", "цветы", "бабушка", "дедушка", "пирог"}


@dataclass
class ChannelContext:
    recent_foreign_count: int   # постов про заграницу за последние N постов
    recent_suspicious_count: int
    total_posts: int
    panic_level: int            # 0-5, накапливается и медленно спадает
    last_topics: list[str]


async def init_db(db_path: str = DB_PATH):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                timestamp TEXT,
                topics TEXT,
                text_snippet TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS censor_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()


async def save_post(message_id: int, topics: list[str], text: str, db_path: str = DB_PATH):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO posts (message_id, timestamp, topics, text_snippet) VALUES (?, ?, ?, ?)",
            (message_id, datetime.utcnow().isoformat(), json.dumps(topics, ensure_ascii=False), text[:200])
        )
        await db.commit()


async def get_context(window: int = 10, db_path: str = DB_PATH) -> ChannelContext:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT topics FROM posts ORDER BY id DESC LIMIT ?", (window,)
        )
        rows = await cursor.fetchall()

        cursor2 = await db.execute("SELECT COUNT(*) FROM posts")
        total = (await cursor2.fetchone())[0]

        state_cursor = await db.execute("SELECT value FROM censor_state WHERE key='panic_level'")
        panic_row = await state_cursor.fetchone()
        panic_level = int(panic_row[0]) if panic_row else 0

    foreign_count = 0
    suspicious_count = 0
    last_topics = []

    for (topics_json,) in rows:
        topics = json.loads(topics_json)
        last_topics.extend(topics)
        if any(t in FOREIGN_TOPICS for t in topics):
            foreign_count += 1
        if any(t in SUSPICIOUS_TOPICS for t in topics):
            suspicious_count += 1

    return ChannelContext(
        recent_foreign_count=foreign_count,
        recent_suspicious_count=suspicious_count,
        total_posts=total,
        panic_level=panic_level,
        last_topics=list(set(last_topics))[-10:]
    )


async def update_panic_level(delta: int, db_path: str = DB_PATH):
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT value FROM censor_state WHERE key='panic_level'")
        row = await cursor.fetchone()
        current = int(row[0]) if row else 0
        new_level = max(0, min(5, current + delta))
        await db.execute(
            "INSERT OR REPLACE INTO censor_state (key, value) VALUES ('panic_level', ?)",
            (str(new_level),)
        )
        await db.commit()
    return new_level


def detect_topics(text: str) -> list[str]:
    text_lower = text.lower()
    found = []
    for topic in FOREIGN_TOPICS | SUSPICIOUS_TOPICS | INNOCUOUS_TOPICS:
        if topic in text_lower:
            found.append(topic)
    return found
