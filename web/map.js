/* The stage: a generated aerial view of a fictional dairy cluster, and the living layer on top of it.
   Everything is drawn in code, so it needs no image files, no network, and belongs to this project. */
(function () {
  const rng = seed => () => {
    seed |= 0; seed = seed + 0x6d2b79f5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  const CROPS = ["#2f5a36", "#35663a", "#3f7640", "#4d8444", "#5f8f45", "#74994a", "#27503a"];
  const DRY = ["#a18a4d", "#b19c63", "#8d7a44", "#c0ad78"];
  const SOIL = ["#6d5a3f", "#7b684a", "#5f4e38", "#86724f"];
  const ROOFS = ["#c9694a", "#d9cdb6", "#b6583f", "#e3dccb", "#9d8f7c"];

  function zone(x, y) { // large soft patches, so crops and dry land form regions rather than confetti
    return Math.sin(x * 0.0037 + 1.3) + Math.sin(y * 0.0049 - 0.7) + 0.6 * Math.sin((x + y) * 0.0083);
  }

  function plotColor(r, x, y) {
    const z = zone(x, y) + (r() - 0.5) * 1.5;
    if (z > 0.5) return { base: CROPS[Math.floor(r() * CROPS.length)], rows: "#16361f", kind: "crop" };
    if (z > -0.6) return r() < 0.55
      ? { base: CROPS[Math.floor(r() * CROPS.length)], rows: "#16361f", kind: "crop" }
      : { base: DRY[Math.floor(r() * DRY.length)], rows: "#5b4a24", kind: "dry" };
    return r() < 0.6
      ? { base: SOIL[Math.floor(r() * SOIL.length)], rows: "#2e2415", kind: "soil" }
      : { base: DRY[Math.floor(r() * DRY.length)], rows: "#5b4a24", kind: "dry" };
  }

  function splitPlots(r, x, y, w, h, out, minArea) {
    const area = w * h;
    if (area < minArea * (0.6 + r() * 2.4) || Math.min(w, h) < 26) { out.push({ x, y, w, h }); return; }
    const along = w > h * (0.8 + r() * 0.5);
    const at = 0.34 + r() * 0.32;
    if (along) { splitPlots(r, x, y, w * at, h, out, minArea); splitPlots(r, x + w * at, y, w * (1 - at), h, out, minArea); }
    else { splitPlots(r, x, y, w, h * at, out, minArea); splitPlots(r, x, y + h * at, w, h * (1 - at), out, minArea); }
  }

  function jittered(r, p, amount) {
    const j = () => (r() - 0.5) * amount;
    return [[p.x + j(), p.y + j()], [p.x + p.w + j(), p.y + j()], [p.x + p.w + j(), p.y + p.h + j()], [p.x + j(), p.y + p.h + j()]];
  }

  function path(ctx, pts) {
    ctx.beginPath();
    pts.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])));
    ctx.closePath();
  }

  function drawPlot(ctx, r, p) {
    const pts = jittered(r, p, 5);
    const c = plotColor(r, p.x + p.w / 2, p.y + p.h / 2);
    ctx.save();
    path(ctx, pts);
    ctx.fillStyle = c.base;
    ctx.fill();
    ctx.clip();
    // Crop rows run along the plot's long side, ploughed fields get closer furrows.
    const horizontal = p.w > p.h;
    const gap = c.kind === "soil" ? 3 + r() * 2 : 4 + r() * 5;
    ctx.strokeStyle = c.rows;
    ctx.globalAlpha = c.kind === "dry" ? 0.1 : 0.2 + r() * 0.16;
    ctx.lineWidth = 0.9 + r() * 0.7;
    ctx.beginPath();
    if (horizontal) for (let y = p.y - 4; y < p.y + p.h + 4; y += gap) { ctx.moveTo(p.x - 4, y); ctx.lineTo(p.x + p.w + 4, y + (r() - 0.5) * 1.5); }
    else for (let x = p.x - 4; x < p.x + p.w + 4; x += gap) { ctx.moveTo(x, p.y - 4); ctx.lineTo(x + (r() - 0.5) * 1.5, p.y + p.h + 4); }
    ctx.stroke();
    // Uneven growth and worn patches inside the plot.
    for (let i = 0, n = 1 + Math.floor(r() * 3); i < n; i++) {
      const gx = p.x + r() * p.w, gy = p.y + r() * p.h, gr = 10 + r() * Math.max(p.w, p.h) * 0.45;
      const g = ctx.createRadialGradient(gx, gy, 0, gx, gy, gr);
      const light = r() < 0.5;
      g.addColorStop(0, light ? "rgba(214,214,140,.20)" : "rgba(12,30,14,.26)");
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.globalAlpha = 1;
      ctx.fillStyle = g;
      ctx.fillRect(gx - gr, gy - gr, gr * 2, gr * 2);
    }
    ctx.restore();
    path(ctx, pts);
    ctx.strokeStyle = "rgba(38,30,16,.42)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    path(ctx, pts);
    ctx.strokeStyle = "rgba(226,214,170,.08)";
    ctx.lineWidth = 0.6;
    ctx.stroke();
  }

  function tree(ctx, r, x, y, size) {
    ctx.fillStyle = "rgba(6,16,10,.42)";
    ctx.beginPath(); ctx.ellipse(x + size * 0.9, y + size * 0.75, size * 1.05, size * 0.8, 0.6, 0, 7); ctx.fill();
    const g = ctx.createRadialGradient(x - size * 0.35, y - size * 0.35, 0, x, y, size * 1.05);
    g.addColorStop(0, r() < 0.5 ? "#4f7f3c" : "#3f7341");
    g.addColorStop(1, "#16391f");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(x, y, size, 0, 7); ctx.fill();
  }

  function curve(ctx, pts) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      ctx.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2);
    }
    ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
  }

  function road(ctx, pts, width) {
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    curve(ctx, pts); ctx.strokeStyle = "rgba(40,30,16,.5)"; ctx.lineWidth = width + 2; ctx.stroke();
    curve(ctx, pts); ctx.strokeStyle = "#bfa97b"; ctx.lineWidth = width; ctx.stroke();
    curve(ctx, pts); ctx.strokeStyle = "rgba(255,240,205,.22)"; ctx.lineWidth = width * 0.3; ctx.stroke();
  }

  function waterway(ctx, pts) {
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    curve(ctx, pts); ctx.strokeStyle = "rgba(60,48,28,.55)"; ctx.lineWidth = 16; ctx.stroke();
    curve(ctx, pts); ctx.strokeStyle = "#9c8a5e"; ctx.lineWidth = 12; ctx.stroke();
    curve(ctx, pts); ctx.strokeStyle = "#3f6f73"; ctx.lineWidth = 6; ctx.stroke();
    curve(ctx, pts); ctx.strokeStyle = "rgba(190,226,222,.26)"; ctx.lineWidth = 1.4; ctx.stroke();
  }

  function house(ctx, r, x, y) {
    const w = 3.4 + r() * 4.2, h = 3.4 + r() * 3.6, a = -0.2 + (r() - 0.5) * 0.8;
    ctx.save(); ctx.translate(x, y); ctx.rotate(a);
    ctx.fillStyle = "rgba(10,14,8,.45)"; ctx.fillRect(-w / 2 + 1.6, -h / 2 + 1.6, w, h);
    ctx.fillStyle = ROOFS[Math.floor(r() * ROOFS.length)]; ctx.fillRect(-w / 2, -h / 2, w, h);
    ctx.fillStyle = "rgba(255,255,255,.18)"; ctx.fillRect(-w / 2, -h / 2, w, h * 0.3);
    ctx.restore();
  }

  function paintLandscape(canvas, place) {
    const W = canvas.width, H = canvas.height, ctx = canvas.getContext("2d");
    const scale = W / 1800, r = rng(1962);
    ctx.fillStyle = "#5c4c34"; ctx.fillRect(0, 0, W, H);

    ctx.save();
    ctx.translate(W / 2, H / 2); ctx.rotate(-0.16); ctx.translate(-W / 2, -H / 2);
    const plots = [], d = Math.max(W, H) * 1.5;
    splitPlots(r, W / 2 - d / 2, H / 2 - d / 2, d, d, plots, 9500 * scale * scale);
    plots.forEach(p => drawPlot(ctx, r, p));
    ctx.restore();

    waterway(ctx, [[-40, H * 0.2], [W * 0.14, H * 0.3], [W * 0.27, H * 0.24], [W * 0.42, H * 0.46], [W * 0.5, H * 0.74], [W * 0.68, H * 0.9], [W + 40, H * 0.84]]);
    road(ctx, [[-20, H * 0.72], [W * 0.2, H * 0.66], [W * 0.38, H * 0.6], [W * 0.56, H * 0.52], [W * 0.78, H * 0.34], [W + 20, H * 0.28]], 5 * Math.max(scale, 0.7));
    road(ctx, [[W * 0.36, -20], [W * 0.4, H * 0.22], [W * 0.46, H * 0.46], [W * 0.56, H * 0.52], [W * 0.62, H * 0.76], [W * 0.58, H + 20]], 3.2 * Math.max(scale, 0.7));
    road(ctx, [[W * 0.72, -20], [W * 0.7, H * 0.2], [W * 0.78, H * 0.34], [W * 0.88, H * 0.62], [W + 20, H * 0.7]], 2.6 * Math.max(scale, 0.7));

    // Tree lines along field edges, denser near the water.
    for (let i = 0; i < 950; i++) {
      const x = r() * W, y = r() * H;
      if (zone(x, y) > -1.2) tree(ctx, r, x, y, (1.6 + r() * 3.4) * Math.max(scale, 0.75));
    }

    // A small settlement around every registered household, so its light lands on real roofs.
    place.forEach(p => {
      for (let i = 0, n = 3 + Math.floor(r() * 7); i < n; i++) {
        const a = r() * 6.28, q = 3 + r() * 19;
        house(ctx, r, p.x + Math.cos(a) * q, p.y + Math.sin(a) * q);
      }
      if (r() < 0.6) tree(ctx, r, p.x + 12 * (r() - 0.5), p.y + 12 * (r() - 0.5), 4);
    });

    // Golden-hour light from the top left, then film grain.
    ctx.save();
    ctx.globalCompositeOperation = "soft-light";
    let g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#ffd68a"); g.addColorStop(0.5, "#b5a36a"); g.addColorStop(1, "#21414a");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = "multiply";
    g = ctx.createRadialGradient(W * 0.55, H * 0.5, H * 0.25, W * 0.55, H * 0.5, W * 0.72);
    g.addColorStop(0, "#ffffff"); g.addColorStop(1, "#5d6a5e");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    ctx.restore();

    const tile = document.createElement("canvas");
    tile.width = tile.height = 220;
    const tc = tile.getContext("2d"), img = tc.createImageData(220, 220);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = 128 + (r() - 0.5) * 90;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255;
    }
    tc.putImageData(img, 0, 0);
    ctx.save();
    ctx.globalCompositeOperation = "overlay"; ctx.globalAlpha = 0.16;
    ctx.fillStyle = ctx.createPattern(tile, "repeat"); ctx.fillRect(0, 0, W, H);
    ctx.restore();
  }

  class Stage {
    constructor(land, fx, world) {
      this.land = land; this.fx = fx; this.world = world;
      this.cases = []; this.called = new Map(); this.cluster = null; this.arcs = [];
      this.night = false; this.focusId = null; this.t = 0;
      this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.resize();
      addEventListener("resize", () => { clearTimeout(this._rz); this._rz = setTimeout(() => this.resize(), 180); });
      requestAnimationFrame(t => this.loop(t));
    }

    resize() {
      const box = this.fx.parentElement.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 2);
      this.W = box.width; this.H = box.height; this.dpr = dpr;
      this.fx.width = box.width * dpr; this.fx.height = box.height * dpr;
      this.land.width = box.width * dpr; this.land.height = box.height * dpr;
      this.project();
      paintLandscape(this.land, this.points.map(p => ({ x: p.x * dpr, y: p.y * dpr })));
    }

    project() {
      // Keep true distances: one scale for both axes, so a 10 km ring really is a circle of 10 km.
      const all = [...this.world.farmers, ...this.world.vets];
      const lats = all.map(p => p.lat), lons = all.map(p => p.lon);
      const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
      const midLat = (minLat + maxLat) / 2, kmLon = 111.32 * Math.cos(midLat * Math.PI / 180), kmLat = 110.57;
      const wide = this.W > 1100;
      const region = wide ? { x: this.W * 0.3, y: this.H * 0.11, w: this.W * 0.4, h: this.H * 0.68 } : { x: 24, y: this.H * 0.1, w: this.W - 48, h: this.H * 0.8 };
      const spanX = (maxLon - minLon) * kmLon, spanY = (maxLat - minLat) * kmLat;
      this.pxPerKm = Math.min(region.w / spanX, region.h / spanY);
      const ox = region.x + (region.w - spanX * this.pxPerKm) / 2, oy = region.y + (region.h - spanY * this.pxPerKm) / 2;
      this.at = p => ({ x: ox + (p.lon - minLon) * kmLon * this.pxPerKm, y: oy + (maxLat - p.lat) * kmLat * this.pxPerKm });
      this.points = this.world.farmers.map(f => ({ ...this.at(f), id: f.id, seed: f.id.charCodeAt(3) * 0.37 }));
      this.vets = this.world.vets.map(v => ({ ...this.at(v), id: v.id }));
      this.doctors = this.world.doctors.map(v => ({ ...this.at(v), id: v.id }));
    }

    pointOf(id) { return this.points.find(p => p.id === id); }

    update({ cases, ringIds, cluster, vetCalls, doctorCalls, night }) {
      this.night = night;
      const now = performance.now();
      this.cases = cases;
      this.cluster = cluster;
      ringIds.forEach((id, i) => {
        if (!this.called.has(id)) {
          this.called.set(id, now + 400 + i * 170);
          const to = this.pointOf(id), from = cluster && this.vets[0];
          if (to && from) this.arcs.push({ from, to, start: now + i * 170, dur: 1100, color: "#c9f26c" });
        }
      });
      if (!ringIds.length) { this.called.clear(); }
      (vetCalls || []).forEach(c => {
        const key = "v" + c.id;
        if (this[key]) return;
        this[key] = true;
        const to = this.vets.find(v => v.id === c.to_person), fromCase = cases.find(x => x.id === c.case_id);
        const from = fromCase && this.pointOf(fromCase.farmer_id);
        if (from && to) this.arcs.push({ from, to, start: now, dur: 1500, color: "#ffffff" });
      });
      (doctorCalls || []).forEach(c => {
        const key = "d" + c.id;
        if (this[key]) return;
        this[key] = true;
        const to = this.doctors[0], fromCase = cases.find(x => x.id === c.case_id);
        const from = fromCase && this.pointOf(fromCase.farmer_id);
        if (from && to) this.arcs.push({ from, to, start: now, dur: 1500, color: "#ff8a6b" });
      });
    }

    drawPin(ctx, p, label, fill) {
      ctx.save();
      ctx.shadowColor = "rgba(0,0,0,.4)"; ctx.shadowBlur = 8; ctx.shadowOffsetY = 2;
      ctx.fillStyle = fill;
      ctx.beginPath(); ctx.roundRect(p.x - 11, p.y - 11, 22, 22, 7); ctx.fill();
      ctx.restore();
      ctx.fillStyle = "#fff"; ctx.fillRect(p.x - 1.5, p.y - 6, 3, 12); ctx.fillRect(p.x - 6, p.y - 1.5, 12, 3);
      if (label) {
        ctx.font = "600 11px Figtree, sans-serif"; ctx.textAlign = "center";
        ctx.fillStyle = "#fff"; ctx.shadowColor = "rgba(0,0,0,.75)"; ctx.shadowBlur = 5;
        ctx.fillText(label, p.x, p.y + 25); ctx.shadowBlur = 0;
      }
    }

    loop(t) {
      this.t = t;
      const ctx = this.fx.getContext("2d"), dpr = this.dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, this.W, this.H);
      const slow = this.reduced ? 0 : t;

      // Ring around the cluster, drawn to true scale.
      if (this.cluster && this.clusterCentre()) {
        const c = this.clusterCentre(), R = (this.world.ring_km || 10) * this.pxPerKm;
        ctx.save();
        ctx.fillStyle = "rgba(255,112,80,.10)"; ctx.beginPath(); ctx.arc(c.x, c.y, R, 0, 7); ctx.fill();
        ctx.setLineDash([7, 7]); ctx.lineDashOffset = -slow * 0.012;
        ctx.strokeStyle = "rgba(255,190,165,.92)"; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(c.x, c.y, R, 0, 7); ctx.stroke();
        ctx.setLineDash([]);
        // radar sweep
        const a = (slow * 0.0009) % 6.283;
        const g = ctx.createConicGradient(a, c.x, c.y);
        g.addColorStop(0, "rgba(255,160,130,.26)"); g.addColorStop(0.14, "rgba(255,160,130,0)"); g.addColorStop(1, "rgba(255,160,130,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(c.x, c.y, R, 0, 7); ctx.fill();
        ctx.restore();
      }

      // Calls in flight.
      this.arcs = this.arcs.filter(a => t < a.start + a.dur + 900);
      this.arcs.forEach(a => {
        const k = Math.min(1, Math.max(0, (t - a.start) / a.dur));
        if (k <= 0) return;
        const mx = (a.from.x + a.to.x) / 2, my = (a.from.y + a.to.y) / 2 - Math.hypot(a.to.x - a.from.x, a.to.y - a.from.y) * 0.22;
        const fade = Math.max(0, 1 - Math.max(0, t - a.start - a.dur) / 900);
        ctx.save();
        ctx.globalAlpha = 0.85 * fade; ctx.strokeStyle = a.color; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(a.from.x, a.from.y);
        const steps = 26;
        for (let i = 1; i <= Math.floor(steps * k); i++) {
          const u = i / steps, x = (1 - u) ** 2 * a.from.x + 2 * (1 - u) * u * mx + u * u * a.to.x, y = (1 - u) ** 2 * a.from.y + 2 * (1 - u) * u * my + u * u * a.to.y;
          ctx.lineTo(x, y);
        }
        ctx.stroke();
        const x = (1 - k) ** 2 * a.from.x + 2 * (1 - k) * k * mx + k * k * a.to.x, y = (1 - k) ** 2 * a.from.y + 2 * (1 - k) * k * my + k * k * a.to.y;
        ctx.fillStyle = a.color; ctx.shadowColor = a.color; ctx.shadowBlur = 12;
        ctx.beginPath(); ctx.arc(x, y, 3, 0, 7); ctx.fill();
        ctx.restore();
      });

      // Households as points of light.
      const caseIds = new Set(this.cases.map(c => c.farmer_id));
      this.points.forEach(p => {
        const calledAt = this.called.get(p.id);
        const reached = calledAt && t >= calledAt;
        if (caseIds.has(p.id)) return;
        const twinkle = this.reduced ? 0.8 : 0.72 + 0.28 * Math.sin(t * 0.0016 + p.seed * 9);
        if (this.night) {
          const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, reached ? 15 : 11);
          glow.addColorStop(0, reached ? "rgba(201,242,108,.95)" : `rgba(255,200,120,${0.85 * twinkle})`);
          glow.addColorStop(1, "rgba(255,190,110,0)");
          ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(p.x, p.y, reached ? 15 : 11, 0, 7); ctx.fill();
          ctx.fillStyle = reached ? "#e6ffb0" : "#ffe9c4"; ctx.beginPath(); ctx.arc(p.x, p.y, 1.9, 0, 7); ctx.fill();
        } else {
          ctx.fillStyle = reached ? "#c9f26c" : "rgba(255,255,255,.92)";
          ctx.shadowColor = reached ? "#c9f26c" : "rgba(0,0,0,.5)"; ctx.shadowBlur = reached ? 12 : 3;
          ctx.beginPath(); ctx.arc(p.x, p.y, reached ? 4.2 : 2.5, 0, 7); ctx.fill();
          ctx.shadowBlur = 0;
        }
        if (calledAt && t >= calledAt && t < calledAt + 1500) {
          const k = (t - calledAt) / 1500;
          ctx.strokeStyle = `rgba(201,242,108,${1 - k})`; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(p.x, p.y, 4 + k * 22, 0, 7); ctx.stroke();
        }
      });

      this.vets.forEach((v, i) => this.drawPin(ctx, v, i === 0 ? "Vet" : "", "#0e6a4f"));
      this.doctors.forEach(d => this.drawPin(ctx, d, "Doctor", "#2d6cb3"));

      // Sick animals.
      this.cases.forEach(c => {
        const p = this.pointOf(c.farmer_id);
        if (!p) return;
        const flagged = c.red_flags.length > 0;
        for (let i = 0; i < 2; i++) {
          const k = this.reduced ? 0.4 : ((slow * 0.0007 + i * 0.5) % 1);
          ctx.strokeStyle = `rgba(255,112,80,${0.75 * (1 - k)})`; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(p.x, p.y, 7 + k * 25, 0, 7); ctx.stroke();
        }
        ctx.save(); ctx.shadowColor = "#ff7050"; ctx.shadowBlur = 14;
        ctx.fillStyle = flagged ? "#ff4a2e" : "#ff7050";
        ctx.beginPath(); ctx.arc(p.x, p.y, 6.5, 0, 7); ctx.fill(); ctx.restore();
        ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(p.x, p.y, 6.5, 0, 7); ctx.stroke();
      });

      // Leader line to the callout card.
      const callout = document.getElementById("callout");
      const focus = this.cases.find(c => c.id === this.focusId) || this.cases[0];
      if (focus && callout && !callout.hidden) {
        const p = this.pointOf(focus.farmer_id);
        if (p) {
          const cw = callout.offsetWidth, ch = callout.offsetHeight;
          let cx = p.x + 38, cy = p.y - ch - 30;
          if (cx + cw > this.W * 0.71) cx = p.x - cw - 38;
          if (cy < 92) cy = p.y + 30;
          if (cy < this.H * 0.4 && cx < this.W * 0.5) cy = p.y + 30; // keep clear of the headline
          // Appear in place the first time, then glide between cases.
          if (!callout.dataset.placed) { callout.style.transition = "none"; callout.dataset.placed = "1"; requestAnimationFrame(() => { callout.style.transition = ""; }); }
          callout.style.transform = `translate(${Math.round(cx)}px, ${Math.round(cy)}px)`;
          const ax = cx < p.x ? cx + cw : cx, ay = cy < p.y ? cy + ch - 16 : cy + 16;
          ctx.strokeStyle = "rgba(255,255,255,.92)"; ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(ax, ay); ctx.stroke();
          ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(ax, ay, 2.8, 0, 7); ctx.fill();
        }
      }
      requestAnimationFrame(n => this.loop(n));
    }

    clusterCentre() {
      const newest = this.cases.find(c => c.cluster);
      return newest ? this.pointOf(newest.farmer_id) : null;
    }
  }

  /* The voice orb: layered soft blobs that breathe with the conversation. */
  class Orb {
    constructor(canvas) { this.c = canvas; this.level = 0; this.target = 0; this.tone = 0; requestAnimationFrame(t => this.loop(t)); }
    set(level) { this.target = level; }
    loop(t) {
      const c = this.c, box = c.getBoundingClientRect();
      if (box.width && (c.width !== box.width * 2)) { c.width = box.width * 2; c.height = box.height * 2; }
      const ctx = c.getContext("2d"), W = c.width, H = c.height, cx = W / 2, cy = H / 2;
      ctx.clearRect(0, 0, W, H);
      if (!W) { requestAnimationFrame(n => this.loop(n)); return; }
      this.level += (this.target - this.level) * 0.12;
      const R = Math.min(W, H) * 0.3 * (1 + this.level * 0.42);
      const LAYERS = [["#0a7a5a", 1.0, 0.0011, 0], ["#2fd39a", 0.86, -0.0017, 2], ["#c9f26c", 0.62, 0.0023, 4], ["#eaffc2", 0.34, -0.003, 1]];
      ctx.globalCompositeOperation = "source-over";
      LAYERS.forEach(([color, size, speed, phase]) => {
        ctx.beginPath();
        for (let a = 0; a <= 6.3; a += 0.14) {
          const wob = 1 + (0.07 + this.level * 0.2) * Math.sin(a * 3 + t * speed + phase) + 0.045 * Math.sin(a * 5 - t * speed * 1.4 + phase);
          const x = cx + Math.cos(a) * R * size * wob, y = cy + Math.sin(a) * R * size * wob;
          a ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
        }
        ctx.closePath();
        const g = ctx.createRadialGradient(cx - R * 0.3, cy - R * 0.35, 0, cx, cy, R * size * 1.2);
        g.addColorStop(0, color); g.addColorStop(1, color + "33");
        ctx.fillStyle = g; ctx.fill();
      });
      requestAnimationFrame(n => this.loop(n));
    }
  }

  window.Emerald = { Stage, Orb };
})();
