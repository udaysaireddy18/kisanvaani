let claimId = null;

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const statusEl = $("status");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function setStatus(msg, isError = false) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (isError ? " error" : "");
}

const languageSelect = $("language");
const voiceBtn = $("voiceBtn");
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

function currentLanguage() {
  return languageSelect ? languageSelect.value : "hi";
}

function initRecognition() {
  if (!SpeechRecognition) return;
  recognition = new SpeechRecognition();
  recognition.lang = currentLanguage();
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.continuous = false;

  recognition.onstart = () => {
    listening = true;
    voiceBtn.classList.add("listening");
    voiceBtn.textContent = "■ Stop";
    setStatus("Listening... speak now.");
  };

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(" ")
      .trim();
    if (!transcript) return;
    const box = $("message");
    box.value = box.value.trim() ? `${box.value.trim()} ${transcript}` : transcript;
    setStatus("Transcript added. Review it, then click Send Message.");
  };

  recognition.onerror = (event) => {
    const errors = {
      "not-allowed": "Microphone permission denied. Allow mic access and try again.",
      "no-speech": "No speech detected. Try again.",
      "audio-capture": "No microphone found.",
      "network": "Speech service unavailable. You can type the message instead.",
    };
    setStatus(errors[event.error] || `Voice error: ${event.error}`, true);
  };

  recognition.onend = () => {
    listening = false;
    voiceBtn.classList.remove("listening");
    voiceBtn.textContent = "🎙 Speak";
  };
}

function toggleVoice() {
  if (!SpeechRecognition) {
    setStatus("Voice input is not supported in this browser. Use Chrome/Edge, or type the message.", true);
    return;
  }
  if (!recognition) initRecognition();
  if (listening) {
    recognition.stop();
    return;
  }
  recognition.lang = currentLanguage();
  try {
    recognition.start();
  } catch (err) {
    setStatus(`Could not start voice input: ${err.message}`, true);
  }
}

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function renderClaim(claim) {
  const el = $("claim");
  const pdfArea = $("pdfArea");
  if (!claim) {
    el.innerHTML = '<div class="muted">No claim yet. Send a message to start.</div>';
    pdfArea.innerHTML = "";
    renderReview(null);
    renderTimeline(null);
    return;
  }
  claimId = claim.id;
  renderReview(claim);
  renderTimeline(claim);
  const fields = [
    ["Claim ID", claim.id], ["Status", claim.status], ["Phone", claim.farmer_phone],
    ["Crop", claim.crop || "-"], ["Damage", claim.damage_type || "-"], ["Village", claim.village || "-"],
    ["Incident Date", claim.incident_date || "-"], ["Missing", (claim.missing_fields || []).join(", ") || "None"],
    ["Photos", String(claim.photo_count ?? 0)], ["Confidence", String(claim.confidence ?? 0)],
  ];
  el.innerHTML = fields.map(([k, v]) => `<div class="field"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div></div>`).join("");

  if (claim.status === "READY" || claim.status === "PDF_GENERATED") {
    const pdfBtn = claim.status === "PDF_GENERATED"
      ? `<a class="btn primary" href="/api/claims/${escapeHtml(claim.id)}/pdf" target="_blank">Download PDF</a>`
      : `<button class="btn primary" id="genPdfBtn">Generate PDF</button>`;
    pdfArea.innerHTML = pdfBtn;
    const gen = $("genPdfBtn");
    if (gen) gen.onclick = generatePdf;
  } else {
    pdfArea.innerHTML = '<span class="muted">PDF available when claim is READY (all fields + at least 1 photo).</span>';
  }
}

function renderTimeline(claim) {
  const el = $("timelineArea");
  if (!claim) {
    el.innerHTML = "";
    return;
  }
  const events = claim.timeline || [];
  if (!events.length) {
    el.innerHTML = '<p class="muted">No status events yet.</p>';
    return;
  }
  el.innerHTML = `
    <div class="timeline-card">
      <h3>Status timeline</h3>
      <ol class="timeline">
        ${events.map((event) => `
          <li class="timeline-item">
            <span class="dot"></span>
            <div class="timeline-body">
              <div class="timeline-label">${escapeHtml(event.label)}</div>
              <div class="timeline-meta">${escapeHtml(event.status)} · ${escapeHtml(formatTime(event.created_at))}</div>
            </div>
          </li>`).join("")}
      </ol>
    </div>`;
}

function renderReview(claim) {
  const el = $("reviewArea");
  if (!claim) {
    el.innerHTML = '<p class="muted">Review fields appear here after you send a message.</p>';
    return;
  }
  if (claim.status === "PDF_GENERATED") {
    el.innerHTML = '<p class="muted">PDF already generated. Start a new demo claim to edit details.</p>';
    return;
  }
  el.innerHTML = `
    <div class="review-card">
      <div class="row">
        <h3>Review extracted details</h3>
        <span class="muted">Correct anything wrong, then save.</span>
      </div>
      <div class="review-grid">
        <label>Crop<input id="editCrop" type="text" maxlength="64" value="${escapeHtml(claim.crop || "")}" placeholder="e.g. sugarcane"></label>
        <label>Damage type<input id="editDamage" type="text" maxlength="64" value="${escapeHtml(claim.damage_type || "")}" placeholder="e.g. rain"></label>
        <label>Village<input id="editVillage" type="text" maxlength="128" value="${escapeHtml(claim.village || "")}" placeholder="e.g. Rampur"></label>
        <label>Incident date<input id="editDate" type="text" maxlength="32" value="${escapeHtml(claim.incident_date || "")}" placeholder="DD/MM/YYYY"></label>
      </div>
      <div class="actions">
        <button id="saveDetailsBtn" class="btn primary">Save Details</button>
      </div>
    </div>`;
  $("saveDetailsBtn").addEventListener("click", saveDetails);
}

async function saveDetails() {
  if (!claimId) return;
  const btn = $("saveDetailsBtn");
  const payload = {
    crop: $("editCrop").value.trim(),
    damage_type: $("editDamage").value.trim(),
    village: $("editVillage").value.trim(),
    incident_date: $("editDate").value.trim(),
    language: currentLanguage(),
  };
  if (btn) btn.disabled = true;
  setStatus("Saving details...");
  try {
    const data = await api(`/api/claims/${claimId}/details`, { method: "PUT", body: JSON.stringify(payload) });
    (data.replies || []).forEach(r => addMsg("bot", r));
    renderClaim(data.claim);
    await loadClaims();
    setStatus("Details saved.");
  } catch (e) { setStatus(e.message, true); }
  finally { if (btn) btn.disabled = false; }
}

async function refreshClaim() {
  if (!claimId) return;
  try {
    const data = await api(`/api/claims/${claimId}`);
    renderClaim(data.claim);
  } catch (e) { setStatus(e.message, true); }
}

async function loadClaims() {
  try {
    const data = await api("/api/claims");
    const body = $("claimsBody");
    if (!data.claims.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted">No claims yet.</td></tr>';
      return;
    }
    body.innerHTML = data.claims.map(c => {
      const id = escapeHtml(c.id);
      return `
      <tr>
        <td><a href="#" class="link" data-id="${id}">${id}</a></td>
        <td>${escapeHtml(c.farmer_phone)}</td><td>${escapeHtml(c.status)}</td><td>${escapeHtml(c.crop || "-")}</td>
        <td>${escapeHtml(c.damage_type || "-")}</td><td>${escapeHtml(c.village || "-")}</td><td>${escapeHtml(c.incident_date || "-")}</td>
        <td>${c.pdf_path ? `<a class="link" href="/api/claims/${id}/pdf" target="_blank">PDF</a>` : "-"}</td>
      </tr>`;
    }).join("");
    body.querySelectorAll("a[data-id]").forEach(a => a.addEventListener("click", async (e) => {
      e.preventDefault();
      claimId = a.dataset.id;
      await refreshClaim();
      setStatus(`Loaded ${claimId}`);
    }));
  } catch (e) { setStatus(e.message, true); }
}

async function sendMessage() {
  const phone = $("phone").value.trim();
  const message = $("message").value.trim();
  if (!phone || !message) return setStatus("Phone and message are required.", true);
  $("sendBtn").disabled = true;
  setStatus("Sending...");
  addMsg("user", message);
  try {
    const data = await api("/api/web/messages", { method: "POST", body: JSON.stringify({ phone, message, claim_id: claimId, language: currentLanguage() }) });
    (data.replies || []).forEach(r => addMsg("bot", r));
    renderClaim(data.claim);
    $("message").value = "";
    await loadClaims();
    setStatus("Message processed.");
  } catch (e) { setStatus(e.message, true); }
  finally { $("sendBtn").disabled = false; }
}

async function uploadPhoto() {
  const file = $("photo").files[0];
  const phone = $("phone").value.trim();
  if (!file) return setStatus("Select a photo first.", true);
  if (!phone) return setStatus("Phone is required.", true);
  $("photoBtn").disabled = true;
  setStatus("Uploading photo...");
  try {
    const fd = new FormData();
    fd.append("photo", file);
    fd.append("phone", phone);
    fd.append("language", currentLanguage());
    if (claimId) fd.append("claim_id", claimId);
    const res = await fetch("/api/web/photos", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Upload failed");
    addMsg("user", `[Photo uploaded: ${file.name}]`);
    (data.replies || []).forEach(r => addMsg("bot", r));
    renderClaim(data.claim);
    $("photo").value = "";
    await loadClaims();
    setStatus("Photo uploaded.");
  } catch (e) { setStatus(e.message, true); }
  finally { $("photoBtn").disabled = false; }
}

async function generatePdf() {
  if (!claimId) return;
  setStatus("Generating PDF...");
  try {
    const data = await api(`/api/claims/${claimId}/pdf`, { method: "POST" });
    renderClaim(data.claim);
    await loadClaims();
    setStatus("PDF generated.");
    window.open(`/api/claims/${claimId}/pdf`, "_blank");
  } catch (e) { setStatus(e.message, true); }
}

$("sendBtn").addEventListener("click", sendMessage);
$("photoBtn").addEventListener("click", uploadPhoto);
voiceBtn.addEventListener("click", toggleVoice);
languageSelect.addEventListener("change", () => {
  if (recognition) recognition.lang = currentLanguage();
  setStatus(`Language set to ${languageSelect.options[languageSelect.selectedIndex].text}.`);
});
$("refreshBtn").addEventListener("click", async () => { await refreshClaim(); await loadClaims(); });
$("resetBtn").addEventListener("click", () => { claimId = null; chat.innerHTML = ""; renderClaim(null); setStatus("Started new demo claim session."); });
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });

renderClaim(null);
loadClaims();
