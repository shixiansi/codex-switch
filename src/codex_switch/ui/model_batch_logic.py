from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import perf_counter

from codex_switch.chat import ChatTester
from codex_switch.models import Profile
from codex_switch.storage import DEFAULT_MODEL_BATCH_CONCURRENCY
from codex_switch.ui.utils import compact_text


MODEL_BATCH_PROMPT = "ping"


@dataclass
class ModelBatchResult:
    status: str = "pending"
    detail: str = ""
    duration_ms: int | None = None


@dataclass
class ModelBatchCache:
    models: list[str]
    results: dict[str, ModelBatchResult]
    completed: bool = False
    tested_at: str | None = None


def model_batch_targets(profile: Profile | None) -> list[str]:
    if profile is None:
        return []
    models: list[str] = []
    for model in profile.health.models:
        model_name = str(model).strip()
        if model_name and model_name not in models:
            models.append(model_name)
    return models


def ordered_model_batch_models(models: list[str], results: dict[str, ModelBatchResult], completed: bool) -> list[str]:
    if not completed:
        return list(models)
    order = {model: index for index, model in enumerate(models)}
    return sorted(models, key=lambda model: (0 if results.get(model, ModelBatchResult()).status == "success" else 1, order.get(model, 0)))


def successful_model_batch_models(cache: ModelBatchCache | None) -> list[str]:
    if cache is None or not cache.completed:
        return []
    return [model for model in ordered_model_batch_models(cache.models, cache.results, True) if cache.results.get(model, ModelBatchResult()).status == "success"]


def model_batch_health_summary(cache: ModelBatchCache | None) -> str:
    if cache is None:
        return "未执行测试"
    if not cache.completed:
        finished = sum(1 for item in cache.results.values() if item.status in {"success", "error"})
        success_count = sum(1 for item in cache.results.values() if item.status == "success")
        return f"测试中，完成 {finished}/{len(cache.models)}，成功 {success_count}"
    success_models = successful_model_batch_models(cache)
    if not success_models:
        return "无成功模型"
    return compact_text(", ".join(success_models), 140)


def model_batch_counts(cache: ModelBatchCache) -> tuple[int, int]:
    success_count = sum(1 for item in cache.results.values() if item.status == "success")
    error_count = sum(1 for item in cache.results.values() if item.status == "error")
    return success_count, error_count


def model_batch_caches_from_payload(payload) -> dict[str, ModelBatchCache]:
    if not isinstance(payload, dict):
        return {}

    caches: dict[str, ModelBatchCache] = {}
    for profile_id, cache_payload in payload.items():
        if not str(profile_id).strip() or not isinstance(cache_payload, dict):
            continue
        if not bool(cache_payload.get("completed", False)):
            continue

        raw_models = cache_payload.get("models", [])
        if not isinstance(raw_models, list):
            continue
        models = [str(model).strip() for model in raw_models if str(model).strip()]
        if not models:
            continue

        raw_results = cache_payload.get("results", {})
        if not isinstance(raw_results, dict):
            raw_results = {}
        results: dict[str, ModelBatchResult] = {}
        for model in models:
            result_payload = raw_results.get(model, {})
            if not isinstance(result_payload, dict):
                result_payload = {}
            status = str(result_payload.get("status", "pending") or "pending")
            if status not in {"pending", "running", "success", "error"}:
                status = "pending"
            raw_duration_ms = result_payload.get("duration_ms")
            try:
                duration_ms = int(raw_duration_ms) if raw_duration_ms is not None else None
            except (TypeError, ValueError):
                duration_ms = None
            if duration_ms is not None and duration_ms < 0:
                duration_ms = None
            results[model] = ModelBatchResult(
                status=status,
                detail=str(result_payload.get("detail", "") or ""),
                duration_ms=duration_ms,
            )

        caches[str(profile_id)] = ModelBatchCache(
            models=models,
            results=results,
            completed=True,
            tested_at=str(cache_payload.get("tested_at") or "") or None,
        )
    return caches


def model_batch_caches_to_payload(caches: dict[str, ModelBatchCache]) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for profile_id, cache in caches.items():
        if not cache.completed:
            continue
        models = [str(model).strip() for model in cache.models if str(model).strip()]
        if not models:
            continue
        results_payload: dict[str, dict] = {}
        for model in models:
            result = cache.results.get(model, ModelBatchResult())
            results_payload[model] = {
                "status": result.status,
                "detail": result.detail,
                "duration_ms": result.duration_ms,
            }
        payload[str(profile_id)] = {
            "models": models,
            "results": results_payload,
            "completed": True,
            "tested_at": cache.tested_at,
        }
    return payload


def run_model_batch_requests(
    chat_tester: ChatTester,
    profile: Profile,
    models: list[str],
    wire_api: str,
    payload_text: str | None,
    on_start,
    on_result,
    *,
    max_workers: int = DEFAULT_MODEL_BATCH_CONCURRENCY,
) -> None:
    if not models:
        return

    worker_count = max(1, min(max_workers, len(models)))

    def test_model(model: str) -> tuple[str, str, str, int]:
        started = perf_counter()
        try:
            result = chat_tester.send_message(
                profile,
                MODEL_BATCH_PROMPT,
                model_override=model,
                wire_api_override=wire_api,
                payload_override_text=payload_text,
            )
            status = "success" if result.ok else "error"
            detail = result.text
            if result.detail:
                detail = f"{detail}  {result.detail}"
        except Exception:
            status = "error"
            detail = "测试异常"
        duration_ms = int((perf_counter() - started) * 1000)
        return model, status, detail, duration_ms

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending_models = iter(models)
        future_by_model = {}

        def submit_next() -> None:
            try:
                model = next(pending_models)
            except StopIteration:
                return
            on_start(model)
            future_by_model[executor.submit(test_model, model)] = model

        for _ in range(worker_count):
            submit_next()

        while future_by_model:
            done, _ = wait(future_by_model, return_when=FIRST_COMPLETED)
            for future in done:
                model = future_by_model.pop(future)
                try:
                    result_model, status, detail, duration_ms = future.result()
                except Exception:
                    result_model, status, detail, duration_ms = model, "error", "测试异常", 0
                on_result(result_model, status, detail, duration_ms)
                submit_next()
