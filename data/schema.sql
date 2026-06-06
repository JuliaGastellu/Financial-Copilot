-- AI Financial Copilot — SQLite schema
-- All tables use CREATE TABLE IF NOT EXISTS for idempotent execution.

CREATE TABLE IF NOT EXISTS profiles (
    user_id     TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source      TEXT,
    content     TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    sha256      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id  TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    decision_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id    ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_decisions_user_id ON decisions(user_id);
