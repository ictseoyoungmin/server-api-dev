const el = (id) => document.getElementById(id);

const state = {
  exemplars: [],
  daycares: [],
};

function nowIso() {
  return new Date().toISOString();
}

function log(msg, obj) {
  const line = `[${nowIso()}] ${msg}`;
  const text = obj ? `${line}\n${JSON.stringify(obj, null, 2)}\n` : `${line}\n`;
  const box = el("logBox");
  box.textContent = text + box.textContent;
}

function value(id) {
  const target = el(id);
  if (!target) return "";
  return target.value || "";
}

function apiBase() {
  return value("apiBase").trim().replace(/\/$/, "");
}

async function api(path, init = {}) {
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(typeof body === "string" ? body : JSON.stringify(body));
  }
  return body;
}

async function apiForm(path, formData) {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    body: formData,
  });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error(typeof body === "string" ? body : JSON.stringify(body));
  }
  return body;
}

function boolParam(v) {
  if (v === "") return null;
  return v === "true";
}

function resolveDaycareId() {
  return (
    value("qDaycare") ||
    value("uDaycare") ||
    value("fDaycare") ||
    value("dDaycare") ||
    value("imgDaycare") ||
    ""
  ).trim();
}

function resolveUpdatedBy() {
  return (value("uBy") || value("fBy") || "admin").trim();
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

function applyDaycare(daycareId) {
  ["qDaycare", "uDaycare", "fDaycare", "dDaycare", "imgDaycare"].forEach((id) => {
    const target = el(id);
    if (target) target.value = daycareId;
  });
  log("Applied daycare_id", { daycare_id: daycareId });
}

function renderDaycares() {
  const ul = el("daycareList");
  ul.innerHTML = "";
  state.daycares.forEach((dc) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <div class="daycare-row">
        <div class="daycare-id"><code>${dc.daycare_id}</code></div>
        <div class="small">images=${dc.image_count} (daily=${dc.daily_image_count}, seed=${dc.seed_image_count}) · pets=${dc.pet_count} · instances=${dc.instance_count}</div>
      </div>
      <div class="actions">
        <button data-act="select" data-id="${dc.daycare_id}">선택</button>
        <button data-act="delete" data-id="${dc.daycare_id}" class="danger">삭제</button>
      </div>
    `;
    ul.appendChild(li);
  });

  ul.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const daycareId = btn.dataset.id;
      const act = btn.dataset.act;
      if (act === "select") {
        applyDaycare(daycareId);
        return;
      }
      try {
        await deleteDaycare(daycareId);
      } catch (e) {
        alert(`daycare 삭제 실패: ${e.message}`);
        log("Delete daycare failed", { daycare_id: daycareId, error: e.message });
      }
    });
  });
}

async function loadDaycares() {
  const params = {
    limit: Number(el("dcLimit").value || 100),
    offset: 0,
  };
  let data;
  try {
    data = await api(`/daycares${toQuery(params)}`);
  } catch (e) {
    const msg = String(e?.message || e);
    if (msg.includes("404")) {
      throw new Error("`GET /v1/daycares` API가 없습니다. API 서버를 최신 코드로 재시작하세요.");
    }
    throw e;
  }
  state.daycares = data.items || [];
  el("dcMeta").textContent = `count=${data.count} (DB 기준)`;
  renderDaycares();
  log("Loaded daycares", { count: data.count });
}

async function loadQdrantStatus() {
  const data = await api("/health/qdrant");
  const box = el("qdrantStatusBox");
  if (box) {
    const q = data?.qdrant || {};
    const view = {
      status: data?.status,
      collection: q.collection,
      points_count: q.points_count,
      sampled_points: q.sampled_points,
      sampled_with_vector: q.sampled_with_vector,
      sampled_has_vector: q.sampled_has_vector,
      sampled_vector_dim: q.sampled_vector_dim,
      collection_status: q.status,
    };
    box.textContent = JSON.stringify(view, null, 2);
  }
  log("Loaded qdrant status", { status: data.status });
}

async function deleteDaycare(daycareId) {
  const ok = confirm(
    `daycare '${daycareId}'의 DB(Qdrant) + storage 데이터를 삭제합니다.\n테스트 초기화 용도이며 되돌릴 수 없습니다. 진행할까요?`
  );
  if (!ok) return;

  const data = await api(
    `/daycares/${encodeURIComponent(daycareId)}${toQuery({
      delete_qdrant: true,
      delete_storage: true,
    })}`,
    { method: "DELETE" }
  );
  log("Deleted daycare", data);

  if (resolveDaycareId() === daycareId) {
    ["qDaycare", "uDaycare", "fDaycare", "dDaycare", "imgDaycare"].forEach((id) => {
      const target = el(id);
      if (target) target.value = "";
    });
  }

  const list = el("imageList");
  if (list) list.innerHTML = "";
  const meta = el("imageMetaBox");
  if (meta) meta.innerHTML = "";
  const searchMeta = el("searchMeta");
  if (searchMeta) searchMeta.textContent = "";
  const exemplarBody = el("exemplarTbody");
  if (exemplarBody) exemplarBody.innerHTML = "";
  state.exemplars = [];

  await loadDaycares();
  await loadQdrantStatus();
}

function renderExemplars() {
  const tbody = el("exemplarTbody");
  tbody.innerHTML = "";
  state.exemplars.forEach((x) => {
    const thumbUrl = x.image_id ? `${apiBase()}/images/${encodeURIComponent(x.image_id)}?variant=thumb` : "";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${thumbUrl ? `<img class="ex-thumb" src="${thumbUrl}" alt="${x.image_id || x.instance_id}" loading="lazy" />` : ""}</td>
      <td><code>${x.instance_id}</code></td>
      <td><code>${x.pet_id}</code></td>
      <td>${x.active}</td>
      <td>${x.rank ?? ""}</td>
      <td>${x.note ?? ""}</td>
      <td><code>${x.image_id ?? ""}</code></td>
      <td>${x.updated_at ?? ""}</td>
      <td>
        <button data-act="edit" data-id="${x.instance_id}">수정</button>
        <button data-act="toggle" data-id="${x.instance_id}" class="warn">${x.active ? "비활성" : "활성"}</button>
        <button data-act="delete" data-id="${x.instance_id}" class="danger">삭제</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      const act = btn.dataset.act;
      try {
        if (act === "delete") {
          await onDelete(id);
        } else if (act === "toggle") {
          await onToggle(id);
        } else {
          await onEdit(id);
        }
        await loadExemplars();
      } catch (e) {
        alert(`실패: ${e.message}`);
        log("Action failed", { id, act, error: e.message });
      }
    });
  });
}

async function loadExemplars() {
  const daycare = resolveDaycareId();
  if (!daycare) {
    throw new Error("daycare_id를 입력하세요. (검색/등록/빠른등록 중 하나)");
  }
  const params = {
    daycare_id: daycare,
    pet_id: el("qPet").value,
    species: el("qSpecies").value,
    active: boolParam(el("qActive").value),
    q: el("qText").value,
    limit: Number(el("qLimit").value || 200),
    offset: 0,
  };

  const data = await api(`/exemplars${toQuery(params)}`);
  state.exemplars = data.items || [];
  el("searchMeta").textContent = `count=${data.count}`;
  renderExemplars();
  log("Loaded exemplars", { count: data.count });
}

function getDaycareForAction() {
  return value("qDaycare") || value("uDaycare") || value("fDaycare") || value("dDaycare") || value("imgDaycare");
}

async function dailyUploadImages() {
  const fileInput = el("dFiles");
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    throw new Error("Daily 업로드할 이미지 파일들을 선택하세요.");
  }

  const daycare = (value("dDaycare") || resolveDaycareId()).trim();
  if (!daycare) {
    throw new Error("daycare_id를 입력하세요.");
  }
  const trainerId = value("dTrainer").trim() || "test_uploader";
  const capturedAt = value("dCapturedAt").trim();

  let success = 0;
  let failed = 0;
  const errors = [];

  for (const file of Array.from(fileInput.files)) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("daycare_id", daycare);
    fd.append("trainer_id", trainerId);
    fd.append("image_role", "DAILY");
    if (capturedAt) fd.append("captured_at", capturedAt);
    try {
      await apiForm("/ingest", fd);
      success += 1;
    } catch (e) {
      failed += 1;
      errors.push({ file: file.name, error: e.message });
    }
  }

  applyDaycare(daycare);
  log("Daily upload done", {
    daycare_id: daycare,
    trainer_id: trainerId,
    total_files: fileInput.files.length,
    succeeded: success,
    failed,
    errors,
  });

  await loadDaycares();
  await loadQdrantStatus();
}

async function onDelete(instanceId) {
  const daycareId = getDaycareForAction();
  const updatedBy = resolveUpdatedBy() || null;
  if (!daycareId) throw new Error("daycare_id가 필요합니다.");
  await api(`/exemplars/${encodeURIComponent(instanceId)}${toQuery({ daycare_id: daycareId, updated_by: updatedBy })}`, {
    method: "DELETE",
  });
}

async function onToggle(instanceId) {
  const target = state.exemplars.find((x) => x.instance_id === instanceId);
  if (!target) throw new Error("해당 exemplar를 찾지 못했습니다.");
  const body = {
    daycare_id: getDaycareForAction(),
    updated_by: resolveUpdatedBy() || null,
    active: !target.active,
    sync_label: false,
  };
  await api(`/exemplars/${encodeURIComponent(instanceId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

async function onEdit(instanceId) {
  const target = state.exemplars.find((x) => x.instance_id === instanceId);
  if (!target) throw new Error("해당 exemplar를 찾지 못했습니다.");

  const petId = prompt("pet_id", target.pet_id || "") ?? target.pet_id;
  const note = prompt("note", target.note || "") ?? target.note;
  const rankRaw = prompt("rank(숫자, 비우면 유지)", target.rank ?? "");
  const active = confirm("활성 상태로 저장할까요? (취소=비활성)");

  const body = {
    daycare_id: getDaycareForAction(),
    updated_by: resolveUpdatedBy() || null,
    pet_id: petId,
    note: note,
    active,
    sync_label: true,
  };
  if (rankRaw !== null && String(rankRaw).trim() !== "") {
    body.rank = Number(rankRaw);
  }

  await api(`/exemplars/${encodeURIComponent(instanceId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

async function loadImages() {
  const daycare = (el("imgDaycare").value || resolveDaycareId() || el("fDaycare").value || "").trim();
  if (!daycare) {
    throw new Error("daycare_id를 입력하세요. (이미지 조회/검색/등록 중 하나)");
  }
  const imageType = (el("imgRole").value || "DAILY").toUpperCase();
  const includeSeed = imageType !== "DAILY";
  const params = {
    daycare_id: daycare,
    date: el("imgDate").value || null,
    include_seed: includeSeed,
    limit: Number(el("imgLimit").value || 50),
    offset: 0,
  };
  const data = await api(`/images${toQuery(params)}`);
  let imagePetMap = {};
  try {
    const ex = await api(
      `/exemplars${toQuery({
        daycare_id: params.daycare_id,
        active: true,
        limit: 2000,
        offset: 0,
      })}`
    );
    imagePetMap = (ex.items || []).reduce((acc, item) => {
      const imageId = item.image_id;
      if (!imageId) return acc;
      if (!acc[imageId]) acc[imageId] = new Set();
      acc[imageId].add(item.pet_id);
      return acc;
    }, {});
  } catch (e) {
    log("Exemplar map load skipped", { error: e.message });
  }
  const ul = el("imageList");
  ul.innerHTML = "";

  const items = (data.items || []).filter((img) => {
    const role = String(img.image_role || "DAILY").toUpperCase();
    if (imageType === "ALL") return true;
    return role === imageType;
  });

  items.forEach((img) => {
    const role = String(img.image_role || "DAILY").toUpperCase();
    const fromImage = Array.isArray(img.pet_ids) ? img.pet_ids.filter(Boolean) : [];
    const fromExemplar = imagePetMap[img.image_id] ? Array.from(imagePetMap[img.image_id]) : [];
    const petNames = fromImage.length > 0 ? fromImage.join(", ") : fromExemplar.length > 0 ? fromExemplar.join(", ") : "미지정";
    const li = document.createElement("li");
    li.innerHTML = `
      <div class="image-list-item">
        <img class="thumb" src="${img.thumb_url || ""}" alt="${img.image_id}" loading="lazy" />
        <div>
          <div><span class="role-badge ${role === "SEED" ? "seed" : "daily"}">${role}</span> <strong>${petNames}</strong></div>
          <div class="small"><code>${img.image_id}</code> · instances=${img.instance_count}</div>
        </div>
      </div>
      <button data-id="${img.image_id}">열기</button>
    `;
    ul.appendChild(li);
  });

  ul.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => showImageMeta(btn.dataset.id));
  });

  log("Loaded images", {
    role: imageType,
    api_count: Number(data.count || 0),
    filtered_count: items.length,
  });
}

async function showImageMeta(imageId) {
  const data = await api(`/images/${encodeURIComponent(imageId)}/meta`);
  const box = el("imageMetaBox");
  box.innerHTML = `
    <h3><code>${imageId}</code></h3>
    <div class="meta-preview">
      <img class="meta-thumb" src="${data.image?.thumb_url || ""}" alt="${imageId}" loading="lazy" />
      <div class="small">
        <a href="${data.image?.raw_url || "#"}" target="_blank" rel="noopener noreferrer">raw</a>
        |
        <a href="${data.image?.thumb_url || "#"}" target="_blank" rel="noopener noreferrer">thumb</a>
      </div>
    </div>
  `;

  (data.instances || []).forEach((inst) => {
    const div = document.createElement("div");
    div.className = "instance-row";
    div.innerHTML = `
      <div>
        <div><code>${inst.instance_id}</code></div>
        <div>species=${inst.species} conf=${inst.confidence?.toFixed?.(3) ?? inst.confidence}</div>
      </div>
      <button data-ins="${inst.instance_id}">검색어에 복사</button>
    `;
    box.appendChild(div);
  });

  box.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const existing = value("qText");
      const target = el("qText");
      if (target) target.value = existing ? `${existing} ${btn.dataset.ins}` : btn.dataset.ins;
      log("Copied instance_id to search field", { instance_id: btn.dataset.ins });
    });
  });
}

async function quickUploadExemplar() {
  const fileInput = el("uFile");
  if (!fileInput.files || fileInput.files.length === 0) {
    throw new Error("이미지 파일을 선택하세요.");
  }
  const daycare = resolveDaycareId();
  if (!daycare) {
    throw new Error("daycare_id를 입력하세요. (빠른 등록/등록/검색 중 하나의 daycare_id)");
  }

  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("daycare_id", daycare);
  fd.append("pet_name", el("uPetName").value);
  fd.append("updated_by", el("uBy").value || "");
  fd.append("trainer_id", el("uTrainer").value || "");
  fd.append("captured_at", el("uCapturedAt").value || "");
  fd.append("sync_label", String(el("uSyncLabel").checked));
  fd.append("apply_to_all_instances", String(el("uAllInstances").checked));
  const data = await apiForm("/exemplars/upload", fd);
  // Keep query/create forms in sync so subsequent list refresh won't miss daycare_id.
  applyDaycare(daycare);
  log("Quick upload done", data);
  await loadDaycares();
}

async function folderUploadExemplars() {
  const folderInput = el("fFolder");
  if (!folderInput.files || folderInput.files.length === 0) {
    throw new Error("폴더(파일들)를 선택하세요.");
  }
  const daycare = (el("fDaycare").value || resolveDaycareId()).trim();
  if (!daycare) {
    throw new Error("daycare_id를 입력하세요.");
  }

  const fd = new FormData();
  fd.append("daycare_id", daycare);
  fd.append("updated_by", el("fBy").value || "");
  fd.append("trainer_id", el("fTrainer").value || "");
  fd.append("captured_at", el("fCapturedAt").value || "");
  fd.append("sync_label", String(el("fSyncLabel").checked));
  fd.append("apply_to_all_instances", String(el("fAllInstances").checked));
  fd.append("skip_on_error", String(el("fSkipOnError").checked));

  Array.from(folderInput.files).forEach((file) => {
    fd.append("files", file);
    fd.append("relative_paths", file.webkitRelativePath || file.name);
  });

  const data = await apiForm("/exemplars/upload-folder", fd);
  applyDaycare(daycare);
  log("Folder upload done", data);
  await loadDaycares();
}

function bindEvents() {
  const bindClick = (id, fn) => {
    const target = el(id);
    if (!target) {
      log("UI binding skipped: missing element", { id });
      return;
    }
    target.addEventListener("click", fn);
  };

  bindClick("btnLoadDaycares", async () => {
    try {
      await loadDaycares();
    } catch (e) {
      alert(`daycare 목록 조회 실패: ${e.message}`);
      log("Load daycares failed", { error: e.message });
    }
  });

  bindClick("btnQdrantStatus", async () => {
    try {
      await loadQdrantStatus();
    } catch (e) {
      alert(`Qdrant 상태 조회 실패: ${e.message}`);
      log("Load qdrant status failed", { error: e.message });
    }
  });

  bindClick("btnSearch", async () => {
    try {
      await loadExemplars();
    } catch (e) {
      alert(`조회 실패: ${e.message}`);
      log("Search failed", { error: e.message });
    }
  });

  bindClick("btnRefresh", loadExemplars);

  bindClick("btnLoadImages", async () => {
    try {
      await loadImages();
    } catch (e) {
      alert(`이미지 조회 실패: ${e.message}`);
      log("Load images failed", { error: e.message });
    }
  });

  bindClick("btnQuickUpload", async () => {
    try {
      await quickUploadExemplar();
      await loadExemplars();
    } catch (e) {
      alert(`빠른 등록 실패: ${e.message}`);
      log("Quick upload failed", { error: e.message });
    }
  });

  bindClick("btnFolderUpload", async () => {
    try {
      await folderUploadExemplars();
      await loadExemplars();
    } catch (e) {
      alert(`폴더 일괄 등록 실패: ${e.message}`);
      log("Folder upload failed", { error: e.message });
    }
  });

  bindClick("btnDailyUpload", async () => {
    try {
      await dailyUploadImages();
      await loadImages();
    } catch (e) {
      alert(`Daily 업로드 실패: ${e.message}`);
      log("Daily upload failed", { error: e.message });
    }
  });
}

function bootstrapDefaults() {
  const origin = window.location.origin;
  const root = `${origin}/v1`;
  const apiBaseInput = el("apiBase");
  if (apiBaseInput) apiBaseInput.value = root;
}

function init() {
  bootstrapDefaults();
  bindEvents();
  log("Admin dashboard ready");
  loadDaycares().catch((e) => {
    log("Initial daycare load skipped", { error: e.message });
  });
  loadQdrantStatus().catch((e) => {
    log("Initial qdrant status load skipped", { error: e.message });
  });
}

init();
