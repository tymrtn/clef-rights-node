import { createServer as createHttpServer } from "node:http";
import { fileURLToPath } from "node:url";
import { createServer as createViteServer, loadConfigFromFile } from "vite";
import { expect, it } from "vitest";

it("routes authentication, node API and legacy API requests through the default development server", async () => {
  const received: string[] = [];
  const backend = createHttpServer((req, res) => {
    received.push(`${req.method} ${req.url}`);
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ source: "synthetic-backend" }));
  });
  await new Promise<void>(resolve => backend.listen(0, "127.0.0.1", resolve));
  const oldTarget = process.env.VITE_API_PROXY_TARGET;
  const address = backend.address() as { port: number };
  process.env.VITE_API_PROXY_TARGET = `http://127.0.0.1:${address.port}`;
  let web: Awaited<ReturnType<typeof createViteServer>> | undefined;
  try {
    const configPath = fileURLToPath(new URL("../../vite.config.ts", import.meta.url));
    const loaded = await loadConfigFromFile({ command: "serve", mode: "development" }, configPath);
    web = await createViteServer({ ...loaded!.config, configFile: false, logLevel: "silent", server: { ...loaded!.config.server, host: "127.0.0.1", port: 0, hmr: false } });
    await web.listen();
    const webAddress = web.httpServer!.address() as { port: number };
    for (const [method, path] of [["GET", "/v1/node/info"], ["POST", "/auth/invite"], ["GET", "/api/health"]]) {
      const response = await fetch(`http://127.0.0.1:${webAddress.port}${path}`, { method });
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ source: "synthetic-backend" });
    }
    expect(received).toEqual(["GET /v1/node/info", "POST /auth/invite", "GET /health"]);
  } finally {
    if (web) await web.close();
    await new Promise<void>(resolve => backend.close(() => resolve()));
    if (oldTarget === undefined) delete process.env.VITE_API_PROXY_TARGET;
    else process.env.VITE_API_PROXY_TARGET = oldTarget;
  }
});
