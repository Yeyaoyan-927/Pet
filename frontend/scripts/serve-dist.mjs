/**
 * serve-dist.mjs — 生产构建(dist)静态服务 + /api 反代到后端
 *
 * 用途：cpolar 等内网穿透场景下，用「单端口」对外提供完整应用。
 *       Vite dev server 对外部域名返回 403（主机检查），不适合直接穿透，
 *       因此穿透时统一走本服务（dist + 反代）。
 *
 * 用法：
 *   node scripts/serve-dist.mjs [端口]        # 默认 8080
 *   API_TARGET=http://127.0.0.1:8000 node scripts/serve-dist.mjs 8080
 *
 * 特性：
 *   - dist 静态资源 + SPA 兜底（/user/home 等前端路由回 index.html）
 *   - /api/* 流式反代到后端（SSE 逐字输出不受影响）
 *   - 文本类资源 gzip 压缩；hash 资源长缓存，index.html 不缓存
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../dist');
const PORT = Number(process.argv[2] || process.env.SERVE_PORT || 8080);
const API_TARGET = process.env.API_TARGET || 'http://127.0.0.1:8000';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
};
const GZIP_TYPES = new Set(['.html', '.js', '.mjs', '.css', '.json', '.map', '.svg', '.txt']);

const server = http.createServer((req, res) => {
  // ---------- /api/* 反代到后端（流式，SSE 兼容） ----------
  if (req.url === '/api' || req.url.startsWith('/api/')) {
    const target = new URL(API_TARGET);
    const headers = { ...req.headers };
    headers.host = target.host;
    delete headers.connection;

    const proxyReq = http.request(
      {
        hostname: target.hostname,
        port: target.port || 80,
        path: req.url,
        method: req.method,
        headers,
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
        proxyRes.pipe(res);
      },
    );
    proxyReq.on('error', (err) => {
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
      }
      res.end(JSON.stringify({ code: 502, message: `后端不可达: ${err.message}` }));
    });
    req.pipe(proxyReq);
    return;
  }

  // ---------- dist 静态资源 ----------
  const urlPath = decodeURIComponent((req.url || '/').split('?')[0]);
  const filePath = path.normalize(path.join(ROOT, urlPath));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403).end('Forbidden');
    return;
  }

  const sendFile = (fp) => {
    const ext = path.extname(fp).toLowerCase();
    const headers = {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      // hash 资源长缓存；index.html 每次校验，保证发布后立即生效
      'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=31536000, immutable',
    };
    const useGzip = GZIP_TYPES.has(ext) && (req.headers['accept-encoding'] || '').includes('gzip');
    if (useGzip) headers['Content-Encoding'] = 'gzip';
    res.writeHead(200, headers);
    const stream = fs.createReadStream(fp);
    (useGzip ? stream.pipe(zlib.createGzip()) : stream).pipe(res);
  };

  fs.stat(filePath, (err, stat) => {
    if (!err && stat.isFile()) {
      sendFile(filePath);
      return;
    }
    // SPA 兜底：前端路由一律回 index.html
    const indexFile = path.join(ROOT, 'index.html');
    if (fs.existsSync(indexFile)) sendFile(indexFile);
    else res.writeHead(404).end('dist 未构建，请先 npm run build');
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[serve-dist] 静态目录: ${ROOT}`);
  console.log(`[serve-dist] API 反代 : ${API_TARGET} -> /api/*`);
  console.log(`[serve-dist] 监听     : http://0.0.0.0:${PORT}`);
});
