/* The console. Polls the agent's real state and tells the story of one case at a time. */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SCENARIOS = {
  lsd: { signs: ["fever", "skin_nodules", "reduced_milk", "nasal_discharge"], weight: 320 },
  anthrax: { signs: ["sudden_death", "bleeding_from_body_openings"], weight: null },
  rabies: { signs: ["aggression", "abnormal_behaviour", "bitten_by_animal", "drooling"], weight: 300 },
  mastitis: { signs: ["swollen_udder", "abnormal_milk", "painful_udder", "fever"], weight: 350 },
};
const STEPS = ["call", "proof", "vet", "act", "ring"];
const LOG_NAMES = {
  case_recorded: "Case recorded", evidence_checked: "Evidence checked", second_opinion_deferred: "Second opinion waits for signal",
  second_opinion_completed: "Second opinion done", second_opinion_unavailable: "Second opinion unavailable", vet_called: "Vet called", doctor_called: "Doctor called",
  farmer_told: "Farmer told what to do", signoff_requested: "Vet asked to sign", signoff_approved: "Vet signed", signoff_declined: "Vet declined",
  signoff_rejected_bad_pin: "Wrong PIN refused", treatment_prescribed: "Treatment plan issued", vet_paid: "Vet paid", cluster_detected: "Cluster detected",
  outbreak_report_filed: "Outbreak report filed", ring_calls_started: "Ring calls made", action_refused: "Action refused", agent_sent_back: "Agent sent back to finish",
  case_run_finished: "Case run finished", model_usage: "Model use recorded", no_verified_evidence: "Nothing could be proven", vet_told_of_correction: "Vet told of a correction",
};
const ICON = {
  phone: '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1A17 17 0 0 1 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1z"/></svg>',
  rx: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M10.5 20.5a4.95 4.95 0 0 1-7-7l10-10a4.95 4.95 0 0 1 7 7z"/><path d="M8.5 8.5l7 7"/></svg>',
  money: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12M6 8h12M6 13l8.5 8M6 13h3a5 5 0 0 0 0-10"/></svg>',
  doc: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/></svg>',
  ring: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/></svg>',
  person: '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0z"/></svg>',
};

let world, stage, orb, S = null, activeTab = "proof", userTab = 0, seen = "", lastHeadline = "", callOn = false, syncNote = "";

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}
const capsule = warn => `<span class="capsule${warn ? " warn" : ""}" aria-hidden="true"></span>`;
const firstName = f => (f?.name || "A farmer").split(" ")[0];
const vetName = id => (world.vets.find(v => v.id === id)?.name || "the vet").replace(" (synthetic)", "");

function stageOf(s) {
  const focus = s.cases[0], cluster = s.cases.find(c => c.cluster);
  const ringDone = s.calls.some(c => c.purpose === "ring_alert");
  const busy = s.cases.some(c => c.job === "proving"), acting = s.cases.some(c => c.job === "acting");
  if (callOn && !focus) return "call";
  if (callOn && !s.pending.length && !busy) return "call";
  if (s.pending.length) return "vet";
  if (busy) return "proof";
  if (acting) return cluster ? "ring" : "act";
  if (ringDone) return "ring-done";
  if (focus) return "done";
  return "idle";
}

function headline(s, st) {
  const focus = s.cases[0], cluster = s.cases.find(c => c.cluster);
  const ring = s.calls.filter(c => c.purpose === "ring_alert").length;
  const pendingOutbreak = s.pending.some(p => p.tool === "file_outbreak_report" || p.tool === "start_ring_calls");
  const flagged = focus && focus.red_flags.length;
  const off = s.lane === "offline";
  switch (st) {
    case "call": return { a: `A farmer ${capsule()}`, b: "is on the line.", p: "No app, no reading. Just a phone call." };
    case "proof":
      if (flagged) return { a: `Red flag. ${capsule(true)}`, b: "Safety comes first.", p: "The farmer already has the safety steps and a doctor is being called. Now the evidence is checked." };
      return { a: `Checking ${capsule()}`, b: "every claim.", p: off ? "On this laptop, the same rules apply: a claim with no source sentence doesn't get through." : "Each claim must point to a sentence in an official source. A second model looks for overreach." };
    case "vet":
      if (pendingOutbreak) return { a: `${cluster ? cluster.cluster.cases.length : 3} calls. ${capsule(true)}`, b: "One outbreak?", p: `Cases cluster within 10 km. The report and the warning calls wait for ${vetName("V01")}.` };
      return { a: `Nothing happens ${capsule()}`, b: "until the vet signs.", p: "Treatment and money are locked. A signature covers one exact action, once." };
    case "act": return { a: `Signed. ${capsule()}`, b: "Now it acts.", p: "The tool itself re-checks the vet's signature before anything happens." };
    case "ring": return { a: `Signed. ${capsule(true)}`, b: "Warning the ring.", p: "Every registered home around the outbreak gets a call." };
    case "ring-done": return { a: `${ring} homes ${capsule()}`, b: "warned. All on record.", p: "One report under section 4 of the 2009 Act, one round of calls, and a signed chain anyone can re-check." };
    case "done": return { a: `${firstName(focus.farmer)}'s case ${capsule()}`, b: "is on record.", p: "Vet called, evidence attached, and every step in a signed chain." };
    default: return { a: `Every sick animal ${capsule()}`, b: "gets a call back.", p: "A phone line for smallholder farmers that acts on the call, proves its work, and asks a vet before anything irreversible." };
  }
}

function renderHero(s, st) {
  const h = headline(s, st), key = st + h.b;
  if (key !== lastHeadline) {
    lastHeadline = key;
    $("headline").innerHTML = `<span class="swap">${h.a}</span><span class="swap" style="animation-delay:.08s">${esc(h.b)}</span>`;
    $("subline").textContent = h.p;
  }
  $("cta").hidden = !(st === "idle" || st === "done" || st === "ring-done");
  $("heroCall").textContent = "";
  $("heroCall").innerHTML = s.lane === "offline" ? 'Log a case below <span class="go" aria-hidden="true">↓</span>' : 'Call the line <span class="go" aria-hidden="true">↗</span>';
  const now = { idle: -1, call: 0, proof: 1, vet: 2, act: 3, ring: 4, "ring-done": 5, done: 4 }[st];
  document.querySelectorAll(".step").forEach((el, i) => {
    el.classList.toggle("now", i === now);
    el.classList.toggle("done", i < now);
    el.querySelector("i").textContent = i < now ? "✓" : i + 1;
  });
}

function highlight(quote, claim) {
  // Mark the words the claim and its source share, so the eye can check the support.
  const words = new Set(claim.toLowerCase().match(/[a-z]{5,}/g) || []);
  return esc(quote).replace(/[A-Za-z]{5,}/g, w => (words.has(w.toLowerCase()) ? `<mark>${w}</mark>` : w));
}

function renderProof(s) {
  if (!s.cases.length) return `<div class="pane-title">What no model can do here</div>
    <div class="promise"><span class="big">0</span><div><b>doses written by a model</b><small>Dose arithmetic is code, from rows quoted out of the official guidelines.</small></div></div>
    <div class="promise"><span class="big">0</span><div><b>unsigned irreversible actions</b><small>Treatment, payment, reports and warning calls each need a vet's signature on that exact action.</small></div></div>
    <div class="promise"><span class="big">0</span><div><b>misquotes</b><small>Models cite a numbered sentence, and code fills in the words. A second model rejects overreach.</small></div></div>
    <div class="promise"><span class="big">1</span><div><b>tamper-evident record</b><small>Every step is signed and chained, and you can try to break it yourself.</small></div></div>`;
  return s.cases.map(c => {
    const ok = c.evidence.verified.map(v => `<div class="proof"><span>${esc(v.claim)}</span><q title="Click to read it all">${highlight(v.quote, v.claim)}</q><span class="src">${esc(shortCite(v.citation))}</span></div>`).join("");
    const no = c.evidence.rejected.map(v => `<div class="proof no"><s>${esc(v.claim)}</s><span class="why">Rejected: ${esc(v.reason)}</span></div>`).join("");
    const flags = c.red_flags.map(f => `<div class="flag">${esc(f.instruction)}</div>`).join("");
    const wait = c.job === "proving" && !c.evidence.verified.length ? '<div class="shimmer"></div><div class="shimmer short"></div>' : "";
    const deferred = c.evidence.second_opinion_deferred ? ' <span class="badge">second opinion waits for signal</span>' : "";
    return `<div class="casehead"><b>${esc(c.farmer?.name)}</b><span>${esc((c.candidates[0] && c.candidates[0].name) || "No match")}${deferred}</span></div>${flags}${no}${ok}${wait}`;
  }).join("");
}

function shortCite(text) {
  return String(text).replace("Standard Veterinary Treatment Guidelines for Livestock and Poultry (DAHD, 2024)", "Vet Treatment Guidelines, 2024")
    .replace("Prevention and Control of Infectious and Contagious Diseases in Animals Act, 2009", "Animal Diseases Act, 2009")
    .replace("Lumpy skin disease: A field manual for veterinarians (FAO, 2017)", "FAO field manual, 2017").replace("PDF page", "p.");
}

function actionItems(s) {
  const items = [];
  const ring = s.calls.filter(c => c.purpose === "ring_alert");
  if (ring.length) items.push(`<div class="act"><span class="ico lime">${ICON.ring}</span><div><b>${ring.length} homes warned</b><small>${esc(ring[0].script)}</small></div></div>`);
  s.reports.forEach(r => items.push(`<div class="act"><span class="ico hot">${ICON.doc}</span><div><b>Outbreak report filed</b><small>${esc(r.body)}</small></div></div>`));
  s.prescriptions.forEach(r => {
    const d = JSON.parse(r.detail);
    items.push(`<div class="act"><span class="ico">${ICON.rx}</span><div><b>${esc(d.drug)} ${esc(d.total_dose)} ${esc(d.route)}</b><small>Dose from code at ${d.weight_kg} kg, for the vet to give. Source: “${esc(d.source_quote)}”</small></div></div>`);
  });
  s.payments.forEach(p => items.push(`<div class="act"><span class="ico">${ICON.money}</span><div><b>₹${Math.round(p.amount)} paid to ${esc(vetName(p.to_vet))}</b><small>From the village fund, on the vet's signature.</small></div></div>`));
  s.calls.filter(c => c.to_role === "doctor").forEach(c => items.push(`<div class="act"><span class="ico hot">${ICON.person}</span><div><b>Doctor called</b><small>${esc(c.script)}</small></div></div>`));
  s.calls.filter(c => c.to_role === "farmer").forEach(c => items.push(`<div class="act"><span class="ico">${ICON.phone}</span><div><b>Farmer told what to do</b><small>${esc(c.script)}</small></div></div>`));
  s.calls.filter(c => c.to_role === "vet").forEach(c => items.push(`<div class="act"><span class="ico">${ICON.phone}</span><div><b>${esc(vetName(c.to_person))} called</b><small>${esc(c.script || "Evidence pack read out.")}</small></div></div>`));
  return items;
}

function renderActions(s) {
  const items = actionItems(s);
  return items.length ? items.join("") : '<div class="empty">Calls, reports and payments appear here as they happen.</div>';
}

function renderLedger(s) {
  const v = s.verification, broken = v.ok ? null : v.broken_at;
  const head = v.ok
    ? `<div class="verdict"><div class="big">${v.entries}</div><div><b>entries, chain intact</b><small>Each one is signed and linked to the one before it. Head ${esc((v.head || "").slice(0, 12))}…</small></div></div>`
    : `<div class="verdict bad"><div class="big">#${esc(broken)}</div><div><b>Someone changed this record</b><small>The chain no longer adds up, so the edit shows. A broken record is never uploaded.</small></div></div>`;
  const tools = `<div class="ledger-tools">
    ${s.tampered ? '<button class="pill" id="restoreBtn">Put it back</button>' : `<button class="pill" id="tamperBtn"${s.ledger_total ? "" : " disabled"}>Try to change a past record</button>`}
    ${s.can_sync && !s.tampered ? `<button class="pill" id="syncBtn"${s.lane === "offline" || !s.unsynced ? " disabled" : ""}>Seal ${s.unsynced} in S3</button>` : ""}
  </div>${syncNote ? `<p class="hint" style="margin:0 0 8px">${esc(syncNote)}</p>` : ""}`;
  const rows = s.ledger.filter(e => e.type !== "model_usage").map(e => `<div class="block${broken && e.seq === broken ? " broken" : ""}"><span class="n">#${e.seq}</span><span class="t">${esc(LOG_NAMES[e.type] || e.type)}</span><span class="h">${esc(e.hash.slice(0, 8))}</span></div>`).join("");
  return `<div class="ledger-head">${head}${tools}</div>` + (rows || '<div class="empty">Empty so far.</div>');
}

function renderPane(s) {
  const html = activeTab === "proof" ? renderProof(s) : activeTab === "actions" ? renderActions(s) : renderLedger(s);
  const key = activeTab + html;
  if (key !== seen) {
    const pane = $("pane"), top = pane.scrollTop;
    // Only new items animate: a full re-render shouldn't replay everything.
    pane.innerHTML = html;
    pane.querySelectorAll(".proof,.act,.block").forEach(el => { if (seen) el.style.animation = "none"; });
    pane.scrollTop = top;
    seen = key;
    pane.querySelector(".block.broken")?.scrollIntoView({ block: "center" });
  }
  document.querySelector(".panel").classList.toggle("compact", !s.cases.length);
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.dataset.tab === activeTab));
  const claims = s.cases.reduce((n, c) => n + c.evidence.verified.length, 0);
  $("nProof").textContent = claims || "";
  $("nActions").textContent = actionItems(s).length || "";
  $("nLedger").textContent = s.ledger_total || "";
}

function renderVet(s) {
  const box = $("vet");
  const item = s.pending[0];
  if (!item) { box.hidden = true; box.dataset.id = ""; return; }
  if (box.dataset.id === item.id && !box.hidden) {
    box.querySelector(".count").textContent = `${s.pending.length} waiting`;
    return;
  }
  const parts = item.summary.split(/(?<=\.)\s(?=Milk|Source)/);
  box.hidden = false;
  box.dataset.id = item.id;
  box.innerHTML = `<div class="vet-top"><span>${esc(vetName("V01"))}, nearest vet</span><span class="count">${s.pending.length} waiting</span></div>
    <h3>${esc(parts[0])}</h3>
    ${parts.length > 1 ? `<div class="detail">${esc(parts.slice(1).join(" "))}</div>` : ""}
    <div class="detail" style="margin-top:6px">Signs action <code>${esc(item.action_hash.slice(0, 16))}…</code> with this vet's key. Change one detail and it no longer applies.</div>
    <div class="vet-actions">
      <button class="hold" id="holdBtn" aria-label="Press and hold to approve and sign"><span class="fill"></span><span>Press and hold to sign</span></button>
      <button class="decline" id="declineBtn">Decline</button>
    </div>`;
  wireHold(item);
  $("declineBtn").onclick = async () => { await post(`/api/signoffs/${item.id}`, { vet_id: "V01", pin: world.demo_vet_pin, approve: false }); box.dataset.id = ""; tick(); };
}

function wireHold(item) {
  const btn = $("holdBtn"), fill = btn.querySelector(".fill"), HOLD_MS = 1100;
  let start = 0, raf = 0, done = false;
  const step = t => {
    const k = Math.min(1, (t - start) / HOLD_MS);
    fill.style.width = k * 100 + "%";
    if (k >= 1) { finish(); return; }
    raf = requestAnimationFrame(step);
  };
  const begin = () => { if (done || start) return; start = performance.now(); btn.classList.add("signing"); raf = requestAnimationFrame(step); };
  const cancel = () => { if (done) return; cancelAnimationFrame(raf); start = 0; fill.style.width = 0; btn.classList.remove("signing"); };
  const finish = async () => {
    done = true;
    btn.querySelector("span:last-child").textContent = "Signed";
    const res = await post(`/api/signoffs/${item.id}`, { vet_id: "V01", pin: world.demo_vet_pin, approve: true });
    if (!res.ok) { btn.querySelector("span:last-child").textContent = res.data.reason || "Refused"; return; }
    $("vet").dataset.id = "";
    tick();
  };
  btn.addEventListener("pointerdown", e => { try { btn.setPointerCapture(e.pointerId); } catch { /* not a real pointer */ } begin(); });
  btn.addEventListener("pointerup", cancel);
  btn.addEventListener("pointercancel", cancel);
  btn.addEventListener("keydown", e => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); begin(); } });
  btn.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") cancel(); });
}

function renderCallout(s) {
  const box = $("callout"), c = s.cases[0];
  if (!c) { box.hidden = true; return; }
  stage.focusId = c.id;
  const name = c.candidates[0] ? c.candidates[0].name : "No clear match";
  const html = `<b>${esc(c.farmer?.name)}</b><div class="sub">${esc(c.farmer?.village)}. ${esc(c.signs.slice(0, 3).join(", ").replaceAll("_", " "))}</div><span class="maybe">Could be ${esc(name.toLowerCase())}</span>`;
  if (box.dataset.h !== html) { box.innerHTML = html; box.dataset.h = html; }
  box.hidden = false;
}

function countUp(id, value, prefix = "") {
  const el = $(id), from = Number(el.dataset.v || 0);
  if (from === value) return;
  el.dataset.v = value;
  const start = performance.now();
  const run = t => {
    const k = Math.min(1, (t - start) / 700), now = Math.round(from + (value - from) * (1 - (1 - k) ** 3));
    el.textContent = prefix + now.toLocaleString("en-IN");
    if (k < 1) requestAnimationFrame(run);
  };
  requestAnimationFrame(run);
}

function render(s) {
  const prevStage = S ? stageOf(S) : null;
  S = s;
  if (!s.cases.length) activeTab = "proof"; // a cleared console opens on what no model can do
  const off = s.lane === "offline";
  document.body.classList.toggle("offline", off);
  $("nightBanner").hidden = !off;
  $("signal").setAttribute("aria-checked", String(!off));
  $("signalText").textContent = off ? "No signal" : "Signal on";
  const v = s.verification;
  $("verifyChip").classList.toggle("bad", !v.ok);
  $("verifyText").textContent = v.ok ? `Ledger verified · ${v.entries}` : `Record changed at #${v.broken_at}`;
  const st = stageOf(s);
  // The panel follows the story, unless the viewer just picked a tab themselves.
  if (st !== prevStage && Date.now() - userTab > 9000) {
    activeTab = { proof: "proof", vet: "proof", act: "actions", ring: "actions", "ring-done": "actions", done: "proof" }[st] || activeTab;
  }
  renderHero(s, st);
  renderPane(s);
  renderVet(s);
  renderCallout(s);
  const ring = s.calls.filter(c => c.purpose === "ring_alert");
  stage.update({
    cases: s.cases, ringIds: ring.map(c => c.to_person), cluster: s.cases.find(c => c.cluster)?.cluster || null,
    vetCalls: s.calls.filter(c => c.to_role === "vet"), doctorCalls: s.calls.filter(c => c.to_role === "doctor"), night: off,
  });
  countUp("nCases", s.cases.length);
  countUp("nSigned", s.signoffs.filter(x => x.status === "approved").length);
  countUp("nRing", ring.length);
  countUp("nPaid", Math.round(s.payments.reduce((n, p) => n + p.amount, 0)), "₹");
  if (!callOn) { orb.set(st === "proof" || st === "act" || st === "ring" ? 0.25 : st === "vet" ? 0.1 : 0); }
  $("callTitle").textContent = callOn ? "On the call" : off ? "Field worker entry" : "The vet line";
}

let polling = false;
async function tick() {
  if (polling) return;
  polling = true;
  try { render(await (await fetch("/api/state")).json()); } catch (e) { /* the server may be restarting */ } finally { polling = false; }
}

/* Voice: 16 kHz mono PCM both ways. */
let socket, audioCtx, micStream, micNode, playAt = 0, liveSources = [];
function say(role, text) {
  const box = $("lines"), div = document.createElement("div");
  div.className = "say " + role;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function playPcm(b64) {
  const raw = atob(b64), pcm = new Int16Array(raw.length / 2);
  let peak = 0;
  for (let i = 0; i < pcm.length; i++) { pcm[i] = (raw.charCodeAt(2 * i + 1) << 8 | raw.charCodeAt(2 * i)) << 16 >> 16; peak = Math.max(peak, Math.abs(pcm[i])); }
  const buf = audioCtx.createBuffer(1, pcm.length, 16000), ch = buf.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
  const src = audioCtx.createBufferSource();
  src.buffer = buf; src.connect(audioCtx.destination);
  playAt = Math.max(playAt, audioCtx.currentTime + .05);
  src.start(playAt);
  playAt += buf.duration;
  orb.set(Math.min(1, peak / 16000));
  liveSources.push(src);
  src.onended = () => { liveSources = liveSources.filter(x => x !== src); if (!liveSources.length) orb.set(.12); };
}
async function startCall() {
  if (S?.lane === "offline") { say("tool", "Voice needs signal. Log the case with the buttons below."); return; }
  audioCtx = new AudioContext({ sampleRate: 16000 });
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/call/${$("caller").value}`);
  socket.binaryType = "arraybuffer";
  socket.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === "audio") playPcm(m.audio);
    else if (m.type === "transcript") {
      // Nova Sonic can spell a short Indian-English line in Devanagari, though it understood it: this log stays English.
      if (m.role !== "user" || !/[ऀ-ॿ]/.test(m.text)) say(m.role === "user" ? "user" : "assistant", m.text);
    }
    else if (m.type === "tool") say("tool", "Agent used: " + m.names.join(", "));
    else if (m.type === "barge_in") { liveSources.forEach(s => s.stop()); liveSources = []; playAt = 0; }
    else if (m.type === "no_signal") say("tool", "Voice needs signal. Log the case with the buttons below.");
  };
  socket.onclose = () => stopCall();
  socket.onopen = () => {
    callOn = true;
    const source = audioCtx.createMediaStreamSource(micStream);
    micNode = audioCtx.createScriptProcessor(2048, 1, 1);
    micNode.onaudioprocess = e => {
      if (socket?.readyState !== 1) return;
      const input = e.inputBuffer.getChannelData(0), out = new Int16Array(input.length);
      let peak = 0;
      for (let i = 0; i < input.length; i++) { out[i] = Math.max(-1, Math.min(1, input[i])) * 32767; peak = Math.max(peak, Math.abs(input[i])); }
      if (!liveSources.length) orb.set(Math.min(.8, peak * 2.2));
      socket.send(out.buffer);
    };
    source.connect(micNode);
    micNode.connect(audioCtx.destination);
    $("callBtn").classList.add("hang");
    $("callBtn").setAttribute("aria-label", "End the call");
    $("lines").innerHTML = "";
    $("scenarios").hidden = true;
    tick();
  };
}
function stopCall() {
  try { socket?.close(); } catch { /* already closed */ }
  micStream?.getTracks().forEach(t => t.stop());
  micNode?.disconnect();
  audioCtx?.close();
  socket = audioCtx = micStream = micNode = null;
  playAt = 0; callOn = false;
  $("callBtn").classList.remove("hang");
  $("callBtn").setAttribute("aria-label", "Start the call");
  $("scenarios").hidden = false;
  orb.set(0);
  tick();
}
const toggleCall = () => (socket ? stopCall() : startCall().catch(e => say("tool", "Could not start the call: " + e.message)));

const nearbyFarmers = n => {
  const r = Math.PI / 180;
  const km = (a, b) => 6371 * 2 * Math.asin(Math.sqrt(Math.sin((b.lat - a.lat) * r / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin((b.lon - a.lon) * r / 2) ** 2));
  // The story starts just south of the map's centre, in the open part of the screen.
  const lats = world.farmers.map(f => f.lat), lons = world.farmers.map(f => f.lon);
  const spot = { lat: Math.min(...lats) * 0.62 + Math.max(...lats) * 0.38, lon: (Math.min(...lons) + Math.max(...lons)) / 2 };
  const picked = [];
  for (const f of [...world.farmers].sort((a, b) => km(spot, a) - km(spot, b))) {
    if (picked.every(p => km(p, f) >= 2.5)) picked.push(f); // far enough apart to read on the map, close enough to be a cluster
    if (picked.length === n) break;
  }
  return picked;
};

async function playStory() {
  $("storyBtn").disabled = true;
  const taken = new Set((S?.cases || []).map(c => c.farmer_id));
  for (const f of nearbyFarmers(8).filter(f => !taken.has(f.id)).slice(0, 3)) {
    await post("/api/calls", { farmer_id: f.id, signs: SCENARIOS.lsd.signs, weight_kg: SCENARIOS.lsd.weight });
    await tick();
    await new Promise(r => setTimeout(r, 5000));
  }
  $("storyBtn").disabled = false;
}

function wire() {
  $("callBtn").onclick = toggleCall;
  $("heroCall").onclick = () => (S?.lane === "offline" ? document.querySelector(".pill[data-s]").focus() : toggleCall());
  $("storyBtn").onclick = playStory;
  $("signal").onclick = async () => {
    await post("/api/lane", { lane: S?.lane === "offline" ? "cloud" : "offline" });
    syncNote = "";
    if (socket) stopCall();
    tick();
  };
  $("scenarios").onclick = async e => {
    const b = e.target.closest("button[data-s]");
    if (!b) return;
    const sc = SCENARIOS[b.dataset.s], taken = new Set((S?.cases || []).map(c => c.farmer_id));
    const who = taken.has($("caller").value) ? world.farmers.find(f => !taken.has(f.id)).id : $("caller").value;
    await post("/api/calls", { farmer_id: who, signs: sc.signs, weight_kg: sc.weight });
    tick();
  };
  document.querySelector(".tabs").onclick = e => {
    const t = e.target.closest(".tab");
    if (t) { activeTab = t.dataset.tab; userTab = Date.now(); if (S) renderPane(S); }
  };
  $("pane").addEventListener("click", async e => {
    const quote = e.target.closest("q");
    if (quote) quote.classList.toggle("open");
    const id = e.target.id;
    if (id === "tamperBtn") { await post("/api/demo/tamper"); userTab = Date.now(); tick(); }
    if (id === "restoreBtn") { await post("/api/demo/restore"); tick(); }
    if (id === "syncBtn") {
      e.target.disabled = true; e.target.textContent = "Sealing…";
      const res = await post("/api/sync");
      syncNote = res.ok
        ? `${res.data.uploaded} entries sealed in S3 Object Lock. ${res.data.second_opinions.length} deferred second opinions done, ${res.data.second_opinions.reduce((n, x) => n + x.failed.length, 0)} claims sent back to the vet.`
        : (res.data.reason || "Could not sync.");
      seen = ""; tick();
    }
  });
  addEventListener("keydown", e => { // a quiet way to clear the demo between takes
    if (e.shiftKey && e.key === "R" && e.target.tagName !== "SELECT") { post("/api/demo/reset").then(() => { syncNote = ""; $("lines").innerHTML = ""; tick(); }); }
  });
}

(async () => {
  world = await (await fetch("/api/world")).json();
  $("caller").innerHTML = world.farmers.map(f => `<option value="${f.id}">${esc(f.name)}, ${esc(f.village)}</option>`).join("");
  $("caller").value = nearbyFarmers(1)[0].id; // open with someone in the clear part of the map
  await document.fonts.ready;
  stage = new Emerald.Stage($("land"), $("fx"), world);
  orb = new Emerald.Orb($("orb"));
  wire();
  await tick();
  setInterval(tick, 1200);
})();
