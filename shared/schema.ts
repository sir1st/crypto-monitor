import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

/**
 * All tables live in a single local SQLite file (see server/db.ts). Timestamps
 * are stored as unix epoch integers and surfaced as JS `Date`s by Drizzle.
 *
 * There are no users: the app is single-tenant and unauthenticated, so nothing
 * is scoped by owner. See the security note in README.md.
 */

const now = () => new Date();

export const accounts = sqliteTable("accounts", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  exchange: text("exchange").notNull(), // "bybit"
  apiKey: text("api_key").notNull(),
  apiSecret: text("api_secret").notNull(),
  status: text("status").default("active").notNull(), // "active" | "inactive"
  lastSync: integer("last_sync", { mode: "timestamp" }),
  createdAt: integer("created_at", { mode: "timestamp" }).$defaultFn(now).notNull(),
});

export const alerts = sqliteTable("alerts", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  symbol: text("symbol").notNull(), // e.g. "BTCUSDT"
  direction: text("direction").notNull(), // "above" | "below"
  price: real("price").notNull(),
  note: text("note"),
  status: text("status").default("active").notNull(), // "active" | "triggered" | "cancelled"
  triggeredAt: integer("triggered_at", { mode: "timestamp" }),
  triggeredPrice: real("triggered_price"),
  createdAt: integer("created_at", { mode: "timestamp" }).$defaultFn(now).notNull(),
});

export const strategies = sqliteTable("strategies", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  description: text("description"),
  symbol: text("symbol").notNull(),
  timeframe: text("timeframe").default("60").notNull(), // Bybit kline interval
  /** Free-form JSON: entry/exit rules, risk parameters, whatever the author needs. */
  rules: text("rules", { mode: "json" }).$type<Record<string, unknown>>(),
  status: text("status").default("draft").notNull(), // "draft" | "active" | "paused"
  createdAt: integer("created_at", { mode: "timestamp" }).$defaultFn(now).notNull(),
  updatedAt: integer("updated_at", { mode: "timestamp" }).$defaultFn(now).notNull(),
});

// ---------------------------------------------------------------------------
// Insert schemas
// ---------------------------------------------------------------------------

export const insertAccountSchema = createInsertSchema(accounts).pick({
  name: true,
  exchange: true,
  apiKey: true,
  apiSecret: true,
  status: true,
});

export const insertAlertSchema = createInsertSchema(alerts)
  .pick({ note: true })
  .extend({
    symbol: z.string().min(3).max(32).toUpperCase(),
    direction: z.enum(["above", "below"]),
    price: z.number().positive(),
    note: z.string().max(500).optional(),
  });

export const insertStrategySchema = createInsertSchema(strategies)
  .pick({ description: true })
  .extend({
    name: z.string().min(1).max(120),
    description: z.string().max(2000).optional(),
    symbol: z.string().min(3).max(32).toUpperCase(),
    timeframe: z.string().default("60"),
    rules: z.record(z.unknown()).optional(),
    status: z.enum(["draft", "active", "paused"]).default("draft"),
  });

export const updateStrategySchema = insertStrategySchema.partial();

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Account = typeof accounts.$inferSelect;
export type InsertAccount = z.infer<typeof insertAccountSchema>;

export type Alert = typeof alerts.$inferSelect;
export type InsertAlert = z.infer<typeof insertAlertSchema>;

export type Strategy = typeof strategies.$inferSelect;
export type InsertStrategy = z.infer<typeof insertStrategySchema>;

/** A single OHLCV candle, normalised from the exchange payload. */
export interface Candle {
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
}
