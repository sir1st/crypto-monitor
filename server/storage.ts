import { and, desc, eq } from "drizzle-orm";
import {
  accounts, type Account, type InsertAccount,
  alerts, type Alert, type InsertAlert,
  strategies, type Strategy, type InsertStrategy,
} from "@shared/schema";
import { db } from "./db";

/**
 * Every database query lives here. The app is single-tenant and
 * unauthenticated, so nothing is scoped by owner.
 */
export class Storage {
  // -- Accounts ------------------------------------------------------------

  async getAllAccounts(): Promise<Account[]> {
    return db.select().from(accounts);
  }

  /** Active accounts that actually carry credentials. */
  async getTradableAccounts(exchange?: string): Promise<Account[]> {
    const all = await this.getAllAccounts();
    return all.filter((a) => {
      if (a.status !== "active" || !a.apiKey || !a.apiSecret) return false;
      if (exchange && a.exchange !== exchange) return false;
      return true;
    });
  }

  async getAccount(id: number): Promise<Account | undefined> {
    const [account] = await db.select().from(accounts).where(eq(accounts.id, id));
    return account;
  }

  async createAccount(account: InsertAccount): Promise<Account> {
    const [created] = await db.insert(accounts).values(account).returning();
    return created;
  }

  async updateAccount(id: number, updates: Partial<InsertAccount>): Promise<Account | undefined> {
    const [updated] = await db
      .update(accounts)
      .set({ ...updates, lastSync: new Date() })
      .where(eq(accounts.id, id))
      .returning();
    return updated;
  }

  async deleteAccount(id: number): Promise<boolean> {
    const result = await db.delete(accounts).where(eq(accounts.id, id)).returning();
    return result.length > 0;
  }

  // -- Alerts --------------------------------------------------------------

  async getAlerts(status?: string): Promise<Alert[]> {
    const query = db.select().from(alerts);
    const rows = status
      ? await query.where(eq(alerts.status, status)).orderBy(desc(alerts.createdAt))
      : await query.orderBy(desc(alerts.createdAt));
    return rows;
  }

  async getActiveAlerts(): Promise<Alert[]> {
    return db.select().from(alerts).where(eq(alerts.status, "active"));
  }

  async getAlert(id: number): Promise<Alert | undefined> {
    const [alert] = await db.select().from(alerts).where(eq(alerts.id, id));
    return alert;
  }

  async createAlert(alert: InsertAlert): Promise<Alert> {
    const [created] = await db.insert(alerts).values(alert).returning();
    return created;
  }

  async markAlertTriggered(id: number, price: number): Promise<Alert | undefined> {
    const [updated] = await db
      .update(alerts)
      .set({ status: "triggered", triggeredAt: new Date(), triggeredPrice: price })
      .where(eq(alerts.id, id))
      .returning();
    return updated;
  }

  /** Only an active alert can be cancelled, so a second call reports false. */
  async cancelAlert(id: number): Promise<boolean> {
    const result = await db
      .update(alerts)
      .set({ status: "cancelled" })
      .where(and(eq(alerts.id, id), eq(alerts.status, "active")))
      .returning();
    return result.length > 0;
  }

  async deleteAlert(id: number): Promise<boolean> {
    const result = await db.delete(alerts).where(eq(alerts.id, id)).returning();
    return result.length > 0;
  }

  // -- Strategies ----------------------------------------------------------

  async getStrategies(): Promise<Strategy[]> {
    return db.select().from(strategies).orderBy(desc(strategies.updatedAt));
  }

  async getStrategy(id: number): Promise<Strategy | undefined> {
    const [strategy] = await db.select().from(strategies).where(eq(strategies.id, id));
    return strategy;
  }

  async createStrategy(strategy: InsertStrategy): Promise<Strategy> {
    const [created] = await db.insert(strategies).values(strategy).returning();
    return created;
  }

  async updateStrategy(
    id: number,
    updates: Partial<InsertStrategy>,
  ): Promise<Strategy | undefined> {
    const [updated] = await db
      .update(strategies)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(strategies.id, id))
      .returning();
    return updated;
  }

  async deleteStrategy(id: number): Promise<boolean> {
    const result = await db.delete(strategies).where(eq(strategies.id, id)).returning();
    return result.length > 0;
  }
}

export const storage = new Storage();
