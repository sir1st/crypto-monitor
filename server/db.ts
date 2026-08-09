import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import fs from "fs";
import path from "path";
import * as schema from "@shared/schema";

/**
 * Local, file-backed SQLite database. No server to provision and nothing to
 * configure: point DATABASE_PATH somewhere else if you want, otherwise the
 * database lands in ./data/vale.db and is created on first boot.
 */
const dbPath = process.env.DATABASE_PATH
  ? path.resolve(process.env.DATABASE_PATH)
  : path.resolve(process.cwd(), "data", "vale.db");

fs.mkdirSync(path.dirname(dbPath), { recursive: true });

export const sqlite = new Database(dbPath);

// WAL lets the MCP server and the web server read concurrently without locking.
sqlite.pragma("journal_mode = WAL");
sqlite.pragma("foreign_keys = ON");

export const db = drizzle(sqlite, { schema });

/**
 * Creates the schema if it is missing. Called once at startup so a fresh clone
 * runs without a migration step; `npm run db:push` remains available for
 * iterating on shared/schema.ts.
 *
 * Note this is `CREATE TABLE IF NOT EXISTS`: removing a table here does not drop
 * it from an existing database file.
 */
export function initialiseSchema() {
  sqlite.exec(`
    CREATE TABLE IF NOT EXISTS accounts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      exchange TEXT NOT NULL,
      api_key TEXT NOT NULL,
      api_secret TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      last_sync INTEGER,
      created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS alerts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol TEXT NOT NULL,
      direction TEXT NOT NULL,
      price REAL NOT NULL,
      note TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      triggered_at INTEGER,
      triggered_price REAL,
      created_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS strategies (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      description TEXT,
      symbol TEXT NOT NULL,
      timeframe TEXT NOT NULL DEFAULT '60',
      rules TEXT,
      status TEXT NOT NULL DEFAULT 'draft',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
  `);
}

export const databaseFile = dbPath;
