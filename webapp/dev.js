// Local server that behaves like the Vercel deployment: static pages with clean URLs and api/*.js
// functions (exported GET/POST handlers). Run: SESSION_SECRET=… GITHUB_CLIENT_ID=… node dev.js
import { createServer } from "node:http";
import { readFile, access } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = dirname(fileURLToPath(import.meta.url));
const PAGES = {
  "/": "index.html", "/index": "index.html", "/dashboard": "dashboard.html",
  "/docs": "docs.html", "/privacy": "privacy.html", "/terms": "terms.html", "/cookies": "cookies.html",
};
const ASSETS = {
  "/consent.js": "text/javascript; charset=utf-8",
  "/llms.txt": "text/markdown; charset=utf-8",
  "/skill.md": "text/markdown; charset=utf-8",
};
const REDIRECTS = { "/doc": "/docs" };

/** Route a Web Request the way Vercel does for this project. */
export async function app(request) {
  const { pathname } = new URL(request.url);
  if (pathname.startsWith("/api/")) {
    const file = join(ROOT, pathname.replace(/\/+$/, "") + ".js");
    if (!file.startsWith(join(ROOT, "api")) || !(await access(file).then(() => true, () => false))) {
      return Response.json({ error: "Not found" }, { status: 404 });
    }
    const handler = (await import(pathToFileURL(file).href))[request.method];
    return handler ? handler(request) : Response.json({ error: "Method not allowed" }, { status: 405 });
  }
  if (REDIRECTS[pathname]) return new Response(null, { status: 308, headers: { Location: REDIRECTS[pathname] } });
  if (ASSETS[pathname]) {
    return new Response(await readFile(join(ROOT, pathname)), { headers: { "Content-Type": ASSETS[pathname] } });
  }
  const page = PAGES[pathname.replace(/\.html$/, "")];
  if (!page) return new Response("Not found", { status: 404 });
  return new Response(await readFile(join(ROOT, page)), { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

export function serve(port) {
  return createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const request = new Request(`http://${req.headers.host}${req.url}`, {
      method: req.method,
      headers: req.headers,
      body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks),
    });
    try {
      const response = await app(request);
      const headers = Object.fromEntries([...response.headers].filter(([k]) => k !== "set-cookie"));
      const cookies = response.headers.getSetCookie();
      if (cookies.length) headers["set-cookie"] = cookies;
      res.writeHead(response.status, headers);
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch (err) {
      console.error(err);
      res.writeHead(500).end("Internal error");
    }
  }).listen(port, () => console.log(`skylls webapp on http://localhost:${port}`));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) serve(Number(process.env.PORT) || 3901);
