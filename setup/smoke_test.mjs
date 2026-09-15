// smoke_test.mjs <RCWM_ROOT> : renders a tiny three.js scene with headless Chromium exactly the way a solver
// session does (import three.module.js from the runtime root, screenshot with Playwright) and checks the
// Python side (Pillow + numpy). Writes $RCWM_ROOT/runs/.smoke/smoke.png and prints ok.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path'; import { execFileSync } from 'node:child_process';
const root = path.resolve(process.argv[2] || process.env.RCWM_ROOT || '.');
const outDir = path.join(root, 'runs', '.smoke'); fs.mkdirSync(outDir, { recursive: true });
const html = `<!doctype html><body style="margin:0"><script type="importmap">{"imports":{"three":"/.render-tools/node_modules/three/build/three.module.js"}}</script>
<script type="module">
import * as THREE from 'three';
const r = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); r.setSize(320, 200); document.body.appendChild(r.domElement);
const s = new THREE.Scene(); s.background = new THREE.Color(0xffffff);
const c = new THREE.PerspectiveCamera(45, 1.6, 0.1, 100); c.position.set(3, 3, 5); c.lookAt(0, 0, 0);
s.add(new THREE.HemisphereLight(0xffffff, 0x444444, 1.2));
const m = new THREE.Mesh(new THREE.BoxGeometry(2, 1, 1), new THREE.MeshStandardMaterial({ color: 0xcc4422 })); s.add(m);
r.render(s, c); window.ready = true;
</script></body>`;
fs.writeFileSync(path.join(outDir, 'index.html'), html);
const mime = { '.js': 'text/javascript', '.html': 'text/html' };
const server = http.createServer((q, res) => { const p = path.join(root, decodeURIComponent(q.url.split('?')[0])); fs.readFile(p, (e, b) => { if (e) { res.writeHead(404); res.end(); return; } res.setHeader('Content-Type', mime[path.extname(p)] || 'application/octet-stream'); res.end(b); }); });
await new Promise(r => server.listen(0, '127.0.0.1', r));
const { chromium } = await import(path.join(root, '.render-tools/node_modules/playwright/index.mjs'));
let browser;
try { browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] }); }
catch (e) { console.error('Chromium failed to launch. Missing system libraries? Run: sudo npx playwright install-deps chromium  (in ' + root + '/.render-tools)\n' + String(e).slice(0, 400)); process.exit(1); }
const page = await browser.newPage({ viewport: { width: 320, height: 200 } });
const errors = []; page.on('pageerror', e => errors.push(String(e)));
await page.goto(`http://127.0.0.1:${server.address().port}/runs/.smoke/index.html`);
await page.waitForFunction('window.ready', null, { timeout: 60000 });
const png = path.join(outDir, 'smoke.png'); await page.screenshot({ path: png });
await browser.close(); server.close();
if (errors.length) { console.error('page errors: ' + errors.join(' | ')); process.exit(1); }
const py = path.join(root, '.venv/bin/python');
const check = execFileSync(py, ['-I', '-c', `from PIL import Image; import numpy as np; a=np.asarray(Image.open('${png}').convert('RGB')); print('red pixels:', int(((a[:,:,0]>150)&(a[:,:,1]<120)).sum()))`]).toString().trim();
console.log(`smoke test ok: ${png}  (${check})`);
if (!/red pixels: [1-9]/.test(check)) { console.error('the rendered box is missing from the screenshot (WebGL not working in headless Chromium?)'); process.exit(1); }
