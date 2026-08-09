import { defineConfig } from "drizzle-kit";
import path from "path";

const dbPath = process.env.DATABASE_PATH
  ? path.resolve(process.env.DATABASE_PATH)
  : path.resolve(process.cwd(), "data", "vale.db");

export default defineConfig({
  out: "./migrations",
  schema: "./shared/schema.ts",
  dialect: "sqlite",
  dbCredentials: {
    url: dbPath,
  },
});
