let claimId = null;
let currentClaim = null;

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const statusEl = $("status");
const MIN_IMAGE_WIDTH = 480;
const MIN_IMAGE_HEIGHT = 360;
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
let pendingPhotos = [];
let previewUrls = [];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(currentLanguage());
}

function displayStatus(status) {
  const key = "statusValue." + status;
  const translated = t(key);
  return translated === key ? status : translated;
}

function displayEvent(label) {
  const key = "timeline." + label;
  const translated = t(key);
  return translated === key ? label : translated;
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

// Restore the saved language before rendering any dynamic content.
const savedLang = i18nGetLang();
if (languageSelect) languageSelect.value = savedLang;
i18nSetLang(savedLang);

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
    voiceBtn.textContent = t("report.stop");
    setStatus(t("status.listening"));
  };

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(" ")
      .trim();
    if (!transcript) return;
    const box = $("message");
    box.value = box.value.trim() ? `${box.value.trim()} ${transcript}` : transcript;
    setStatus(t("status.transcriptAdded"));
  };

  recognition.onerror = (event) => {
    const errors = {
      "not-allowed": t("voice.not-allowed"),
      "no-speech": t("voice.no-speech"),
      "audio-capture": t("voice.audio-capture"),
      "network": t("voice.network"),
    };
    setStatus(errors[event.error] || t("status.voiceError", { error: event.error }), true);
  };

  recognition.onend = () => {
    listening = false;
    voiceBtn.classList.remove("listening");
    voiceBtn.textContent = t("report.speak");
  };
}

function toggleVoice() {
  if (!SpeechRecognition) {
    setStatus(t("status.voiceNotSupported"), true);
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
    setStatus(t("status.voiceStartError", { error: err.message }), true);
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
  currentClaim = claim || null;
  if (!claim) {
    el.innerHTML = `<div class="muted">${escapeHtml(t("claim.none"))}</div>`;
    pdfArea.innerHTML = "";
    renderReview(null);
    renderTimeline(null);
    return;
  }
  claimId = claim.id;
  renderReview(claim);
  renderTimeline(claim);
  const fields = [
    [t("field.claimId"), claim.id],
    [t("field.status"), displayStatus(claim.status)],
    [t("field.phone"), claim.farmer_phone],
    [t("field.crop"), claim.crop || "-"],
    [t("field.damage"), claim.damage_type || "-"],
    [t("field.village"), claim.village || "-"],
    [t("field.incidentDate"), claim.incident_date || "-"],
    [t("field.missing"), (claim.missing_fields || []).join(", ") || t("value.none")],
    [t("field.photos"), String(claim.photo_count ?? 0)],
    [t("field.confidence"), String(claim.confidence ?? 0)],
  ];
  el.innerHTML = fields.map(([k, v]) => `<div class="field"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div></div>`).join("");

  if (claim.status === "READY" || claim.status === "PDF_GENERATED") {
    const pdfBtn = claim.status === "PDF_GENERATED"
      ? `<a class="btn primary" href="/api/claims/${escapeHtml(claim.id)}/pdf" target="_blank">${escapeHtml(t("claim.downloadPdf"))}</a>`
      : `<button class="btn primary" id="genPdfBtn">${escapeHtml(t("claim.generatePdf"))}</button>`;
    pdfArea.innerHTML = pdfBtn;
    const gen = $("genPdfBtn");
    if (gen) gen.onclick = generatePdf;
  } else {
    pdfArea.innerHTML = `<span class="muted">${escapeHtml(t("claim.pdfHint"))}</span>`;
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
    el.innerHTML = `<p class="muted">${escapeHtml(t("claim.timelineNone"))}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="timeline-card">
      <h3>${escapeHtml(t("claim.timelineTitle"))}</h3>
      <ol class="timeline">
        ${events.map((event) => `
          <li class="timeline-item">
            <span class="dot"></span>
            <div class="timeline-body">
              <div class="timeline-label">${escapeHtml(displayEvent(event.label))}</div>
              <div class="timeline-meta">${escapeHtml(displayStatus(event.status))} · ${escapeHtml(formatTime(event.created_at))}</div>
            </div>
          </li>`).join("")}
      </ol>
    </div>`;
}

function renderReview(claim) {
  const el = $("reviewArea");
  if (!claim) {
    el.innerHTML = `<p class="muted">${escapeHtml(t("claim.reviewNone"))}</p>`;
    return;
  }
  if (claim.status === "PDF_GENERATED") {
    el.innerHTML = `<p class="muted">${escapeHtml(t("claim.reviewLocked"))}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="review-card">
      <div class="row">
        <h3>${escapeHtml(t("claim.reviewTitle"))}</h3>
        <span class="muted">${escapeHtml(t("claim.reviewHint"))}</span>
      </div>
      <div class="review-grid">
        <label>${escapeHtml(t("review.crop"))}<input id="editCrop" type="text" maxlength="64" value="${escapeHtml(claim.crop || "")}" placeholder="${escapeHtml(t("review.ph.crop"))}"></label>
        <label>${escapeHtml(t("review.damage"))}<input id="editDamage" type="text" maxlength="64" value="${escapeHtml(claim.damage_type || "")}" placeholder="${escapeHtml(t("review.ph.damage"))}"></label>
        <label>${escapeHtml(t("review.village"))}<input id="editVillage" type="text" maxlength="128" value="${escapeHtml(claim.village || "")}" placeholder="${escapeHtml(t("review.ph.village"))}"></label>
        <label>${escapeHtml(t("review.date"))}<input id="editDate" type="text" maxlength="32" value="${escapeHtml(claim.incident_date || "")}" placeholder="${escapeHtml(t("review.ph.date"))}"></label>
      </div>
      <div class="actions">
        <button id="saveDetailsBtn" class="btn primary">${escapeHtml(t("claim.saveDetails"))}</button>
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
  setStatus(t("status.saving"));
  try {
    const data = await api(`/api/claims/${claimId}/details`, { method: "PUT", body: JSON.stringify(payload) });
    (data.replies || []).forEach(r => addMsg("bot", r));
    renderClaim(data.claim);
    await loadClaims();
    setStatus(t("status.detailsSaved"));
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
      body.innerHTML = `<tr><td colspan="8" class="muted">${escapeHtml(t("claim.noClaims"))}</td></tr>`;
      return;
    }
    body.innerHTML = data.claims.map(c => {
      const id = escapeHtml(c.id);
      return `
      <tr>
        <td><a href="#" class="link" data-id="${id}">${id}</a></td>
        <td>${escapeHtml(c.farmer_phone)}</td><td>${escapeHtml(displayStatus(c.status))}</td><td>${escapeHtml(c.crop || "-")}</td>
        <td>${escapeHtml(c.damage_type || "-")}</td><td>${escapeHtml(c.village || "-")}</td><td>${escapeHtml(c.incident_date || "-")}</td>
        <td>${c.pdf_path ? `<a class="link" href="/api/claims/${id}/pdf" target="_blank">${escapeHtml(t("table.pdfLink"))}</a>` : "-"}</td>
      </tr>`;
    }).join("");
    body.querySelectorAll("a[data-id]").forEach(a => a.addEventListener("click", async (e) => {
      e.preventDefault();
      claimId = a.dataset.id;
      await refreshClaim();
      setStatus(t("status.loaded", { id: claimId }));
    }));
  } catch (e) { setStatus(e.message, true); }
}

async function sendMessage() {
  const phone = $("phone").value.trim();
  const message = $("message").value.trim();
  if (!phone || !message) return setStatus(t("status.phoneAndMessageRequired"), true);
  $("sendBtn").disabled = true;
  setStatus(t("status.sending"));
  addMsg("user", message);
  try {
    const data = await api("/api/web/messages", { method: "POST", body: JSON.stringify({ phone, message, claim_id: claimId, language: currentLanguage() }) });
    (data.replies || []).forEach(r => addMsg("bot", r));
    renderClaim(data.claim);
    $("message").value = "";
    await loadClaims();
    setStatus(t("status.messageProcessed"));
  } catch (e) { setStatus(e.message, true); }
  finally { $("sendBtn").disabled = false; }
}

function revokePreviewUrls() {
  previewUrls.forEach((url) => URL.revokeObjectURL(url));
  previewUrls = [];
}

function loadImageInfo(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => resolve({ width: 0, height: 0 });
    img.src = url;
  });
}

async function renderPhotoPreview() {
  const files = Array.from($("photo").files || []);
  pendingPhotos = files;
  revokePreviewUrls();
  const box = $("photoPreview");
  const qualityBox = $("photoQuality");
  $("forcePhotoBtn").hidden = true;

  if (!files.length) {
    box.innerHTML = "";
    qualityBox.innerHTML = "";
    return;
  }

  const problems = [];
  if (files.length > 3) problems.push(t("status.selectAtMost3Long"));
  const cards = [];
  for (const file of files) {
    const url = URL.createObjectURL(file);
    previewUrls.push(url);
    const info = await loadImageInfo(url);
    const sizeMb = (file.size / 1024 / 1024).toFixed(2);
    if (!file.type.startsWith("image/")) problems.push(t("status.notImage", { name: file.name }));
    if (file.size > MAX_IMAGE_BYTES) problems.push(t("status.tooLarge", { name: file.name }));
    if (info.width && (info.width < MIN_IMAGE_WIDTH || info.height < MIN_IMAGE_HEIGHT)) {
      problems.push(t("status.tooSmall", { name: file.name }));
    }
    cards.push(`
      <div class="photo-thumb" data-name="${escapeHtml(file.name)}">
        <span class="thumb-badge">✓</span>
        <img src="${url}" alt="${escapeHtml(file.name)}">
        <div class="thumb-name">${escapeHtml(file.name)}</div>
        <div class="thumb-meta">${info.width || "?"}×${info.height || "?"} · ${sizeMb} MB</div>
      </div>`);
  }

  box.innerHTML = cards.join("");
  qualityBox.innerHTML = problems.length
    ? problems.map((problem) => `<div class="quality bad">${escapeHtml(problem)}</div>`).join("")
    : `<div class="quality ok">${escapeHtml(t("status.previewReady"))}</div>`;
  $("photoBtn").disabled = problems.length > 0;
}

function markPhotoUploaded(file) {
  const thumbs = Array.from($("photoPreview").querySelectorAll(".photo-thumb"));
  const thumb = thumbs.find((node) => node.dataset.name === file.name);
  if (thumb) thumb.classList.add("uploaded");
}

function clearPhotoPreview() {
  $("photo").value = "";
  pendingPhotos = [];
  revokePreviewUrls();
  $("photoPreview").innerHTML = "";
  $("photoQuality").innerHTML = "";
  $("forcePhotoBtn").hidden = true;
  $("photoBtn").disabled = false;
}

async function uploadPhoto(force = false) {
  const phone = $("phone").value.trim();
  const files = pendingPhotos.length ? pendingPhotos : Array.from($("photo").files || []);
  if (!files.length) return setStatus(t("status.selectPhoto"), true);
  if (files.length > 3) return setStatus(t("status.selectAtMost3Short"), true);
  if (!phone) return setStatus(t("status.phoneRequired"), true);

  $("photoBtn").disabled = true;
  $("forcePhotoBtn").disabled = true;
  setStatus(force ? t("status.uploadingAnyway") : t("status.uploading"));
  const uploaded = [];
  try {
    let lastClaim = null;
    for (const file of files) {
      const fd = new FormData();
      fd.append("photo", file);
      fd.append("phone", phone);
      fd.append("language", currentLanguage());
      if (claimId) fd.append("claim_id", claimId);
      if (force) fd.append("force", "true");
      const res = await fetch("/api/web/photos", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = new Error(data.error || "Upload failed");
        err.warning = Boolean(data.warning);
        throw err;
      }
      addMsg("user", t("status.photoUploadedItem", { name: file.name }));
      (data.replies || []).forEach((r) => addMsg("bot", r));
      markPhotoUploaded(file);
      uploaded.push(file);
      lastClaim = data.claim;
      if (data.quality) {
        setStatus(t("status.uploadedQuality", {
          name: file.name,
          width: data.quality.width,
          height: data.quality.height,
          sharpness: data.quality.sharpness,
        }));
      }
    }
    pendingPhotos = pendingPhotos.filter((file) => !uploaded.includes(file));
    renderClaim(lastClaim);
    await loadClaims();
    $("photo").value = "";
    $("forcePhotoBtn").hidden = true;
    setStatus(t("status.photosUploaded", { count: uploaded.length }));
  } catch (e) {
    pendingPhotos = pendingPhotos.filter((file) => !uploaded.includes(file));
    setStatus(e.message, true);
    if (e.warning) {
      $("photoQuality").innerHTML = `<div class="quality warn">${escapeHtml(e.message)} ${escapeHtml(t("status.clickUploadAnyway"))}</div>`;
      $("forcePhotoBtn").hidden = false;
    }
  } finally {
    $("photoBtn").disabled = false;
    $("forcePhotoBtn").disabled = false;
  }
}

async function generatePdf() {
  if (!claimId) return;
  setStatus(t("status.generatingPdf"));
  try {
    const data = await api(`/api/claims/${claimId}/pdf`, { method: "POST" });
    renderClaim(data.claim);
    await loadClaims();
    setStatus(t("status.pdfGenerated"));
    window.open(`/api/claims/${claimId}/pdf`, "_blank");
  } catch (e) { setStatus(e.message, true); }
}

function exportCsv() {
  // The endpoint sets Content-Disposition, so the browser downloads the file.
  window.location.href = "/api/admin/claims.csv";
}

$("sendBtn").addEventListener("click", sendMessage);
$("photoBtn").addEventListener("click", () => uploadPhoto(false));
$("forcePhotoBtn").addEventListener("click", () => uploadPhoto(true));
$("csvBtn").addEventListener("click", exportCsv);
$("photo").addEventListener("change", renderPhotoPreview);
const photoDrop = $("photoDrop");
photoDrop.addEventListener("dragover", (event) => {
  event.preventDefault();
  photoDrop.classList.add("dragover");
});
photoDrop.addEventListener("dragleave", () => photoDrop.classList.remove("dragover"));
photoDrop.addEventListener("drop", (event) => {
  event.preventDefault();
  photoDrop.classList.remove("dragover");
  if (typeof DataTransfer === "undefined") return;
  const transfer = new DataTransfer();
  Array.from(event.dataTransfer.files).forEach((file) => transfer.items.add(file));
  $("photo").files = transfer.files;
  renderPhotoPreview();
});
voiceBtn.addEventListener("click", toggleVoice);
languageSelect.addEventListener("change", () => {
  const lang = currentLanguage();
  i18nSetLang(lang);
  if (recognition) recognition.lang = lang;
  renderClaim(currentClaim);
  loadClaims();
  if (pendingPhotos.length) renderPhotoPreview();
  setStatus(t("status.languageSet", { name: languageSelect.options[languageSelect.selectedIndex].text }));
});
$("refreshBtn").addEventListener("click", async () => { await refreshClaim(); await loadClaims(); });
$("resetBtn").addEventListener("click", () => { claimId = null; chat.innerHTML = ""; clearPhotoPreview(); renderClaim(null); setStatus(t("status.newDemo")); });
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });

renderClaim(null);
loadClaims();
