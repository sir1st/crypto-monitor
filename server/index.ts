import dotenv from "dotenv";

// Must run before anything reads process.env.
dotenv.config();

import express, { type NextFunction, type Request, type Response } from "express";
import { registerRoutes } from "./routes";
import { log, serveStatic, setupVite } from "./vite";
import { databaseFile, initialiseSchema } from "./db";
import { isAiConfigured } from "./ai";

async function bootstrap() {
  initialiseSchema();
  log(`database ready at ${databaseFile}`);
  log(`ai analysis ${isAiConfigured() ? "enabled" : "disabled (no provider key set)"}`);

  const app = express();
  app.use(express.json({ limit: "1mb" }));
  app.use(express.urlencoded({ extended: false }));

  // Request log for API calls only; bodies are omitted so exchange credentials
  // never reach the log.
  app.use((req, res, next) => {
    if (!req.path.startsWith("/api")) return next();

    const start = Date.now();
    res.on("finish", () => {
      log(`${req.method} ${req.path} ${res.statusCode} in ${Date.now() - start}ms`);
    });
    next();
  });

  const server = await registerRoutes(app);

  app.use((err: Error & { status?: number }, _req: Request, res: Response, next: NextFunction) => {
    console.error("Unhandled error:", err);
    if (res.headersSent) return next(err);
    res.status(err.status ?? 500).json({ error: err.message ?? "Internal server error" });
  });

  // Vite owns the catch-all route, so it must be registered after the API.
  if (app.get("env") === "development") {
    await setupVite(app, server);
  } else {
    serveStatic(app);
  }

  const port = Number(process.env.PORT ?? 5000);
  // Loopback by default. The API is unauthenticated, so binding to 0.0.0.0
  // exposes exchange balances and account management to the whole network.
  const host = process.env.HOST ?? "127.0.0.1";

  server.listen(port, host, () => {
    log(`serving on http://${host}:${port}`);
    if (host !== "127.0.0.1" && host !== "localhost") {
      log(`WARNING: bound to ${host} with no authentication — put a proxy with access control in front`);
    }
  });
}

bootstrap().catch((error) => {
  console.error("Failed to start:", error);
  process.exit(1);
});
