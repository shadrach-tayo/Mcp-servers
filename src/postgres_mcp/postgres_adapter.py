import psycopg2
from psycopg2 import sql


class PostgresClient:
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
        self.cursor = None

    def connect(self):
        if self.conn is not None and not self.conn.closed:
            return
        self.conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
        )
        # Avoid leaving the connection stuck after a failed statement.
        self.conn.autocommit = True
        self.cursor = self.conn.cursor()

    def close(self):
        if self.cursor is not None:
            self.cursor.close()
            self.cursor = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _reset_if_needed(self):
        """Clear an aborted transaction so later queries can run."""
        if self.conn is None or self.conn.closed:
            self.conn = None
            self.cursor = None
            self.connect()
            return
        try:
            self.conn.rollback()
        except psycopg2.Error:
            self.close()
            self.connect()

    def _execute(self, query, params=None):
        self.connect()
        try:
            self.cursor.execute(query, params)
        except psycopg2.Error:
            self._reset_if_needed()
            raise

    def _fetch_dicts(self) -> list[dict]:
        columns = (
            [desc[0] for desc in self.cursor.description]
            if self.cursor.description
            else []
        )
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def execute(self, query: str) -> list[dict]:
        self._execute(query)
        return self._fetch_dicts()

    def fetch_tables(self) -> list[str]:
        self._execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        return [row[0] for row in self.cursor.fetchall()]

    def query_table(self, table: str, whereClause: str) -> list[dict]:
        # `query` is a WHERE clause / filter expression, not a full SQL statement.
        statement = sql.SQL("SELECT * FROM {} WHERE {}").format(
            sql.Identifier(table),
            sql.SQL(whereClause),
        )
        self._execute(statement)
        return self._fetch_dicts()

    def fetch_table_data(self, table: str) -> list[dict]:
        statement = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
        self._execute(statement)
        return self._fetch_dicts()

    def fetch_table_columns(self, table: str) -> list[str]:
        self._execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return [row[0] for row in self.cursor.fetchall()]

    def fetch_table_schema(self, table: str) -> list[dict]:
        self._execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        return [
            {"column_name": row[0], "data_type": row[1]}
            for row in self.cursor.fetchall()
        ]
