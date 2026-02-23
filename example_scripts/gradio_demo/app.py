#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import gradio as gr
import requests

DEFAULT_API_BASE = os.getenv("API_BASE", "http://localhost:8001")
DEFAULT_DAYCARE_ID = os.getenv("DAYCARE_ID", "dc_001")


def _api_base(v: str) -> str:
    return (v or DEFAULT_API_BASE).rstrip("/")


def _abs_url(api_base: str, u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if not u.startswith("/"):
        u = f"/{u}"
    return f"{api_base}{u}"


def _request_json(method: str, api_base: str, path: str, **kwargs) -> Dict[str, Any]:
    url = f"{_api_base(api_base)}{path}"
    resp = requests.request(method=method, url=url, timeout=30, **kwargs)
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if resp.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise RuntimeError(f"{resp.status_code} {path} | {detail}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected response type: {type(payload)}")
    return payload


def _fetch_images(
    api_base: str,
    daycare_id: str,
    day: str,
    tab: str,
    pet_id: str,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "daycare_id": daycare_id,
        "limit": int(limit),
        "offset": int(offset),
    }
    if day:
        params["date"] = day
    if tab:
        params["tab"] = tab
    if tab == "PET" and pet_id:
        params["pet_id"] = pet_id
    return _request_json("GET", api_base, "/v1/images", params=params)


def _fetch_pets(api_base: str, daycare_id: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {"daycare_id": daycare_id}
    return _request_json("GET", api_base, "/v1/pets", params=params)


def _image_table_rows(items: Sequence[Dict[str, Any]]) -> List[List[Any]]:
    rows: List[List[Any]] = []
    for i in items:
        rows.append(
            [
                i.get("image_id"),
                i.get("captured_at") or i.get("uploaded_at"),
                i.get("instance_count"),
                i.get("thumb_url") or i.get("raw_url"),
            ]
        )
    return rows


def _gallery_items(api_base: str, items: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for i in items:
        image_id = str(i.get("image_id") or "")
        thumb = _abs_url(api_base, i.get("thumb_url") or i.get("raw_url"))
        if not image_id or not thumb:
            continue
        caption = f"{image_id} | inst={i.get('instance_count', 0)}"
        out.append((thumb, caption))
    return out


def _choices(items: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for i in items:
        image_id = str(i.get("image_id") or "")
        if not image_id:
            continue
        ts = i.get("captured_at") or i.get("uploaded_at") or ""
        out.append((f"{image_id} | {ts}", image_id))
    return out


def _pet_choices(items: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for i in items:
        pet_id = str(i.get("pet_id") or "")
        if not pet_id:
            continue
        pet_name = str(i.get("pet_name") or "").strip() or pet_id
        image_count = i.get("image_count", 0)
        instance_count = i.get("instance_count", 0)
        out.append((f"{pet_name} ({pet_id}) | img={image_count}, inst={instance_count}", pet_id))
    return out


def _fetch_meta(api_base: str, image_id: str) -> Dict[str, Any]:
    return _request_json("GET", api_base, f"/v1/images/{image_id}/meta")


def _collect_instance_ids(api_base: str, image_ids: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for image_id in image_ids:
        meta = _fetch_meta(api_base, image_id)
        for inst in meta.get("instances") or []:
            iid = inst.get("instance_id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(iid)
    return out


def on_load_gallery(api_base: str, daycare_id: str, day: str, tab: str, pet_id: str, limit: int, offset: int):
    try:
        if tab == "PET" and not pet_id:
            raise RuntimeError("tab=PET이면 pet_id가 필요합니다.")
        data = _fetch_images(api_base, daycare_id, day, tab, pet_id, limit, offset)
        items = data.get("items") or []
        status = f"로드 완료: {len(items)}장 | tab={tab} | day={day}"
        return (
            status,
            _gallery_items(api_base, items),
            gr.update(choices=_choices(items), value=[]),
            _image_table_rows(items),
            data,
            {str(i.get("image_id")): i for i in items if i.get("image_id")},
        )
    except Exception as e:
        return f"오류: {e}", [], gr.update(choices=[], value=[]), [], {"error": str(e)}, {}


def on_load_pets(api_base: str, daycare_id: str):
    try:
        data = _fetch_pets(api_base, daycare_id)
        items = data.get("items") or []
        rows: List[List[Any]] = []
        for i in items:
            rows.append(
                [
                    i.get("pet_id"),
                    i.get("pet_name"),
                    i.get("image_count"),
                    i.get("instance_count"),
                ]
            )
        status = f"펫 목록 로드 완료: {len(items)}"
        return status, gr.update(choices=_pet_choices(items)), rows, data
    except Exception as e:
        return f"오류: {e}", gr.update(choices=[]), [], {"error": str(e)}


def on_auto_classify(
    api_base: str,
    daycare_id: str,
    day: str,
    auto_accept_threshold: float,
    candidate_threshold: float,
    search_limit: int,
    dry_run: bool,
):
    try:
        body = {
            "daycare_id": daycare_id,
            "date": day,
            "auto_accept_threshold": float(auto_accept_threshold),
            "candidate_threshold": float(candidate_threshold),
            "search_limit": int(search_limit),
            "dry_run": bool(dry_run),
        }
        data = _request_json("POST", api_base, "/v1/classify/auto", json=body)
        s = data.get("summary") or {}
        status = (
            "자동분류 완료 | "
            f"scanned={s.get('scanned_instances', 0)}, accepted={s.get('accepted', 0)}, "
            f"unreviewed_candidate={s.get('unreviewed_candidate', 0)}, "
            f"unreviewed_no_candidate={s.get('unreviewed_no_candidate', 0)}"
        )
        return status, data
    except Exception as e:
        return f"오류: {e}", {"error": str(e)}


def on_similar(
    api_base: str,
    daycare_id: str,
    day: str,
    tab: str,
    pet_id: str,
    selected_image_ids: Sequence[str],
    merge: str,
    top_k_images: int,
    per_query_limit: int,
):
    try:
        if tab == "PET" and not pet_id:
            raise RuntimeError("tab=PET이면 pet_id가 필요합니다.")
        if not selected_image_ids:
            raise RuntimeError("유사 정렬을 위해 최소 1개 이미지 선택이 필요합니다.")

        instance_ids = _collect_instance_ids(api_base, selected_image_ids)
        if not instance_ids:
            raise RuntimeError("선택 이미지에서 instance_id를 찾지 못했습니다.")

        body: Dict[str, Any] = {
            "daycare_id": daycare_id,
            "date": day,
            "tab": tab,
            "query_instance_ids": instance_ids,
            "merge": merge,
            "top_k_images": int(top_k_images),
            "per_query_limit": int(per_query_limit),
        }
        if tab == "PET":
            body["pet_id"] = pet_id

        data = _request_json("POST", api_base, "/v1/classify/similar", json=body)
        results = data.get("results") or []

        items = []
        for r in results:
            items.append(
                {
                    "image_id": r.get("image_id"),
                    "thumb_url": r.get("thumb_url"),
                    "raw_url": r.get("raw_url"),
                    "instance_count": "-",
                    "captured_at": "-",
                    "uploaded_at": "-",
                    "score": r.get("score"),
                    "best_match_instance_id": r.get("best_match_instance_id"),
                    "best_match_score": r.get("best_match_score"),
                }
            )

        rows = []
        for r in results:
            rows.append(
                [
                    r.get("image_id"),
                    r.get("score"),
                    r.get("best_match_instance_id"),
                    r.get("best_match_score"),
                    r.get("thumb_url") or r.get("raw_url"),
                ]
            )

        status = f"유사 정렬 완료: {len(results)}장 반환 | query_instance_ids={len(instance_ids)}"
        return (
            status,
            _gallery_items(api_base, items),
            gr.update(choices=_choices(items), value=list(selected_image_ids)),
            rows,
            data,
            {str(i.get("image_id")): i for i in items if i.get("image_id")},
        )
    except Exception as e:
        return f"오류: {e}", [], gr.update(choices=[], value=[]), [], {"error": str(e)}, {}


def on_apply_labels(
    api_base: str,
    daycare_id: str,
    labeled_by: str,
    action: str,
    pet_id_for_label: str,
    selected_image_ids: Sequence[str],
):
    try:
        if not selected_image_ids:
            raise RuntimeError("라벨 액션을 적용할 이미지를 선택하세요.")
        if action == "ACCEPT" and not pet_id_for_label:
            raise RuntimeError("ACCEPT는 pet_id가 필요합니다.")

        instance_ids = _collect_instance_ids(api_base, selected_image_ids)
        if not instance_ids:
            raise RuntimeError("선택 이미지에서 instance_id를 찾지 못했습니다.")

        assignments = []
        for iid in instance_ids:
            item: Dict[str, Any] = {
                "instance_id": iid,
                "action": action,
                "source": "MANUAL",
                "confidence": 1.0,
            }
            if action == "ACCEPT":
                item["pet_id"] = pet_id_for_label
            assignments.append(item)

        body = {
            "daycare_id": daycare_id,
            "labeled_by": labeled_by or None,
            "assignments": assignments,
        }
        data = _request_json("POST", api_base, "/v1/labels", json=body)
        status = f"라벨 적용 완료: action={action}, instances={len(assignments)}"
        return status, data
    except Exception as e:
        return f"오류: {e}", {"error": str(e)}


def on_finalize(api_base: str, daycare_id: str, day: str, pet_ids_csv: str):
    try:
        pet_ids = [p.strip() for p in (pet_ids_csv or "").split(",") if p.strip()]
        body: Dict[str, Any] = {"daycare_id": daycare_id, "date": day}
        if pet_ids:
            body["pet_ids"] = pet_ids
        data = _request_json("POST", api_base, "/v1/buckets/finalize", json=body)
        qm = data.get("quality_metrics") or {}
        status = (
            f"버킷 확정 완료: buckets={data.get('bucket_count', 0)}, total_images={data.get('total_images', 0)} "
            f"| unclassified_ratio={qm.get('unclassified_image_ratio', 0):.3f} "
            f"| auto_accept_ratio={qm.get('auto_accept_ratio', 0):.3f}"
        )
        manifest = data.get("manifest_path") or ""
        return status, data, manifest
    except Exception as e:
        return f"오류: {e}", {"error": str(e)}, ""


def on_get_buckets(api_base: str, daycare_id: str, day: str, manifest: str):
    try:
        path = f"/v1/buckets/{daycare_id}/{day}"
        params = {"manifest": manifest} if manifest else None
        data = _request_json("GET", api_base, path, params=params)
        qm = data.get("quality_metrics") or {}
        status = (
            f"버킷 조회 완료: buckets={data.get('bucket_count', 0)}, total_images={data.get('total_images', 0)} "
            f"| unclassified_ratio={qm.get('unclassified_image_ratio', 0):.3f}"
        )
        return status, data
    except Exception as e:
        return f"오류: {e}", {"error": str(e)}


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Dogface Semi-Auto Gradio Demo") as demo:
        gr.Markdown("# Dogface Semi-Auto Classification Demo")
        gr.Markdown("백엔드 API 기능/흐름(UI/UX 최소단위) 검증용 Gradio 데모")

        with gr.Row():
            api_base = gr.Textbox(label="API_BASE", value=DEFAULT_API_BASE, scale=2)
            daycare_id = gr.Textbox(label="daycare_id", value=DEFAULT_DAYCARE_ID)
            day = gr.Textbox(label="date (YYYY-MM-DD)", value=str(date.today()))
            load_pets_btn = gr.Button("Load Pets")

        with gr.Row():
            tab = gr.Dropdown(label="tab", choices=["ALL", "UNCLASSIFIED", "PET"], value="UNCLASSIFIED")
            pet_id = gr.Dropdown(
                label="pet_id (tab=PET일 때)",
                choices=[],
                value=None,
                allow_custom_value=True,
            )
            limit = gr.Slider(label="limit", minimum=10, maximum=1000, step=10, value=200)
            offset = gr.Slider(label="offset", minimum=0, maximum=2000, step=10, value=0)
            load_btn = gr.Button("Load Gallery", variant="primary")

        pet_table = gr.Dataframe(
            label="pets",
            headers=["pet_id", "pet_name", "image_count", "instance_count"],
            datatype=["str", "str", "number", "number"],
            wrap=True,
        )

        with gr.Row():
            auto_accept_threshold = gr.Slider(label="auto_accept_threshold", minimum=0.0, maximum=1.0, step=0.01, value=0.78)
            candidate_threshold = gr.Slider(label="candidate_threshold", minimum=0.0, maximum=1.0, step=0.01, value=0.62)
            search_limit = gr.Slider(label="search_limit", minimum=10, maximum=1000, step=10, value=200)
            dry_run = gr.Checkbox(label="auto dry_run", value=True)
            auto_btn = gr.Button("Run Auto Classify")

        with gr.Row():
            merge = gr.Dropdown(label="similar merge", choices=["RRF", "MAX"], value="RRF")
            top_k_images = gr.Slider(label="top_k_images", minimum=10, maximum=500, step=10, value=100)
            per_query_limit = gr.Slider(label="per_query_limit", minimum=10, maximum=1000, step=10, value=400)
            similar_btn = gr.Button("Sort Similar In Tab")

        with gr.Row():
            action = gr.Dropdown(label="label action", choices=["ACCEPT", "REJECT", "CLEAR"], value="ACCEPT")
            pet_id_for_label = gr.Textbox(label="label pet_id (ACCEPT only)")
            labeled_by = gr.Textbox(label="labeled_by", value="trainer_demo")
            label_btn = gr.Button("Apply Label Action")

        with gr.Row():
            pet_ids_csv = gr.Textbox(label="finalize pet_ids csv (optional)", placeholder="pet_a,pet_b")
            finalize_btn = gr.Button("Finalize Buckets")
            manifest = gr.Textbox(label="manifest filename (optional, read용)")
            get_buckets_btn = gr.Button("Get Buckets")

        status = gr.Textbox(label="status", lines=2)
        gallery = gr.Gallery(label="gallery", columns=6, rows=3, object_fit="cover", height=420)
        selected_image_ids = gr.CheckboxGroup(label="선택 이미지 IDs")

        image_table = gr.Dataframe(
            label="image list / similar ranking",
            headers=["image_id", "col2", "col3", "col4", "url"],
            datatype=["str", "str", "str", "str", "str"],
            wrap=True,
        )

        api_response = gr.JSON(label="last api response")
        image_state = gr.State({})

        load_btn.click(
            fn=on_load_gallery,
            inputs=[api_base, daycare_id, day, tab, pet_id, limit, offset],
            outputs=[status, gallery, selected_image_ids, image_table, api_response, image_state],
        )

        load_pets_btn.click(
            fn=on_load_pets,
            inputs=[api_base, daycare_id],
            outputs=[status, pet_id, pet_table, api_response],
        )

        auto_btn.click(
            fn=on_auto_classify,
            inputs=[
                api_base,
                daycare_id,
                day,
                auto_accept_threshold,
                candidate_threshold,
                search_limit,
                dry_run,
            ],
            outputs=[status, api_response],
        )

        similar_btn.click(
            fn=on_similar,
            inputs=[
                api_base,
                daycare_id,
                day,
                tab,
                pet_id,
                selected_image_ids,
                merge,
                top_k_images,
                per_query_limit,
            ],
            outputs=[status, gallery, selected_image_ids, image_table, api_response, image_state],
        )

        label_btn.click(
            fn=on_apply_labels,
            inputs=[api_base, daycare_id, labeled_by, action, pet_id_for_label, selected_image_ids],
            outputs=[status, api_response],
        )

        finalize_btn.click(
            fn=on_finalize,
            inputs=[api_base, daycare_id, day, pet_ids_csv],
            outputs=[status, api_response, manifest],
        )

        get_buckets_btn.click(
            fn=on_get_buckets,
            inputs=[api_base, daycare_id, day, manifest],
            outputs=[status, api_response],
        )

    return demo


if __name__ == "__main__":
    app = build_demo()
    app.launch(server_name="0.0.0.0", server_port=int(os.getenv("GRADIO_PORT", "7860")))
