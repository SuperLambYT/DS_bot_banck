import sqlite3
from pathlib import Path
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"


def get_connection() -> sqlite3.Connection:
    """
    Создаёт подключение к SQLite с настройками, устраняющими ошибку 'database is locked'.
    """
    connection = sqlite3.connect(
        DB_PATH,
        timeout=30,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row

    # WAL: параллельное чтение и запись
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT,
                receiver_id TEXT,
                amount INTEGER NOT NULL CHECK(amount > 0),
                transaction_type TEXT NOT NULL,
                reason TEXT,
                sender_balance_after INTEGER,
                receiver_balance_after INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES accounts(user_id),
                FOREIGN KEY (receiver_id) REFERENCES accounts(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tx_sender
                ON transactions(sender_id);
            CREATE INDEX IF NOT EXISTS idx_tx_receiver
                ON transactions(receiver_id);
            CREATE INDEX IF NOT EXISTS idx_tx_created
                ON transactions(created_at);
            """
        )


def _ensure_account(connection: sqlite3.Connection, user_id: str) -> None:
    """Внутренняя функция: создаёт счёт в рамках уже открытого соединения."""
    connection.execute(
        """
        INSERT OR IGNORE INTO accounts (user_id, balance, created_at)
        VALUES (?, 0, ?)
        """,
        (user_id, datetime.now(timezone.utc).isoformat())
    )


def get_balance(user_id: int) -> int:
    """Баланс пользователя. Если счёта нет — создаёт его."""
    user_id = str(user_id)

    with get_connection() as connection:
        _ensure_account(connection, user_id)
        row = connection.execute(
            "SELECT balance FROM accounts WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["balance"]


def get_history(user_id: int, limit: int = 10):
    """Последние операции пользователя."""
    user_id = str(user_id)
    limit = max(1, min(limit, 100))

    with get_connection() as connection:
        _ensure_account(connection, user_id)
        return connection.execute(
            """
            SELECT
                id, sender_id, receiver_id, amount,
                transaction_type, reason,
                sender_balance_after, receiver_balance_after,
                created_at
            FROM transactions
            WHERE sender_id = ? OR receiver_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, user_id, limit)
        ).fetchall()


def transfer_money(
    sender_id: int,
    receiver_id: int,
    amount: int,
    reason: str = "Перевод между игроками"
):
    """
    Переводит деньги от одного пользователя другому.
    Возвращает (success, message_or_new_balance).
    """
    sender_id = str(sender_id)
    receiver_id = str(receiver_id)

    if sender_id == receiver_id:
        return False, "Нельзя переводить деньги самому себе."
    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")

            _ensure_account(connection, sender_id)
            _ensure_account(connection, receiver_id)

            sender = connection.execute(
                "SELECT balance FROM accounts WHERE user_id = ?",
                (sender_id,)
            ).fetchone()
            receiver = connection.execute(
                "SELECT balance FROM accounts WHERE user_id = ?",
                (receiver_id,)
            ).fetchone()

            if sender["balance"] < amount:
                connection.execute("ROLLBACK")
                return False, "Недостаточно средств."

            sender_new = sender["balance"] - amount
            receiver_new = receiver["balance"] + amount

            connection.execute(
                "UPDATE accounts SET balance = ? WHERE user_id = ?",
                (sender_new, sender_id)
            )
            connection.execute(
                "UPDATE accounts SET balance = ? WHERE user_id = ?",
                (receiver_new, receiver_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_id, receiver_id, amount, transaction_type,
                    reason, sender_balance_after, receiver_balance_after,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sender_id, receiver_id, amount, "transfer",
                    reason, sender_new, receiver_new, now
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


def add_money(
    user_id: int,
    amount: int,
    reason: str = "Начисление банком"
):
    """
    Начисляет деньги. Возвращает (success, new_balance_or_error).
    """
    user_id = str(user_id)

    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_account(connection, user_id)

            account = connection.execute(
                "SELECT balance FROM accounts WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            new_balance = account["balance"] + amount

            connection.execute(
                "UPDATE accounts SET balance = ? WHERE user_id = ?",
                (new_balance, user_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_id, receiver_id, amount, transaction_type,
                    reason, receiver_balance_after, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (None, user_id, amount, "bank_add",
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


def remove_money(
    user_id: int,
    amount: int,
    reason: str = "Списание банком"
):
    """
    Списывает деньги. Возвращает (success, new_balance_or_error).
    """
    user_id = str(user_id)

    if amount <= 0:
        return False, "Сумма должна быть больше нуля."

    now = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            _ensure_account(connection, user_id)

            account = connection.execute(
                "SELECT balance FROM accounts WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if account["balance"] < amount:
                connection.execute("ROLLBACK")
                return False, "На счёте недостаточно средств."

            new_balance = account["balance"] - amount

            connection.execute(
                "UPDATE accounts SET balance = ? WHERE user_id = ?",
                (new_balance, user_id)
            )

            connection.execute(
                """
                INSERT INTO transactions (
                    sender_id, receiver_id, amount, transaction_type,
                    reason, sender_balance_after, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, None, amount, "bank_remove",
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