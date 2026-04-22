// Vite ビルド成果物 (dist) を Basic 認証付きで配信する本番サーバー
// Render の Web Service (Node) で起動する想定
//
// 必須環境変数:
//   BASIC_AUTH_USER
//   BASIC_AUTH_PASSWORD
// 任意環境変数:
//   PORT           (Render が自動設定。ローカルは 3000)
//   AUTH_REALM     (WWW-Authenticate realm 文字列)
//   SKIP_AUTH_PATHS(カンマ区切り。ヘルスチェック等を除外したい場合のみ)

import express from 'express';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST_DIR = path.join(__dirname, 'dist');
const PORT = Number(process.env.PORT) || 3000;
const REALM = process.env.AUTH_REALM || 'Staff Only';

const EXPECTED_USER = process.env.BASIC_AUTH_USER;
const EXPECTED_PASS = process.env.BASIC_AUTH_PASSWORD;
const AUTH_CONFIGURED =
    typeof EXPECTED_USER === 'string' &&
    EXPECTED_USER.length > 0 &&
    typeof EXPECTED_PASS === 'string' &&
    EXPECTED_PASS.length > 0;

const SKIP_AUTH_PATHS = (process.env.SKIP_AUTH_PATHS || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

// 起動時チェック: dist が存在しなければ即エラー終了
if (!fs.existsSync(DIST_DIR) || !fs.existsSync(path.join(DIST_DIR, 'index.html'))) {
    console.error(`[server] dist not found at ${DIST_DIR}. Run "npm run build" first.`);
    process.exit(1);
}

if (!AUTH_CONFIGURED) {
    console.error(
        '[server] BASIC_AUTH_USER / BASIC_AUTH_PASSWORD are not set. ' +
        'All requests will be denied (fail closed).',
    );
}

// 定数時間比較（タイミング攻撃対策）
function safeEqual(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string') return false;
    if (a.length !== b.length) return false;
    let result = 0;
    for (let i = 0; i < a.length; i++) {
        result |= a.charCodeAt(i) ^ b.charCodeAt(i);
    }
    return result === 0;
}

function sendUnauthorized(res) {
    res.set('WWW-Authenticate', `Basic realm="${REALM}", charset="UTF-8"`);
    res.set('Cache-Control', 'no-store');
    res.status(401).type('text/plain').send('Authentication required');
}

function basicAuth(req, res, next) {
    // 除外パス（例: /healthz）
    if (SKIP_AUTH_PATHS.includes(req.path)) {
        return next();
    }

    // Fail closed: 環境変数が無ければ全拒否
    if (!AUTH_CONFIGURED) {
        res.set('Cache-Control', 'no-store');
        return res.status(503).type('text/plain').send('Service unavailable: auth not configured');
    }

    const header = req.headers['authorization'] || '';
    if (typeof header !== 'string' || !header.toLowerCase().startsWith('basic ')) {
        return sendUnauthorized(res);
    }

    const encoded = header.slice(6).trim();
    let decoded;
    try {
        decoded = Buffer.from(encoded, 'base64').toString('utf-8');
    } catch {
        return sendUnauthorized(res);
    }

    const sepIdx = decoded.indexOf(':');
    if (sepIdx < 0) return sendUnauthorized(res);

    const user = decoded.slice(0, sepIdx);
    const pass = decoded.slice(sepIdx + 1);

    const userOk = safeEqual(user, EXPECTED_USER);
    const passOk = safeEqual(pass, EXPECTED_PASS);
    if (!userOk || !passOk) {
        return sendUnauthorized(res);
    }

    return next();
}

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', 1); // Render の HTTPS 終端配下で動作

// すべてのリクエストに Basic 認証を適用
app.use(basicAuth);

// 静的ファイル配信
app.use(
    express.static(DIST_DIR, {
        index: false,
        maxAge: '1h',
        setHeaders: (res, filePath) => {
            // 認証後のレスポンスを共有キャッシュに載せない
            res.setHeader('Cache-Control', 'private, max-age=0, must-revalidate');
            if (filePath.endsWith('.html')) {
                res.setHeader('Cache-Control', 'no-store');
            }
        },
    }),
);

// SPA フォールバック: 未マッチの GET はすべて index.html を返す
app.get('*', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    res.sendFile(path.join(DIST_DIR, 'index.html'));
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`[server] listening on 0.0.0.0:${PORT}`);
    console.log(`[server] serving ${DIST_DIR}`);
    console.log(`[server] auth configured: ${AUTH_CONFIGURED}`);
});
