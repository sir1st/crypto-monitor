import express, { type Express } from "express";
import fs from "fs";
import path, { dirname } from "path";
import { fileURLToPath } from "url";
import { createLogger, createServer as createViteServer } from "vite";
import type { Server } from "http";
import viteConfig from "../vite.config";

const __dirname = dirname(fileURLToPath(import.meta.url));
const viteLogger = createLogger();

export function log(message: string, source = "express") {
  const time = new Date().toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
  console.log(`${time} [${source}] ${message}`);
}

/**
 * Mounts Vite in middleware mode. Registered last, because its catch-all route
 * would otherwise swallow the API.
 */
export async function setupVite(app: Express, server: Server) {
  const vite = await createViteServer({
    ...viteConfig,
    configFile: false,
    customLogger: {
      ...viteLogger,
      error: (msg, options) => {
        viteLogger.error(msg, options);
        process.exit(1);
      },
    },
    server: { middlewareMode: true, hmr: { server } },
    appType: "custom",
  });

  app.use(vite.middlewares);

  app.use("*", async (req, res, next) => {
    try {
      const templatePath = path.resolve(__dirname, "..", "client", "index.html");
      // Read from disk each time so edits to index.html are picked up.
      const template = await fs.promises.readFile(templatePath, "utf-8");
      const page = await vite.transformIndexHtml(req.originalUrl, template);
      res.status(200).set({ "Content-Type": "text/html" }).end(page);
    } catch (error) {
      vite.ssrFixStacktrace(error as Error);
      next(error);
    }
  });
}

export function serveStatic(app: Express) {
  const distPath = path.resolve(__dirname, "public");

  if (!fs.existsSync(distPath)) {
    throw new Error(`Client build not found at ${distPath}. Run \`npm run build\` first.`);
  }

  app.use(express.static(distPath));
  app.use("*", (_req, res) => res.sendFile(path.resolve(distPath, "index.html")));
}
