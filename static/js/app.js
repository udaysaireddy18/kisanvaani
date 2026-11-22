let claimId = null;

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const statusEl = $("status");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg || "";
  statusEl.className = "status" + (isError ? " error" : "");
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
    return;
  }
  claimId = claim.id;
  const fields = [
    ["Claim ID", claim.id], ["Status", claim.status], ["Phone", claim.farmer_phone],
    ["Crop", claim.crop || "-"], ["Damage", claim.damage_type || "-"], ["Village", claim.village || "-"],
    ["Incident Date", claim.incident_date || "-"], ["Missing", (claim.missing_fields || []).join(", ") || "None"],
    ["Photos", String(claim.photo_count ?? 0)], ["Confidence", String(claim.confidence ?? 0)],
  ];
  el.innerHTML = fields.map(([k, v]) => `<div class="field"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");

  if (claim.status === "READY" || claim.status === "PDF_GENERATED") {
    const pdfBtn = claim.status === "PDF_GENERATED"
      ? `<a class="btn primary" href="/api/claims/${claim.id}/pdf" target="_blank">Download PDF</a>`
      : `<button class="btn primary" id="genPdfBtn">Generate PDF</button>`;
    pdfArea.innerHTML = pdfBtn;
    const gen = $("genPdfBtn");
    if (gen) gen.onclick = generatePdf;
  } else {
    pdfArea.innerHTML = '<span class="muted">PDF available when claim is READY (all fields + at least 1 photo).</span>';
  }
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
    body.innerHTML = data.claims.map(c => `
      <tr>
        <td><a href="#" class="link" data-id="${c.id}">${c.id}</a></td>
        <td>${c.farmer_phone}</td><td>${c.status}</td><td>${c.crop || "-"}</td>
        <td>${c.damage_type || "-"}</td><td>${c.village || "-"}</td><td>${c.incident_date || "-"}</td>
        <td>${c.pdf_path ? `<a class="link" href="/api/claims/${c.id}/pdf" target="_blank">PDF</a>` : "-"}</td>
      </tr>`).join("");
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
    const data = await api("/api/web/messages", { method: "POST", body: JSON.stringify({ phone, message, claim_id: claimId }) });
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
$("refreshBtn").addEventListener("click", async () => { await refreshClaim(); await loadClaims(); });
$("resetBtn").addEventListener("click", () => { claimId = null; chat.innerHTML = ""; renderClaim(null); setStatus("Started new demo claim session."); });
$("message").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });

renderClaim(null);
loadClaims();
