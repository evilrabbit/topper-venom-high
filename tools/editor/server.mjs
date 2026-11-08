// Local colorway editor server (no dependencies).
//   node tools/editor/server.mjs        ->  http://localhost:8010/tools/editor/
// Serves the project root and accepts saves from the editor:
//   POST /api/save-texture  (image/webp)  -> models/navy-color.webp  (+ copy in tools/editor/history/)
//   POST /api/state/parts   (json)        -> tools/editor/state/parts.json
//   POST /api/state/paint   (image/png)   -> tools/editor/state/paint.png
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PORT = Number(process.env.PORT || 8010);
const MAX = 64 * 1024 * 1024;
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.png': 'image/png', '.webp': 'image/webp',
  '.glb': 'model/gltf-binary', '.bin': 'application/octet-stream', '.svg': 'image/svg+xml', '.woff2': 'font/woff2',
  '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []; let n = 0;
    req.on('data', (c) => { n += c.length; if (n > MAX) { reject(new Error('too large')); req.destroy(); } else chunks.push(c); });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

const SAVES = {
  '/api/save-texture': async (buf) => {
    if (buf.subarray(0, 4).toString() !== 'RIFF' || buf.subarray(8, 12).toString() !== 'WEBP') throw new Error('not a webp');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    await fs.mkdir(path.join(ROOT, 'tools/editor/history'), { recursive: true });
    await fs.writeFile(path.join(ROOT, 'tools/editor/history', `navy-color-${stamp}.webp`), buf);
    const dst = path.join(ROOT, 'models/navy-color.webp');
    await fs.writeFile(dst + '.tmp', buf);
    await fs.rename(dst + '.tmp', dst);           // atomic swap so the site never reads half a file
    return { wrote: 'models/navy-color.webp', bytes: buf.length };
  },
  '/api/save-material': async (buf) => {
    if (buf.subarray(0, 4).toString() !== 'RIFF' || buf.subarray(8, 12).toString() !== 'WEBP') throw new Error('not a webp');
    const dst = path.join(ROOT, 'models/navy-material.webp');
    await fs.writeFile(dst + '.tmp', buf); await fs.rename(dst + '.tmp', dst);
    return { wrote: 'models/navy-material.webp', bytes: buf.length };
  },
  '/api/state/parts': async (buf) => {
    JSON.parse(buf.toString());                    // validate
    await fs.mkdir(path.join(ROOT, 'tools/editor/state'), { recursive: true });
    await fs.writeFile(path.join(ROOT, 'tools/editor/state/parts.json'), buf);
    return { wrote: 'tools/editor/state/parts.json' };
  },
  '/api/state/paint': async (buf) => {
    if (buf.subarray(1, 4).toString() !== 'PNG') throw new Error('not a png');
    await fs.mkdir(path.join(ROOT, 'tools/editor/state'), { recursive: true });
    await fs.writeFile(path.join(ROOT, 'tools/editor/state/paint.png'), buf);
    return { wrote: 'tools/editor/state/paint.png', bytes: buf.length };
  },
};

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  try {
    if (req.method === 'POST') {
      const fn = SAVES[url.pathname];
      if (!fn) { res.writeHead(404).end('no such endpoint'); return; }
      const out = await fn(await readBody(req));
      console.log(new Date().toLocaleTimeString(), 'saved', JSON.stringify(out));
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(out));
      return;
    }
    let p = decodeURIComponent(url.pathname);
    if (p.endsWith('/')) p += 'index.html';
    const file = path.resolve(ROOT, '.' + p);
    if (!file.startsWith(ROOT + path.sep)) { res.writeHead(403).end(); return; }
    const data = await fs.readFile(file);
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' }).end(data);
  } catch (e) {
    const code = e.code === 'ENOENT' ? 404 : 500;
    if (code === 500) console.error(e);
    res.writeHead(code, { 'content-type': 'text/plain' }).end(code === 404 ? 'not found' : String(e.message || e));
  }
}).listen(PORT, () => console.log(`colorway editor: http://localhost:${PORT}/tools/editor/`));
