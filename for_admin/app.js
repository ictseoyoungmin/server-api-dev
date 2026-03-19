const el = (id) => document.getElementById(id);

const state = {
  daycares: [],
  pets: [],
  activePetId: null,
  galleryView: "ALL",
  galleryItems: [],
  originalGalleryItems: [],
  selectedImageIds: new Set(),
  imageMetaCache: new Map(),
  inspectedImageId: null,
  searchScores: {},
  activeExemplars: [],
};

function nowIso() {
  return new Date().toISOString();
}

function log(msg, obj) {
  const box = el("logBox");
  if (!box) return;
  const line = `[${nowIso()}] ${msg}`;
  const text = obj ? `${line}\n${JSON.stringify(obj, null, 2)}\n` : `${line}\n`;
  box.textContent = text + box.textContent;
}

function value(id) {
  const target = el(id);
  return target ? target.value || "" : "";
}

function currentDaycare() {
  return value("workspaceDaycare").trim();
}

function currentDate() {
  return value("workspaceDate").trim();
}

function apiBase() {
  return value("apiBase").trim().replace(/\/$/, "");
}

async function api(path, init = {}) {
  const headers = { ...(init.headers || {}) };
  if (!(init.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${apiBase()}${path}`, { ...init, headers });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(typeof body === "string" ? body : JSON.stringify(body));
  }
  return body;
}

function toQuery(params) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === "") return;
    q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

function setWorkspaceDaycare(daycareId) {
  el("workspaceDaycare").value = daycareId;
  log("Applied daycare", { daycare_id: daycareId });
}

function selectedImageIds() {
  return Array.from(state.selectedImageIds);
}

function selectedCountText() {
  return `선택된 이미지 ${state.selectedImageIds.size}장`;
}

function currentTabForApi() {
  if (state.galleryView === "PET") return "PET";
  if (state.galleryView === "UNCLASSIFIED") return "UNCLASSIFIED";
  return "ALL";
}

function setButtonBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle("is-busy", busy);
  button.setAttribute("aria-busy", busy ? "true" : "false");
}

async function withButtonBusy(button, task) {
  setButtonBusy(button, true);
  try {
    return await task();
  } finally {
    setButtonBusy(button, false);
  }
}

function renderDaycares() {
  const list = el("daycareList");
  list.innerHTML = "";
  if (!state.daycares.length) {
    list.innerHTML = '<li><span class="daycare-label">등록된 daycare가 없습니다.</span></li>';
    return;
  }
  state.daycares.forEach((item) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="daycare-label"><code>${item.daycare_id}</code></span>
      <span class="inline-actions">
        <button data-act="select" data-id="${item.daycare_id}">적용</button>
        <button data-act="delete" data-id="${item.daycare_id}" class="danger">삭제</button>
      </span>
    `;
    list.appendChild(li);
  });
  list.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const daycareId = btn.dataset.id;
      if (btn.dataset.act === "select") {
        setWorkspaceDaycare(daycareId);
        await loadWorkspace();
        return;
      }
      if (!confirm(`daycare '${daycareId}' 데이터를 삭제할까요?`)) return;
      await api(`/daycares/${encodeURIComponent(daycareId)}${toQuery({ delete_qdrant: true, delete_storage: true })}`, {
        method: "DELETE",
      });
      log("Deleted daycare", { daycare_id: daycareId });
      if (currentDaycare() === daycareId) {
        el("workspaceDaycare").value = "";
      }
      await loadDaycares();
      await loadQdrantStatus();
    });
  });
}

function renderPetButtons() {
  const box = el("petButtons");
  box.innerHTML = "";
  el("petMeta").textContent = state.activePetId ? "active pet=" + state.activePetId : "";
  if (!state.pets.length) {
    box.innerHTML = '<div class="empty-state">초기 등록 pet이 아직 없습니다.</div>';
    return;
  }
  state.pets.forEach((pet) => {
    const btn = document.createElement("button");
    btn.className = `pet-pill${state.activePetId === pet.pet_id ? " active" : ""}`;
    btn.textContent = pet.pet_name || pet.pet_id;
    btn.addEventListener("click", async () => {
      state.activePetId = pet.pet_id;
      state.galleryView = "PET";
      resetSearchRanking();
      await Promise.all([loadActiveExemplars(), loadGallery()]);
      renderPetButtons();
      syncViewButtons();
    });
    box.appendChild(btn);
  });
}

function renderActiveExemplars() {
  const strip = el("activePetStrip");
  strip.innerHTML = "";
  if (!state.activePetId) {
    strip.innerHTML = '<div class="empty-state">pet 버튼을 선택하면 해당 seed 이미지가 표시됩니다.</div>';
    return;
  }
  if (!state.activeExemplars.length) {
    strip.innerHTML = '<div class="empty-state">선택된 pet의 seed exemplar가 없습니다.</div>';
    return;
  }
  state.activeExemplars.forEach((item) => {
    const card = document.createElement("div");
    card.className = "seed-card";
    const src = item.image_id ? `${apiBase()}/images/${encodeURIComponent(item.image_id)}?variant=thumb` : "";
    card.innerHTML = `
      <img src="${src}" alt="${item.pet_id}" loading="lazy" />
      <span>${item.pet_id}</span>
      <code>${item.instance_id}</code>
    `;
    strip.appendChild(card);
  });
}

function inferCardState(item) {
  if (Array.isArray(item.pet_ids) && item.pet_ids.length > 0) return "accepted";
  return "unreviewed";
}

function renderGallery() {
  const grid = el("galleryGrid");
  const meta = el("galleryMeta");
  grid.innerHTML = "";
  meta.textContent = `${state.galleryItems.length} images · view=${state.galleryView}${state.activePetId ? ` · pet=${state.activePetId}` : ""}`;
  el("selectionMeta").textContent = selectedCountText();

  if (!state.galleryItems.length) {
    grid.innerHTML = '<div class="empty-state">표시할 daily 이미지가 없습니다.</div>';
    return;
  }

  state.galleryItems.forEach((item) => {
    const selected = state.selectedImageIds.has(item.image_id);
    const card = document.createElement("article");
    card.className = `gallery-card${selected ? " selected" : ""}`;
    const score = state.searchScores[item.image_id];
    const petLabel = Array.isArray(item.pet_ids) && item.pet_ids.length > 0 ? item.pet_ids.join(", ") : "미지정";
    const cardState = inferCardState(item);
    card.innerHTML = `
      <div class="gallery-thumb-wrap">
        <input class="card-check" type="checkbox" ${selected ? "checked" : ""} data-image-id="${item.image_id}" />
        <img class="gallery-thumb" src="${item.thumb_url}" alt="${item.image_id}" loading="lazy" data-inspect="${item.image_id}" />
      </div>
      <div class="card-lines">
        <div class="inline-actions wrap">
          <span class="role-badge">${item.image_role}</span>
          <span class="state-badge ${cardState}">${cardState.toUpperCase()}</span>
          ${score !== undefined ? `<span class="score-badge">sim ${score.toFixed(2)}</span>` : ""}
        </div>
        <div class="pet-label">${petLabel}</div>
        <div class="pet-sub"><code>${item.image_id}</code></div>
        <div class="instance-meta">instances=${item.instance_count}</div>
      </div>
    `;
    grid.appendChild(card);
  });

  grid.querySelectorAll(".card-check").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const imageId = checkbox.dataset.imageId;
      if (checkbox.checked) state.selectedImageIds.add(imageId);
      else state.selectedImageIds.delete(imageId);
      renderGallery();
    });
  });

  grid.querySelectorAll("[data-inspect]").forEach((node) => {
    node.addEventListener("click", async () => {
      await inspectImage(node.dataset.inspect);
    });
  });
}

function renderInspector(meta) {
  const pane = el("detailPane");
  const detailMeta = el("detailMeta");
  if (!meta) {
    pane.className = "detail-empty";
    pane.textContent = "이미지를 클릭하면 instance 상세가 표시됩니다.";
    detailMeta.textContent = "";
    return;
  }
  detailMeta.textContent = meta.image?.image_id || "";
  pane.className = "detail-body";
  const petLabel = Array.isArray(meta.image?.pet_ids) && meta.image.pet_ids.length > 0 ? meta.image.pet_ids.join(", ") : "미지정";
  pane.innerHTML = `
    <div class="detail-hero">
      <img src="${meta.image?.thumb_url || ""}" alt="${meta.image?.image_id || "detail"}" loading="lazy" />
      <div>
        <div class="pet-label">${petLabel}</div>
        <div class="pet-sub"><code>${meta.image?.image_id || ""}</code></div>
        <div class="pet-sub">captured_at=${meta.image?.captured_at || "n/a"}</div>
      </div>
    </div>
    <div class="instance-list"></div>
  `;
  const list = pane.querySelector(".instance-list");
  (meta.instances || []).forEach((inst) => {
    const row = document.createElement("div");
    row.className = "instance-row";
    row.innerHTML = `
      <div>
        <div><code>${inst.instance_id}</code></div>
        <div class="sub">species=${inst.species} · conf=${Number(inst.confidence || 0).toFixed(3)}</div>
        <div class="sub">pet_id=${inst.pet_id || ""}</div>
      </div>
      <button data-copy="${inst.instance_id}">instance_id 복사</button>
    `;
    list.appendChild(row);
  });
  pane.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await navigator.clipboard.writeText(btn.dataset.copy);
      log("Copied instance_id", { instance_id: btn.dataset.copy });
    });
  });
}

function syncViewButtons() {
  ["btnViewAll", "btnViewUnclassified", "btnViewPet"].forEach((id) => {
    const button = el(id);
    if (!button) return;
    button.classList.toggle("active", button.dataset.view === state.galleryView);
    button.classList.toggle("is-active", button.dataset.view === state.galleryView);
  });
}

function resetSearchRanking() {
  state.searchScores = {};
  state.galleryItems = [...state.originalGalleryItems];
}

function selectAllVisibleImages() {
  state.selectedImageIds = new Set(state.galleryItems.map((item) => item.image_id));
  renderGallery();
}

function clearSelectedImages() {
  state.selectedImageIds.clear();
  renderGallery();
}

async function loadDaycares() {
  const data = await api(`/daycares${toQuery({ limit: 200, offset: 0 })}`);
  state.daycares = data.items || [];
  renderDaycares();
  log("Loaded daycares", { count: state.daycares.length });
}

async function loadQdrantStatus() {
  const data = await api("/health/qdrant");
  const q = data.qdrant || {};
  el("qdrantStatusBox").textContent = JSON.stringify(
    {
      status: data.status,
      collection: q.collection,
      points_count: q.points_count,
      sampled_points: q.sampled_points,
      sampled_with_vector: q.sampled_with_vector,
      sampled_has_vector: q.sampled_has_vector,
      sampled_vector_dim: q.sampled_vector_dim,
      status_detail: q.status,
    },
    null,
    2
  );
}

async function loadPets() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  const data = await api(`/pets${toQuery({ daycare_id: daycare })}`);
  state.pets = data.items || [];
  if (state.activePetId && !state.pets.find((item) => item.pet_id === state.activePetId)) {
    state.activePetId = null;
  }
  renderPetButtons();
  if (!state.activePetId) {
    state.activeExemplars = [];
    renderActiveExemplars();
  }
}

async function loadActiveExemplars() {
  if (!currentDaycare() || !state.activePetId) {
    state.activeExemplars = [];
    renderActiveExemplars();
    return;
  }
  const data = await api(
    `/exemplars${toQuery({ daycare_id: currentDaycare(), pet_id: state.activePetId, active: true, limit: 30, offset: 0 })}`
  );
  state.activeExemplars = data.items || [];
  renderActiveExemplars();
}

async function loadGallery() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  if (state.galleryView === "PET" && !state.activePetId) {
    throw new Error("PET bucket view는 pet 버튼 선택 후 사용할 수 있습니다.");
  }
  const params = {
    daycare_id: daycare,
    date: currentDate() || null,
    tab: currentTabForApi(),
    pet_id: state.galleryView === "PET" ? state.activePetId : null,
    include_seed: false,
    limit: 500,
    offset: 0,
  };
  const data = await api(`/images${toQuery(params)}`);
  state.galleryItems = data.items || [];
  state.originalGalleryItems = [...state.galleryItems];
  state.selectedImageIds.clear();
  state.imageMetaCache.clear();
  state.searchScores = {};
  renderGallery();
  log("Loaded gallery", { view: state.galleryView, count: state.galleryItems.length, pet_id: state.activePetId });
}

async function inspectImage(imageId) {
  state.inspectedImageId = imageId;
  let meta = state.imageMetaCache.get(imageId);
  if (!meta) {
    meta = await api(`/images/${encodeURIComponent(imageId)}/meta`);
    state.imageMetaCache.set(imageId, meta);
  }
  renderInspector(meta);
}

async function loadWorkspace() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  el("workspaceMeta").textContent = `${daycare}${currentDate() ? ` · ${currentDate()}` : ""}`;
  await Promise.all([loadPets(), state.activePetId ? loadActiveExemplars() : Promise.resolve()]);
  await loadGallery();
}

async function autoClassify() {
  const daycare = currentDaycare();
  const date = currentDate();
  if (!daycare || !date) throw new Error("자동 분류에는 daycare_id와 date가 모두 필요합니다.");
  const autoThreshold = Number(value("autoAcceptThreshold") || 0.6);
  const body = {
    daycare_id: daycare,
    date,
    auto_accept_threshold: autoThreshold,
    candidate_threshold: autoThreshold,
    labeled_by: "admin_dashboard",
  };
  const data = await api("/classify/auto", { method: "POST", body: JSON.stringify(body) });
  el("opsMeta").textContent = `accepted=${data.summary.accepted} · candidate=${data.summary.unreviewed_candidate} · no_candidate=${data.summary.unreviewed_no_candidate}`;
  log("Auto classify done", data.summary);
  await loadGallery();
}

async function finalizeBuckets() {
  const daycare = currentDaycare();
  const date = currentDate();
  if (!daycare || !date) throw new Error("버킷 확정에는 daycare_id와 date가 필요합니다.");
  const data = await api("/buckets/finalize", {
    method: "POST",
    body: JSON.stringify({ daycare_id: daycare, date }),
  });
  el("opsMeta").textContent = `bucket_count=${data.bucket_count} · total_images=${data.total_images}`;
  log("Buckets finalized", { bucket_count: data.bucket_count, total_images: data.total_images });
}

async function resolveRepresentativeInstanceIds(imageIds) {
  const ids = [];
  for (const imageId of imageIds) {
    let meta = state.imageMetaCache.get(imageId);
    if (!meta) {
      meta = await api(`/images/${encodeURIComponent(imageId)}/meta`);
      state.imageMetaCache.set(imageId, meta);
    }
    const instances = Array.isArray(meta.instances) ? meta.instances : [];
    if (!instances.length) continue;
    let chosen = null;
    if (state.activePetId) {
      chosen = instances.find(
        (inst) => String(inst.pet_id || "") === state.activePetId && String(inst.assignment_status || "").toUpperCase() === "ACCEPTED"
      );
    }
    if (!chosen) {
      chosen = [...instances].sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))[0];
    }
    if (chosen?.instance_id) ids.push(chosen.instance_id);
  }
  return [...new Set(ids)];
}

async function runSimilarSearch() {
  const daycare = currentDaycare();
  const date = currentDate();
  const imageIds = selectedImageIds();
  if (!daycare || !date) throw new Error("유사 정렬에는 daycare_id와 date가 필요합니다.");
  if (!imageIds.length) throw new Error("유사 정렬 기준 이미지를 1장 이상 선택하세요.");
  const queryInstanceIds = await resolveRepresentativeInstanceIds(imageIds);
  if (!queryInstanceIds.length) throw new Error("선택된 이미지에서 query instance를 찾지 못했습니다.");
  const data = await api("/classify/similar", {
    method: "POST",
    body: JSON.stringify({
      daycare_id: daycare,
      date,
      tab: currentTabForApi(),
      pet_id: state.galleryView === "PET" ? state.activePetId : null,
      include_seed: false,
      query_instance_ids: queryInstanceIds,
      merge: "MAX",
      top_k_images: Number(value("similarTopK") || 80),
      per_query_limit: 400,
    }),
  });
  state.searchScores = Object.fromEntries((data.results || []).map((item) => [item.image_id, Number(item.score)]));
  const selectedOrder = new Map(imageIds.map((imageId, idx) => [imageId, idx]));
  const order = new Map((data.results || []).map((item, idx) => [item.image_id, idx]));
  state.galleryItems = [...state.originalGalleryItems].sort((a, b) => {
    const aSelected = selectedOrder.has(a.image_id);
    const bSelected = selectedOrder.has(b.image_id);
    if (aSelected && bSelected) {
      return selectedOrder.get(a.image_id) - selectedOrder.get(b.image_id);
    }
    if (aSelected) return -1;
    if (bSelected) return 1;

    const ai = order.has(a.image_id) ? order.get(a.image_id) : Number.MAX_SAFE_INTEGER;
    const bi = order.has(b.image_id) ? order.get(b.image_id) : Number.MAX_SAFE_INTEGER;
    if (ai !== bi) return ai - bi;
    return 0;
  });
  renderGallery();
  log("Similar ranking applied", data.query_debug);
}

async function labelSelectedImages(action) {
  const daycare = currentDaycare();
  const date = currentDate();
  const imageIds = selectedImageIds();
  if (!daycare || !date) throw new Error("daycare_id와 date가 필요합니다.");
  if (!imageIds.length) throw new Error("먼저 daily 이미지를 선택하세요.");
  if (action === "ACCEPT" && !state.activePetId) throw new Error("포함 작업에는 active pet 선택이 필요합니다.");
  const data = await api("/admin/images/labels", {
    method: "POST",
    body: JSON.stringify({
      daycare_id: daycare,
      date,
      image_ids: imageIds,
      action,
      pet_id: state.activePetId,
      labeled_by: "admin_dashboard",
      confidence: 1.0,
      source: "MANUAL",
      select_mode: value("selectionMode") || "BEST_CONFIDENCE",
    }),
  });
  log("Applied image label action", { action, count: data.items.length, pet_id: state.activePetId });
  await loadGallery();
}

async function quickUploadExemplar() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  const fileInput = el("uFile");
  if (!fileInput.files || !fileInput.files.length) throw new Error("seed 이미지 파일을 선택하세요.");
  const petName = value("uPetName").trim();
  if (!petName) throw new Error("pet name을 입력하세요.");
  const fd = new FormData();
  fd.append("daycare_id", daycare);
  fd.append("pet_name", petName);
  fd.append("updated_by", "admin_dashboard");
  fd.append("sync_label", "true");
  fd.append("apply_to_all_instances", "false");
  fd.append("file", fileInput.files[0]);
  const data = await api("/exemplars/upload", { method: "POST", body: fd });
  log("Quick seed upload done", data);
  await loadWorkspace();
}

async function folderUploadExemplars() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  const folderInput = el("fFolder");
  if (!folderInput.files || !folderInput.files.length) throw new Error("pet 폴더를 선택하세요.");
  const fd = new FormData();
  fd.append("daycare_id", daycare);
  fd.append("updated_by", "admin_dashboard");
  fd.append("sync_label", "true");
  fd.append("apply_to_all_instances", "false");
  fd.append("skip_on_error", "true");
  Array.from(folderInput.files).forEach((file) => {
    fd.append("files", file);
    fd.append("relative_paths", file.webkitRelativePath || file.name);
  });
  const data = await api("/exemplars/upload-folder", { method: "POST", body: fd });
  log("Seed folder upload done", { succeeded: data.succeeded, failed: data.failed });
  await loadWorkspace();
}

async function dailyUploadImages() {
  const daycare = currentDaycare();
  if (!daycare) throw new Error("daycare_id를 입력하세요.");
  const input = el("dFiles");
  if (!input.files || !input.files.length) throw new Error("daily 이미지 파일을 선택하세요.");
  let success = 0;
  let failed = 0;
  for (const file of Array.from(input.files)) {
    const fd = new FormData();
    fd.append("daycare_id", daycare);
    fd.append("trainer_id", "admin_dashboard");
    fd.append("image_role", "DAILY");
    fd.append("file", file);
    try {
      await api("/ingest", { method: "POST", body: fd });
      success += 1;
    } catch (err) {
      failed += 1;
      log("Daily upload failed for file", { file: file.name, error: err.message });
    }
  }
  log("Daily upload done", { succeeded: success, failed });
  await loadGallery();
}

function bindViewButtons() {
  ["btnViewAll", "btnViewUnclassified", "btnViewPet"].forEach((id) => {
    el(id).addEventListener("click", async () => {
      const nextView = el(id).dataset.view;
      if (nextView === "PET" && !state.activePetId) {
        alert("먼저 pet 버튼을 선택하세요.");
        return;
      }
      state.galleryView = nextView;
      resetSearchRanking();
      syncViewButtons();
      await loadGallery();
    });
  });
}

function bootstrapDefaults() {
  el("apiBase").value = `${window.location.origin}/v1`;
  const today = new Date().toISOString().slice(0, 10);
  el("workspaceDate").value = today;
}

function bindEvents() {
  el("btnLoadWorkspace").addEventListener("click", async () => {
    const button = el("btnLoadWorkspace");
    try {
      await withButtonBusy(button, () => loadWorkspace());
    } catch (err) {
      alert(err.message);
      log("Load workspace failed", { error: err.message });
    }
  });

  el("btnLoadDaycares").addEventListener("click", async () => {
    const button = el("btnLoadDaycares");
    try {
      await withButtonBusy(button, () => loadDaycares());
    } catch (err) {
      alert(err.message);
      log("Load daycares failed", { error: err.message });
    }
  });

  el("btnQdrantStatus").addEventListener("click", async () => {
    const button = el("btnQdrantStatus");
    try {
      await withButtonBusy(button, () => loadQdrantStatus());
    } catch (err) {
      alert(err.message);
      log("Qdrant status failed", { error: err.message });
    }
  });

  el("btnAutoClassify").addEventListener("click", async () => {
    const button = el("btnAutoClassify");
    try {
      await withButtonBusy(button, () => autoClassify());
    } catch (err) {
      alert(err.message);
      log("Auto classify failed", { error: err.message });
    }
  });

  el("btnFinalize").addEventListener("click", async () => {
    const button = el("btnFinalize");
    try {
      await withButtonBusy(button, () => finalizeBuckets());
    } catch (err) {
      alert(err.message);
      log("Finalize failed", { error: err.message });
    }
  });

  el("btnReloadGallery").addEventListener("click", async () => {
    const button = el("btnReloadGallery");
    try {
      await withButtonBusy(button, async () => {
        resetSearchRanking();
        await loadGallery();
      });
    } catch (err) {
      alert(err.message);
      log("Reload gallery failed", { error: err.message });
    }
  });

  el("btnSimilarSearch").addEventListener("click", async () => {
    const button = el("btnSimilarSearch");
    try {
      await withButtonBusy(button, () => runSimilarSearch());
    } catch (err) {
      alert(err.message);
      log("Similar search failed", { error: err.message });
    }
  });

  el("btnClearRanking").addEventListener("click", () => {
    resetSearchRanking();
    renderGallery();
    log("Ranking reset");
  });

  el("btnSelectAll").addEventListener("click", () => {
    selectAllVisibleImages();
    log("Selected all visible images", { count: state.galleryItems.length });
  });

  el("btnClearSelection").addEventListener("click", () => {
    clearSelectedImages();
    log("Cleared selected images");
  });

  el("btnAssignSelected").addEventListener("click", async () => {
    const button = el("btnAssignSelected");
    try {
      await withButtonBusy(button, () => labelSelectedImages("ACCEPT"));
    } catch (err) {
      alert(err.message);
      log("Assign selected failed", { error: err.message });
    }
  });

  el("btnClearSelected").addEventListener("click", async () => {
    const button = el("btnClearSelected");
    try {
      await withButtonBusy(button, () => labelSelectedImages("CLEAR"));
    } catch (err) {
      alert(err.message);
      log("Reset to unassigned failed", { error: err.message });
    }
  });

  el("btnQuickUpload").addEventListener("click", async () => {
    const button = el("btnQuickUpload");
    try {
      await withButtonBusy(button, () => quickUploadExemplar());
    } catch (err) {
      alert(err.message);
      log("Quick upload failed", { error: err.message });
    }
  });

  el("btnFolderUpload").addEventListener("click", async () => {
    const button = el("btnFolderUpload");
    try {
      await withButtonBusy(button, () => folderUploadExemplars());
    } catch (err) {
      alert(err.message);
      log("Folder upload failed", { error: err.message });
    }
  });

  el("btnDailyUpload").addEventListener("click", async () => {
    const button = el("btnDailyUpload");
    try {
      await withButtonBusy(button, () => dailyUploadImages());
    } catch (err) {
      alert(err.message);
      log("Daily upload failed", { error: err.message });
    }
  });

  bindViewButtons();
}

async function init() {
  bootstrapDefaults();
  bindEvents();
  renderInspector(null);
  renderPetButtons();
  renderActiveExemplars();
  renderGallery();
  syncViewButtons();
  log("Admin workspace ready");
  try {
    await loadDaycares();
    await loadQdrantStatus();
  } catch (err) {
    log("Initial bootstrap skipped", { error: err.message });
  }
}

init();
