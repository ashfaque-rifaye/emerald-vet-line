// The Emerald film: draws each frame from the edit (data/film/edit.json) as a pure function of time.
// Screen footage is the real take; the camera, cursor, phone, captions and cards are drawn on top.
const edit = await (await fetch("/data/film/edit.json")).json();
const FPS = edit.fps, W = 1920, H = 1080, SRC = 2;
const canvas = document.getElementById("c");
const g = canvas.getContext("2d", { alpha: false });
const C = { deep: "#04170f", deep2: "#07261c", emerald: "#0d6a4e", mid: "#127a5b", lime: "#c9f26c", mint: "#a9ebca", coral: "#ff7050", red: "#e0452b", amber: "#f2b84b", stone: "#ece8df", ink: "#0f241b", white: "#ffffff" };
const DISPLAY = '"Bricolage Grotesque", "Figtree", sans-serif', UI = '"Figtree", sans-serif', MONO = '"JetBrains Mono", Consolas, monospace';

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const prog = (t, a, b) => clamp((t - a) / (b - a || 1));
const easeOut = x => 1 - Math.pow(1 - x, 3);
const easeInOut = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const spring = x => (x >= 1 ? 1 : 1 - Math.exp(-6 * x) * Math.cos(9 * x));
const lerp = (a, b, k) => a + (b - a) * k;

// ------------------------------------------------------------ footage
const pad = n => String(n).padStart(6, "0");
const cache = new Map();
function bitmap(url) {
  const hit = cache.get(url) ?? fetch(url).then(r => r.blob()).then(b => createImageBitmap(b));
  cache.delete(url);
  cache.set(url, hit);
  if (cache.size > 14) {
    const old = cache.keys().next().value, p = cache.get(old);
    cache.delete(old);
    p.then(x => x.close()).catch(() => {});
  }
  return hit;
}
function frameAt(at) {
  const times = edit.times;
  let lo = 0, hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= at) lo = mid; else hi = mid - 1;
  }
  return `/data/film/take/frames/${pad(lo)}.jpg`;
}
function sourceAt(shot, t) {
  const m = shot.map.find(p => t >= p[0] && t <= p[2]) ?? (t < shot.map[0][0] ? shot.map[0] : shot.map.at(-1));
  return m[1] + clamp((t - m[0]) / (m[2] - m[0] || 1)) * (m[3] - m[1]);
}
function speedAt(shot, t) {
  const m = shot.map.find(p => t >= p[0] && t <= p[2]);
  return m ? (m[3] - m[1]) / (m[2] - m[0] || 1) : 1;
}

// ------------------------------------------------------------ backdrops
const back = document.createElement("canvas");
back.width = W; back.height = H;
{
  const b = back.getContext("2d");
  const gr = b.createRadialGradient(W * 0.82, 0, 0, W * 0.82, 0, W * 1.2);
  gr.addColorStop(0, "#127a5b"); gr.addColorStop(0.45, "#0a4b38"); gr.addColorStop(1, "#04170f");
  b.fillStyle = gr; b.fillRect(0, 0, W, H);
}
const rr = (x, y, w, h, r) => { g.beginPath(); g.roundRect(x, y, w, h, r); };

// ------------------------------------------------------------ camera
function cameraAt(keys, t) {
  let prev = keys[0], next = null;
  for (const k of keys) { if (k.t <= t) prev = k; else { next = k; break; } }
  let cur = prev;
  if (next && t > next.t - next.d) {
    const k = easeInOut(prog(t, next.t - next.d, next.t));
    cur = { cx: lerp(prev.cx, next.cx, k), cy: lerp(prev.cy, next.cy, k), s: Math.exp(lerp(Math.log(prev.s), Math.log(next.s), k)) };
  }
  const drift = 1 + 0.004 * clamp(t - prev.t, 0, 8);
  return { cx: cur.cx, cy: cur.cy, s: cur.s * drift };
}
function drawCursor(shot, src, cam, wx, wy) {
  const pts = edit.cursor;
  if (!pts.length || !shot.cursor) return;
  let i = -1;
  for (let n = 0; n < pts.length; n++) if (pts[n][0] <= src) i = n; else break;
  const home = [720, 560];
  const a = i >= 0 ? pts[i] : [src - 9, ...home, "move"];
  const b = pts[i + 1];
  // Glide over the last moment before each waypoint, as a hand would.
  let x = a[1], y = a[2];
  if (b && src > b[0] - 0.65) { const k = easeInOut(prog(src, b[0] - 0.65, b[0])); x = lerp(a[1], b[1], k); y = lerp(a[2], b[2], k); }
  const px = wx + x * cam.s, py = wy + y * cam.s;
  const scale = clamp(cam.s / 1.3, 1, 1.7);
  const pressed = a[3] === "down" && (!b || b[3] === "up");
  const clickAge = a[3] === "click" ? src - a[0] : 99;
  if (clickAge < 0.5) {
    g.save(); g.globalAlpha = 1 - clickAge / 0.5; g.strokeStyle = C.lime; g.lineWidth = 4;
    g.beginPath(); g.arc(px, py, 10 + 60 * easeOut(clickAge / 0.5), 0, 7); g.stroke(); g.restore();
  }
  if (pressed) {
    const k = clamp((src - a[0]) / 1.15);
    g.save(); g.strokeStyle = C.lime; g.lineWidth = 6; g.globalAlpha = 0.9;
    g.beginPath(); g.arc(px, py, 34, -Math.PI / 2, -Math.PI / 2 + k * Math.PI * 2); g.stroke(); g.restore();
  }
  g.save();
  g.translate(px, py); g.scale(scale * (pressed ? 0.88 : 1), scale * (pressed ? 0.88 : 1));
  g.shadowColor = "rgba(0,0,0,.45)"; g.shadowBlur = 10; g.shadowOffsetY = 4;
  g.beginPath(); g.moveTo(0, 0); g.lineTo(0, 27); g.lineTo(6.5, 21); g.lineTo(11, 31.5); g.lineTo(16, 29.5); g.lineTo(11.5, 19.5); g.lineTo(20, 19.5); g.closePath();
  g.fillStyle = "#fff"; g.fill(); g.shadowColor = "transparent"; g.lineWidth = 1.6; g.strokeStyle = "#111"; g.stroke();
  g.restore();
}
async function drawScreen(shot, t, alpha = 1) {
  const src = sourceAt(shot, t);
  const img = await bitmap(frameAt(src));
  const cam = cameraAt(shot.cam, t);
  const dw = 1440 * cam.s, dh = 810 * cam.s;
  const wx = W / 2 - cam.cx * cam.s, wy = H / 2 - cam.cy * cam.s;
  g.save();
  g.globalAlpha = alpha;
  // A browser bar, so wide shots read as a product on a screen.
  const bar = 30 * cam.s;
  g.shadowColor = "rgba(0,0,0,.45)"; g.shadowBlur = 50; g.shadowOffsetY = 20;
  g.fillStyle = "#e4e0d6";
  rr(wx, wy - bar, dw, dh + bar, 14 * cam.s); g.fill();
  g.shadowColor = "transparent";
  g.save();
  rr(wx, wy - bar, dw, dh + bar, 14 * cam.s); g.clip();
  g.imageSmoothingQuality = "high";
  g.drawImage(img, wx, wy, dw, dh);
  for (const [i, c] of ["#f26d5b", "#f2bd4e", "#5fc66a"].entries()) { g.fillStyle = c; g.beginPath(); g.arc(wx + (20 + i * 18) * cam.s, wy - bar / 2, 5.5 * cam.s, 0, 7); g.fill(); }
  g.fillStyle = "rgba(15,36,27,.08)"; rr(wx + dw / 2 - 150 * cam.s, wy - bar + 6 * cam.s, 300 * cam.s, 18 * cam.s, 6 * cam.s); g.fill();
  g.fillStyle = "rgba(15,36,27,.62)"; g.font = `500 ${11 * cam.s}px ${UI}`; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText("emerald vet line", wx + dw / 2, wy - bar + 15.5 * cam.s);
  g.textAlign = "left"; g.textBaseline = "alphabetic";
  drawCursor(shot, src, cam, wx, wy);
  g.restore();
  g.restore();
  return { src, cam, wx, wy };
}

// ------------------------------------------------------------ type
function fit(text, font, maxW) { g.font = font; return g.measureText(text).width <= maxW; }
function slam(text, t, at, { x = W / 2, y = H / 2, size = 120, color = "#fff", align = "center", weight = 700, out = null, tracking = "-0.035em", font = DISPLAY } = {}) {
  const k = prog(t, at, at + 0.32);
  if (k <= 0) return;
  const a = (out ? 1 - prog(t, out - 0.16, out) : 1) * easeOut(prog(t, at, at + 0.12));
  if (a <= 0) return;
  const s = lerp(1.14, 1, spring(k));
  g.save();
  g.globalAlpha = a; g.translate(x, y); g.scale(s, s);
  g.font = `${weight} ${size}px ${font}`; g.letterSpacing = tracking;
  g.textAlign = align; g.textBaseline = "middle"; g.fillStyle = color;
  g.fillText(text, 0, 0);
  g.restore();
}
function gem(x, y, size, alpha = 1) {
  g.save(); g.globalAlpha = alpha; g.translate(x, y); g.scale(size / 32, size / 32); g.translate(-16, -16);
  const gr = g.createLinearGradient(0, 0, 32, 32); gr.addColorStop(0, "#c9f26c"); gr.addColorStop(1, "#1fb98a");
  g.fillStyle = gr; g.fill(new Path2D("M9 3h14l7 9-14 17L2 12z"));
  g.fillStyle = "rgba(255,255,255,.35)"; g.fill(new Path2D("M9 3l-7 9h9l5-9zM16 3l5 9h9l-7-9z"));
  g.restore();
}
function logo(cx, cy, size, alpha = 1) {
  g.save(); g.globalAlpha = alpha;
  g.font = `700 ${size}px ${DISPLAY}`; g.letterSpacing = "-0.04em"; g.textBaseline = "middle"; g.textAlign = "left";
  const w = g.measureText("emerald").width, gemW = size * 1.05, gap = size * 0.26, x = cx - (w + gemW + gap) / 2;
  g.fillStyle = "#fff"; g.fillText("emerald", x + gemW + gap, cy);
  g.restore();
  gem(x + gemW / 2, cy + size * 0.03, gemW, alpha);
}

// ------------------------------------------------------------ the phone
const PHONE = { w: 356, h: 736 };
function drawPhone(p, t) {
  const start = p.t0, end = p.t1;
  const up = spring(prog(t, start, start + 0.9)), down = easeInOut(prog(t, end - 0.5, end));
  if (t < start || t > end) return;
  const x = p.x, y = lerp(H + 40, p.y, up) + down * (H - p.y + 60);
  const ringing = t < p.answered;
  g.save();
  g.translate(x + PHONE.w / 2, y + PHONE.h / 2);
  g.rotate(lerp(0.04, 0, up) + (ringing ? Math.sin(t * 34) * 0.006 : 0));
  g.translate(-PHONE.w / 2, -PHONE.h / 2);
  g.shadowColor = "rgba(0,0,0,.55)"; g.shadowBlur = 70; g.shadowOffsetY = 30;
  g.fillStyle = "#0a0e0c"; rr(0, 0, PHONE.w, PHONE.h, 54); g.fill();
  g.shadowColor = "transparent";
  rr(10, 10, PHONE.w - 20, PHONE.h - 20, 45); g.save(); g.clip();
  const sky = g.createLinearGradient(0, 0, 0, PHONE.h);
  sky.addColorStop(0, "#0d5b44"); sky.addColorStop(0.55, "#06291e"); sky.addColorStop(1, "#04170f");
  g.fillStyle = sky; g.fillRect(0, 0, PHONE.w, PHONE.h);
  g.fillStyle = "#000"; rr(PHONE.w / 2 - 52, 22, 104, 28, 14); g.fill();
  g.fillStyle = "rgba(255,255,255,.72)"; g.font = `600 15px ${UI}`; g.textAlign = "left"; g.textBaseline = "middle";
  g.fillText("9:41", 36, 37);
  // who
  const r = 54 + (ringing ? Math.sin(t * 6) * 4 : 0);
  g.fillStyle = "rgba(255,255,255,.09)"; g.beginPath(); g.arc(PHONE.w / 2, 170, r + 18, 0, 7); g.fill();
  g.fillStyle = "rgba(255,255,255,.14)"; g.beginPath(); g.arc(PHONE.w / 2, 170, r, 0, 7); g.fill();
  gem(PHONE.w / 2, 172, 62);
  g.textAlign = "center"; g.fillStyle = "#fff"; g.font = `600 31px ${DISPLAY}`; g.letterSpacing = "-0.02em"; g.fillText("Emerald Vet Line", PHONE.w / 2, 268);
  g.letterSpacing = "0px"; g.font = `500 19px ${UI}`; g.fillStyle = "rgba(255,255,255,.72)";
  const secs = Math.max(0, Math.floor(t - p.answered));
  g.fillText(ringing ? "Calling..." : t > p.hangup ? "Call ended" : `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`, PHONE.w / 2, 306);
  // the live waveform, from the real audio
  const i = Math.floor((t - p.envAt) * FPS), bars = 25;
  for (let b = 0; b < bars; b++) {
    const v = p.env[i - (bars - 1 - b)] ?? 0, who = p.who[i - (bars - 1 - b)] ?? 0;
    const h = 4 + v * 92, bx = PHONE.w / 2 - (bars * 11) / 2 + b * 11;
    g.fillStyle = who === 1 ? C.lime : who === 2 ? "#fff" : "rgba(255,255,255,.28)";
    rr(bx, 392 - h / 2, 7, h, 3.5); g.fill();
  }
  // speaker label
  const nowWho = p.who[i] ?? 0;
  g.font = `600 15px ${UI}`; g.fillStyle = nowWho === 1 ? C.lime : "rgba(255,255,255,.8)";
  g.fillText(nowWho === 1 ? "EMERALD" : nowWho === 2 ? "FARMER" : " ", PHONE.w / 2, 464);
  // keys
  const keys = [[PHONE.w / 2 - 92, 556], [PHONE.w / 2, 556], [PHONE.w / 2 + 92, 556]];
  for (const [kx, ky] of keys) { g.fillStyle = "rgba(255,255,255,.13)"; g.beginPath(); g.arc(kx, ky, 34, 0, 7); g.fill(); }
  g.strokeStyle = "#fff"; g.lineWidth = 3; g.lineCap = "round";
  g.beginPath(); g.moveTo(keys[0][0], keys[0][1] - 13); g.lineTo(keys[0][0], keys[0][1] + 3); g.stroke(); g.beginPath(); g.arc(keys[0][0], keys[0][1] - 1, 11, 0.2, Math.PI - 0.2); g.stroke();
  for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) { g.fillStyle = "#fff"; g.beginPath(); g.arc(keys[1][0] + dx * 9, keys[1][1] + dy * 9, 2.6, 0, 7); g.fill(); }
  g.beginPath(); g.moveTo(keys[2][0] - 12, keys[2][1] - 5); g.lineTo(keys[2][0] - 5, keys[2][1] - 5); g.lineTo(keys[2][0] + 3, keys[2][1] - 12); g.lineTo(keys[2][0] + 3, keys[2][1] + 12); g.lineTo(keys[2][0] - 5, keys[2][1] + 5); g.lineTo(keys[2][0] - 12, keys[2][1] + 5); g.closePath(); g.stroke();
  g.fillStyle = C.red; g.beginPath(); g.arc(PHONE.w / 2, 652, 38, 0, 7); g.fill();
  g.strokeStyle = "#fff"; g.lineWidth = 6; g.beginPath(); g.arc(PHONE.w / 2, 664, 21, Math.PI + 0.45, -0.45); g.stroke();
  g.restore();
  g.restore();
}

// ------------------------------------------------------------ captions and tags
function wrap(text, font, maxW) {
  g.font = font;
  const out = []; let line = "";
  for (const w of text.split(/\s+/)) {
    const next = line ? `${line} ${w}` : w;
    if (g.measureText(next).width > maxW && line) { out.push(line); line = w; } else line = next;
  }
  if (line) out.push(line);
  return out;
}
function drawCaption(c, t, centre) {
  const a = Math.min(easeOut(prog(t, c.t0, c.t0 + 0.14)), 1 - prog(t, c.t1 - 0.04, c.t1 + 0.1));
  if (a <= 0) return;
  const font = `600 31px ${UI}`;
  g.letterSpacing = "0px";
  const rows = wrap(c.text, font, 1180);
  const lh = 41, label = c.who ? c.who.toUpperCase() : null;
  g.font = font;
  const w = Math.max(...rows.map(r => g.measureText(r).width), 0) + 56;
  const h = rows.length * lh + 26 + (label ? 22 : 0);
  const x = centre - w / 2, y = H - 40 - h + (1 - a) * 8;
  g.save();
  g.globalAlpha = a;
  g.fillStyle = "rgba(4,18,12,.86)"; rr(x, y, w, h, 18); g.fill();
  g.textAlign = "center"; g.textBaseline = "middle";
  if (label) {
    g.font = `700 15px ${UI}`; g.letterSpacing = "0.1em"; g.fillStyle = c.who === "Emerald" ? C.lime : "#ffd9a8";
    g.fillText(label, centre, y + 22); g.letterSpacing = "0px";
  }
  g.font = font; g.fillStyle = "#fff";
  rows.forEach((r, i) => g.fillText(r, centre, y + 14 + (label ? 22 : 0) + lh * (i + 0.5)));
  g.restore();
}
function drawTag(tag, t) {
  if (t < tag.t0 || t > tag.t1) return;
  const a = Math.min(easeOut(prog(t, tag.t0, tag.t0 + 0.25)), 1 - prog(t, tag.t1 - 0.2, tag.t1));
  g.save(); g.globalAlpha = a; g.letterSpacing = "0px";
  g.font = `700 21px ${UI}`;
  const w = g.measureText(tag.text).width + 56, x = 40 + (1 - a) * -14, y = 34;
  g.fillStyle = "rgba(4,18,12,.88)"; rr(x, y, w, 50, 25); g.fill();
  g.fillStyle = tag.color || C.lime; g.beginPath(); g.arc(x + 25, y + 25, 6, 0, 7); g.fill();
  g.fillStyle = "#fff"; g.textBaseline = "middle"; g.textAlign = "left"; g.fillText(tag.text, x + 40, y + 26);
  g.restore();
}
function drawCallout(n, t) {
  if (t < n.t0 || t > n.t1) return;
  const k = spring(prog(t, n.t0, n.t0 + 0.5)), a = 1 - prog(t, n.t1 - 0.2, n.t1);
  g.save(); g.globalAlpha = a * clamp(k); g.letterSpacing = "0px";
  g.font = `700 ${n.size || 44}px ${DISPLAY}`;
  const w = g.measureText(n.text).width + 64, h = (n.size || 44) * 1.9;
  g.translate(n.x, n.y); g.scale(lerp(0.8, 1, k), lerp(0.8, 1, k));
  g.fillStyle = n.bg || C.lime; rr(-w / 2, -h / 2, w, h, h / 2); g.fill();
  g.fillStyle = n.fg || C.deep; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(n.text, 0, 3);
  g.restore();
}
function drawSpeed(shot, t) {
  const v = speedAt(shot, t);
  if (v < 1.6) return;
  g.save(); g.letterSpacing = "0px"; g.font = `700 18px ${MONO}`;
  const text = `▶▶ ${Math.round(v)}×`, w = g.measureText(text).width + 30;
  g.fillStyle = "rgba(4,18,12,.78)"; rr(W - w - 34, H - 78, w, 38, 19); g.fill();
  g.fillStyle = "#fff"; g.textBaseline = "middle"; g.textAlign = "center"; g.fillText(text, W - 34 - w / 2, H - 58);
  g.restore();
}
function drawSpot(o, t, cam) {
  if (t < o.t0 || t > o.t1 || !cam) return;
  const a = Math.min(easeOut(prog(t, o.t0, o.t0 + 0.6)), 1 - prog(t, o.t1 - 0.4, o.t1));
  const x = W / 2 + (o.cx - cam.cx) * cam.s, y = H / 2 + (o.cy - cam.cy) * cam.s, r = o.r * cam.s;
  const gr = g.createRadialGradient(x, y, r * 0.92, x, y, r * 1.34);
  gr.addColorStop(0, "rgba(3,14,9,0)");
  gr.addColorStop(1, `rgba(3,14,9,${0.72 * a})`);
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
}
function drawGraph(o, t) {
  if (t < o.t0 || t > o.t1) return;
  const a = Math.min(easeOut(prog(t, o.t0, o.t0 + 0.3)), 1 - prog(t, o.t1 - 0.25, o.t1));
  const nodes = [["Evidence agent", "Nova 2 Lite cites sentence numbers"], ["Verifier", "Plain code fills in the words"], ["Second opinion", "Llama 3.3 hunts for overreach"]];
  const x = 56, y = 150, w = 410, nh = 104, gap = 46;
  g.save(); g.globalAlpha = a; g.letterSpacing = "0px";
  nodes.forEach(([title, sub], i) => {
    const ny = y + i * (nh + gap), on = (Math.floor((t - o.t0) / 1.4) % 3) === i;
    g.fillStyle = on ? "rgba(13,106,78,.97)" : "rgba(4,18,12,.92)"; rr(x, ny, w, nh, 20); g.fill();
    g.strokeStyle = on ? C.lime : "rgba(255,255,255,.2)"; g.lineWidth = 2.5; rr(x, ny, w, nh, 20); g.stroke();
    g.fillStyle = "#fff"; g.font = `700 29px ${DISPLAY}`; g.textAlign = "left"; g.textBaseline = "middle"; g.fillText(title, x + 26, ny + 37);
    g.fillStyle = "rgba(255,255,255,.76)"; g.font = `500 20px ${UI}`; g.fillText(sub, x + 26, ny + 72);
    if (i < 2) {
      g.strokeStyle = C.lime; g.lineWidth = 3.5; g.lineCap = "round";
      g.beginPath(); g.moveTo(x + w / 2, ny + nh + 8); g.lineTo(x + w / 2, ny + nh + gap - 10); g.stroke();
      g.beginPath(); g.moveTo(x + w / 2 - 8, ny + nh + gap - 18); g.lineTo(x + w / 2, ny + nh + gap - 10); g.lineTo(x + w / 2 + 8, ny + nh + gap - 18); g.stroke();
    }
  });
  g.restore();
}
function drawTerminal(o, t) {
  if (t < o.t0 || t > o.t1) return;
  const a = Math.min(easeOut(prog(t, o.t0, o.t0 + 0.25)), 1 - prog(t, o.t1 - 0.2, o.t1));
  const up = spring(prog(t, o.t0, o.t0 + 0.6));
  const x = 210, w = 1500, y = lerp(180, 138, up), h = 690;
  g.save(); g.globalAlpha = a; g.letterSpacing = "0px";
  g.fillStyle = "rgba(0,0,0,.45)"; g.fillRect(0, 0, W, H);
  g.shadowColor = "rgba(0,0,0,.6)"; g.shadowBlur = 70; g.shadowOffsetY = 26;
  g.fillStyle = "#07120d"; rr(x, y, w, h, 24); g.fill(); g.shadowColor = "transparent";
  g.strokeStyle = "rgba(255,255,255,.14)"; g.lineWidth = 1.5; rr(x, y, w, h, 24); g.stroke();
  for (const [i, c] of ["#f26d5b", "#f2bd4e", "#5fc66a"].entries()) { g.fillStyle = c; g.beginPath(); g.arc(x + 32 + i * 24, y + 32, 8, 0, 7); g.fill(); }
  g.fillStyle = "rgba(255,255,255,.55)"; g.font = `500 19px ${MONO}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("the real tool, against the real signature", x + w / 2, y + 33);
  g.textAlign = "left";
  o.rows.forEach((row, i) => {
    if (t < row.at) return;
    const ry = y + 96 + i * 190;
    const chars = Math.floor((t - row.at) * 62), typed = row.cmd.slice(0, chars);
    g.font = `500 28px ${MONO}`; g.fillStyle = C.mint;
    wrap(typed, g.font, w - 80).forEach((line, j) => g.fillText(line, x + 40, ry + j * 36));
    if (t > row.result) {
      const k = spring(prog(t, row.result, row.result + 0.35));
      g.save(); g.translate(x + 40, ry + 86); g.scale(lerp(1.08, 1, k), lerp(1.08, 1, k));
      g.font = `700 28px ${UI}`; const label = row.label, lw = g.measureText(label).width + 34;
      g.fillStyle = row.good ? C.lime : C.red; rr(0, -26, lw, 52, 12); g.fill();
      g.fillStyle = row.good ? C.deep : "#fff"; g.fillText(label, 17, 1);
      g.font = `500 28px ${MONO}`; g.fillStyle = "#fff"; g.fillText(row.reason, lw + 22, 1);
      g.restore();
    }
  });
  g.restore();
}

// ------------------------------------------------------------ cards
async function aerial(t, z = 2.6, dark = 0.55, night = false) {
  // The project's own generated landscape, from the first frame of the take, drifting.
  const img = await bitmap(`/data/film/take/frames/${pad(edit.aerialFrame)}.jpg`);
  const k = img.width / 1440, s = z + t * 0.012, sw = 1440 * k / s, sh = 810 * k / s;
  const cx = (700 + Math.sin(t * 0.09) * 24) * k, cy = (440 + t * 3) * k;
  g.save();
  if (night) g.filter = "brightness(.38) saturate(.6) hue-rotate(28deg)";
  g.drawImage(img, cx - sw / 2, cy - sh / 2, sw, sh, 0, 0, W, H);
  g.restore();
  g.fillStyle = `rgba(3,18,12,${dark})`; g.fillRect(0, 0, W, H);
}
const scenes = {
  async open(sc, t) {
    const q = sc.cues;
    await aerial(t, 2.8, lerp(0.86, 0.62, prog(t, q.n01[0], q.n02[0])));
    const off1 = q.n02[0];
    slam("A sick cow", t, q.n01[0], { y: 360, size: 168, out: off1 });
    slam("is a health problem", t, q.n01[0] + 0.95, { y: 540, size: 116, color: C.mint, out: off1 });
    slam("and a money problem.", t, q.n01[0] + 2.0, { y: 690, size: 116, color: C.coral, out: off1 });
    if (t >= q.n02[0] && t < q.n03[0]) {
      const k = easeOut(prog(t, q.n02[0], q.n02[0] + 1.4)), n = Math.round(8295 * k).toLocaleString("en-IN");
      slam(n, t, q.n02[0], { y: 410, size: 270, color: C.lime, out: q.n03[0] });
      slam("public field vet posts, empty.", t, q.n02[0] + 0.5, { y: 600, size: 72, out: q.n03[0], weight: 600 });
      slam("28,328 filled of 36,623 approved. Report to India's Parliament, December 2022.", t, q.n02[0] + 0.9, { y: 690, size: 26, color: "rgba(255,255,255,.72)", font: UI, weight: 500, tracking: "0px", out: q.n03[0] });
    }
    if (t >= q.n03[0]) {
      const answer = q.n03[0] + q.adviceLen;
      slam("Most farm AI gives advice.", t, q.n03[0], { y: 450, size: 104, out: answer });
      if (t >= answer) {
        const k = spring(prog(t, answer, answer + 0.5));
        logo(W / 2, 470, 190, clamp(k));
        slam("picks up the phone.", t, answer + 0.32, { y: 640, size: 92, color: C.lime });
      }
    }
  },
  async stack(sc, t) {
    await aerial(t, 3.2, 0.8);
    const groups = sc.groups;
    groups.forEach((gp, i) => {
      if (t < gp.at) return;
      const x = 150 + i * 560, a = 1, y0 = 250;
      slam(gp.title, t, gp.at, { x, y: y0, size: 44, color: C.lime, align: "left", weight: 700 });
      gp.items.forEach((item, j) => slam(item, t, gp.at + 0.14 + j * 0.13, { x, y: y0 + 90 + j * 86, size: 50, align: "left", weight: 600, tracking: "-0.02em" }));
    });
  },
  async stats(sc, t) {
    g.drawImage(back, 0, 0);
    const cols = [[340, 370], [960, 370], [1580, 370]];
    sc.stats.forEach((st, i) => {
      if (t < st.at) return;
      const [x, y] = cols[i];
      slam(st.big, t, st.at, { x, y, size: 170, color: C.lime });
      slam(st.small, t, st.at + 0.16, { x, y: y + 140, size: 44, font: UI, weight: 600, tracking: "0px" });
      slam(st.note, t, st.at + 0.26, { x, y: y + 196, size: 28, font: UI, weight: 500, color: "rgba(255,255,255,.7)", tracking: "0px" });
    });
    slam("On test cases we wrote ourselves. This checks that the software keeps its promises, not clinical accuracy.", t, sc.noteAt, { y: 900, size: 28, font: UI, weight: 500, color: "rgba(255,255,255,.75)", tracking: "0px" });
  },
  async end(sc, t) {
    g.drawImage(back, 0, 0);
    logo(W / 2, 400, 170, clamp(spring(prog(t, 0.1, 0.7))));
    slam("Every sick animal gets a call back.", t, 0.8, { y: 560, size: 66, color: C.lime, weight: 600 });
    slam("github.com/ashfaque-rifaye/emerald-vet-line", t, 1.5, { y: 670, size: 36, font: UI, weight: 600, tracking: "0px" });
    slam("Built with the Strands Agents SDK on AWS. Open source, Apache-2.0.", t, 1.8, { y: 726, size: 27, font: UI, weight: 500, color: "rgba(255,255,255,.72)", tracking: "0px" });
    slam("Demo scenario with fictional people. Phone and payment rails run in test mode. Not yet field-tested; a vet review is next.", t, 2.2, { y: 960, size: 24, font: UI, weight: 500, color: "rgba(255,255,255,.62)", tracking: "0px" });
  },
};

// ------------------------------------------------------------ one frame
const shotAt = t => edit.shots.find(s => t >= s.t0 && t < s.t1) ?? edit.shots.at(-1);
async function drawShot(shot, t, alpha = 1) {
  if (shot.kind === "screen") {
    g.drawImage(back, 0, 0);
    const v = await drawScreen(shot, t, alpha);
    if (shot.dim) { g.fillStyle = `rgba(4,18,12,${shot.dim})`; g.fillRect(0, 0, W, H); }
    drawSpeed(shot, t);
    return v;
  }
  await scenes[shot.kind](shot, t - shot.t0);
}
async function draw(t) {
  g.letterSpacing = "0px";
  const shot = shotAt(t);
  await drawShot(shot, t);
  if (shot.kind === "screen") for (const o of edit.overlays) if (o.type === "spot") drawSpot(o, t, cameraAt(shot.cam, t));
  // Soft dissolve from the shot before, where asked.
  if (shot.fade && t < shot.t0 + shot.fade) {
    const prev = edit.shots[edit.shots.indexOf(shot) - 1];
    if (prev) {
      g.save(); g.globalAlpha = 1 - prog(t, shot.t0, shot.t0 + shot.fade);
      const snap = await snapshot(prev, t);
      g.drawImage(snap, 0, 0); g.restore();
    }
  }
  for (const o of edit.overlays) {
    if (o.type === "graph") drawGraph(o, t);
    else if (o.type === "terminal") drawTerminal(o, t);
    else if (o.type === "callout") drawCallout(o, t);
  }
  drawPhone(edit.phone, t);
  for (const tag of edit.tags) drawTag(tag, t);
  const centre = t >= edit.phone.t0 && t <= edit.phone.t1 ? edit.phone.captionX : W / 2;
  for (const c of edit.captions) if (t >= c.t0 - 0.02 && t <= c.t1 + 0.12) drawCaption(c, t, centre);
  // flashes on the big hits
  for (const f of edit.flashes) if (t >= f.t && t < f.t + f.d) { g.fillStyle = f.color; g.globalAlpha = (1 - prog(t, f.t, f.t + f.d)) * (f.a ?? 0.6); g.fillRect(0, 0, W, H); g.globalAlpha = 1; }
  const fade = Math.max(1 - prog(t, 0, 0.5), prog(t, edit.duration - 0.6, edit.duration));
  if (fade > 0) { g.fillStyle = `rgba(0,0,0,${fade})`; g.fillRect(0, 0, W, H); }
}
const off = document.createElement("canvas");
off.width = W; off.height = H;
const offG = off.getContext("2d");
async function snapshot(shot, t) {
  // The dissolve draws the outgoing shot, held on its last moment, onto a spare canvas.
  const saved = g.canvas;
  const img = shot.kind === "screen" ? await bitmap(frameAt(sourceAt(shot, shot.t1 - 0.01))) : null;
  if (!img) { offG.drawImage(saved, 0, 0); return off; }
  offG.drawImage(back, 0, 0);
  const cam = cameraAt(shot.cam, shot.t1 - 0.01);
  offG.drawImage(img, W / 2 - cam.cx * cam.s, H / 2 - cam.cy * cam.s, 1440 * cam.s, 810 * cam.s);
  return off;
}

window.__duration = edit.duration;
window.__fps = FPS;
window.__frame = async i => { await draw(i / FPS); return true; };
await document.fonts.load(`700 40px ${DISPLAY}`);
await document.fonts.load(`600 30px ${UI}`);
await document.fonts.load(`500 25px ${MONO}`);
await document.fonts.ready;
window.__ready = true;
