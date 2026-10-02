import sqlite3
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"

MAX_CHARACTERS_PER_USER = 2


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, name),
                FOREIGN KEY (user_id) REFERENCES accounts(user_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_characters_user
                ON characters(user_id);

            CREATE TABLE IF NOT EXISTS bank_accounts (
                character_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                sender_character_id INTEGER,
                receiver_character_id INTEGER,

                sender_name TEXT,
                receiver_name TEXT,

                amount INTEGER NOT NULL CHECK(amount > 0),
                transaction_type TEXT NOT NULL,
                reason TEXT,

                sender_balance_after INTEGER,
                receiver_balance_after INTEGER,

                created_at TEXT NOT NULL,

                FOREIGN KEY (sender_character_id)
                    REFERENCES characters(id) ON DELETE SET NULL,
                FOREIGN KEY (receiver_character_id)
                    REFERENCES characters(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tx_sender
                ON transactions(sender_character_id);
            CREATE INDEX IF NOT EXISTS idx_tx_receiver
                ON transactions(receiver_character_id);
            CREATE INDEX IF NOT EXISTS idx_tx_created
                ON transactions(created_at);
            """
        )



# АККАУНТЫ ИГРОКОВ

def _ensure_user(connection: sqlite3.Connection, user_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO accounts (user_id, created_at) VALUES (?, ?)",
        (user_id, datetime.now(timezone.utc).isoformat())
    )



# ПЕРСОНАЖИ

def create_character(user_id: int, name: str):
    """
    Создаёт персонажа. Возвращает (success, character_id_or_error).
    """
    user_id = str(user_id)
    name = name.strip()

    if not name:
        return False, "Имя персонажа не может быть пустым."
    if len(name) > 32:
        return False, "Имя персонажа слишком длинное (макс. 32)."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_user(connection, user_id)

            count = connection.execute(
                "SELECT COUNT(*) AS c FROM characters WHERE user_id = ?",
                (user_id,)
            ).fetchone()["c"]

            if count >= MAX_CHARACTERS_PER_USER:
                connection.execute("ROLLBACK")
                return False, (
                    f"У игрока уже {MAX_CHARACTERS_PER_USER} персонажа. "
                    f"Удалите одного, чтобы создать нового."
                )

            exists = connection.execute(
                "SELECT 1 FROM characters WHERE user_id = ? AND name = ?",
                (user_id, name)
            ).fetchone()
            if exists:
                connection.execute("ROLLBACK")
                return False, f"Персонаж с именем «{name}» уже существует."

            cursor = connection.execute(
                """
                INSERT INTO characters (user_id, name, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, name, now)
            )
            character_id = cursor.lastrowid

            connection.execute(
                """
                INSERT INTO bank_accounts (character_id, balance, created_at)
                VALUES (?, 0, ?)
                """,
                (character_id, now)
            )

            connection.execute("COMMIT")
            return True, character_id

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise


# УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЕЙ

def delete_character(user_id: int, name: str):
    user_id = str(user_id)
    name = name.strip()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                "SELECT id FROM characters WHERE user_id = ? AND name = ?",
                (user_id, name)
            ).fetchone()

            if not row:
                connection.execute("ROLLBACK")
                return False, f"Персонаж «{name}» не найден."

            # bank_accounts удалится каскадом;
            # transactions обнулят ссылки (ON DELETE SET NULL),
            # но сохранят sender_name / receiver_name.
            connection.execute(
                "DELETE FROM characters WHERE id = ?",
                (row["id"],)
            )

            connection.execute("COMMIT")
            return True, f"Персонаж «{name}» удалён."

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise


def get_characters(user_id: int):
    """Список персонажей игрока (id, name)."""
    user_id = str(user_id)
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, name, created_at
            FROM characters
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,)
        ).fetchall()


def get_character(user_id: int, name: str):
    """Персонаж по имени. None, если не найден."""
    user_id = str(user_id)
    name = name.strip()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, user_id, name
            FROM characters
            WHERE user_id = ? AND name = ?
            """,
            (user_id, name)
        ).fetchone()


def get_character_by_id(character_id: int):
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, user_id, name FROM characters WHERE id = ?",
            (character_id,)
        ).fetchone()


def get_all_characters():
    """Все персонажи (для админского просмотра)."""
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT c.id, c.name, c.user_id, c.created_at, b.balance
            FROM characters c
            LEFT JOIN bank_accounts b ON b.character_id = c.id
            ORDER BY c.user_id, c.id
            """
        ).fetchall()


def find_character_by_name(name: str):
    """
    Ищет персонажа по имени среди всех игроков.
    Возвращает список строк (может быть > 1 при коллизии имён).
    """
    name = name.strip()
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT c.id, c.user_id, c.name
            FROM characters c
            WHERE c.name = ?
            """,
            (name,)
        ).fetchall()


# БАЛАНС

def get_balance(character_id: int) -> int:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT balance FROM bank_accounts WHERE character_id = ?",
            (character_id,)
        ).fetchone()
        return row["balance"] if row else 0


def get_balance_for_name(user_id: int, name: str):
    """Возвращает (balance, error)."""
    ch = get_character(user_id, name)
    if not ch:
        return None, f"У игрока нет персонажа с именем «{name}»."
    return get_balance(ch["id"]), None



# ИСТОРИЯ

def get_history(character_id: int, limit: int = 10):
    limit = max(1, min(limit, 100))
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id, amount, transaction_type, reason,
                sender_balance_after, receiver_balance_after,
                created_at,
                sender_character_id, receiver_character_id,
                sender_name, receiver_name
            FROM transactions
            WHERE sender_character_id = ?
               OR receiver_character_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (character_id, character_id, limit)
        ).fetchall()



# ПЕРЕВОДЫ

def transfer_money(
    sender_character_id: int,
    receiver_character_id: int,
    amount: int,
    reason: str = "Перевод между персонажами"
):
    if sender_character_id == receiver_character_id:
        return False, "Нельзя переводить самому себе."
    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            sender_ch = connection.execute(
                "SELECT name FROM characters WHERE id = ?",
                (sender_character_id,)
            ).fetchone()
            receiver_ch = connection.execute(
                "SELECT name FROM characters WHERE id = ?",
                (receiver_character_id,)
            ).fetchone()

            if not sender_ch or not receiver_ch:
                connection.execute("ROLLBACK")
                return False, "Один из персонажей не найден."

            sender = connection.execute(
                "SELECT balance FROM bank_accounts WHERE character_id = ?",
                (sender_character_id,)
            ).fetchone()
            receiver = connection.execute(
                "SELECT balance FROM bank_accounts WHERE character_id = ?",
                (receiver_character_id,)
            ).fetchone()

            if not sender or not receiver:
                connection.execute("ROLLBACK")
                return False, "Один из счетов не найден."

            if sender["balance"] < amount:
                connection.execute("ROLLBACK")
                return False, "Недостаточно средств."

            sender_new = sender["balance"] - amount
            receiver_new = receiver["balance"] + amount

            connection.execute(
                "UPDATE bank_accounts SET balance = ? WHERE character_id = ?",
                (sender_new, sender_character_id)
            )
            connection.execute(
                "UPDATE bank_accounts SET balance = ? WHERE character_id = ?",
                (receiver_new, receiver_character_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_character_id, receiver_character_id,
                    sender_name, receiver_name,
                    amount, transaction_type, reason,
                    sender_balance_after, receiver_balance_after,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sender_character_id, receiver_character_id,
                    sender_ch["name"], receiver_ch["name"],
                    amount, "transfer", reason,
                    sender_new, receiver_new, now
                )
            )

            connection.execute("COMMIT")
            return True, sender_new

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise



# БАНКОВСКИЕ ОПЕРАЦИИ

def add_money(character_id: int, amount: int, reason: str = "Начисление банком"):
    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            account = connection.execute(
                "SELECT balance FROM bank_accounts WHERE character_id = ?",
                (character_id,)
            ).fetchone()

            if not account:
                connection.execute("ROLLBACK")
                return False, "Счёт персонажа не найден."

            new_balance = account["balance"] + amount

            connection.execute(
                "UPDATE bank_accounts SET balance = ? WHERE character_id = ?",
                (new_balance, character_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_character_id, receiver_character_id,
                    amount, transaction_type, reason,
                    receiver_balance_after, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (None, character_id, amount, "bank_add",
                 reason, new_balance, now)
            )

            connection.execute("COMMIT")
            return True, new_balance

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise


# СПИСАНИЕ

def remove_money(character_id: int, amount: int, reason: str = "Списание банком"):
    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            ch = connection.execute(
                "SELECT name FROM characters WHERE id = ?",
                (character_id,)
            ).fetchone()
            if not ch:
                connection.execute("ROLLBACK")
                return False, "Персонаж не найден."

            account = connection.execute(
                "SELECT balance FROM bank_accounts WHERE character_id = ?",
                (character_id,)
            ).fetchone()
            if not account:
                connection.execute("ROLLBACK")
                return False, "Счёт персонажа не найден."

            if account["balance"] < amount:
                connection.execute("ROLLBACK")
                return False, "На счёте недостаточно средств."

            new_balance = account["balance"] - amount

            connection.execute(
                "UPDATE bank_accounts SET balance = ? WHERE character_id = ?",
                (new_balance, character_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_character_id, receiver_character_id,
                    sender_name, receiver_name,
                    amount, transaction_type, reason,
                    sender_balance_after, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (character_id, None, ch["name"], None,
                 amount, "bank_remove", reason,
                 new_balance, now)
            )

            connection.execute("COMMIT")
            return True, new_balance

        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise