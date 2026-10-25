import json
import sqlite3


class Storage:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))')
        self.db.commit()

    def put(self, kind, key, data):
        self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (kind, key, json.dumps(data)))
        self.db.commit()

    def claim(self, key, data):
        try:
            self.db.execute('INSERT INTO records VALUES (?,?,?)', ('intent', key, json.dumps(data)))
            self.db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get(self, kind, key, default=None):
        row = self.db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def all(self, kind):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM records WHERE kind=? ORDER BY rowid', (kind,))]
