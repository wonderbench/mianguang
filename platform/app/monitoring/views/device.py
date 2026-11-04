import json
import logging
import time
import uuid

from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from monitoring.services.errors import PlatformError
from monitoring.services.ingestion import ingest_telemetry

logger = logging.getLogger("monitoring.ingest")


@csrf_exempt
@never_cache
def telemetry(request):
    start = time.monotonic()
    request_id = uuid.uuid4().hex
    try:
        if request.method != "POST":
            raise PlatformError("method_not_allowed", "只接受POST。", 405)
        if request.content_type != "application/json" or request.headers.get("Content-Encoding", "identity") != "identity":
            raise PlatformError("unsupported_media_type", "只接受未压缩的application/json。", 415)
        if int(request.META.get("CONTENT_LENGTH") or 0) > 4096:
            raise PlatformError("payload_too_large", "请求体最多4 KiB。", 413)
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:]:
            raise PlatformError("invalid_credential", "需要设备凭证。", 401)
        result = ingest_telemetry(token=authorization[7:], body=request.body)
        status = 200
        code = result["status"]
    except PlatformError as exc:
        result = {"error": {"code": exc.code, "message": exc.message}}
        status, code = exc.status, exc.code
    except RequestDataTooBig:
        result = {"error": {"code": "payload_too_large", "message": "请求体最多4 KiB。"}}
        status, code = 413, "payload_too_large"
    except DatabaseError:
        result = {"error": {"code": "database_unavailable", "message": "暂时无法保存，请稍后重试。"}}
        status, code = 503, "database_unavailable"
    logger.info(json.dumps({"request_id": request_id, "status": status, "code": code,
                           "duration_ms": round((time.monotonic() - start) * 1000, 2)}))
    response = JsonResponse(result, status=status)
    response["X-Request-ID"] = request_id
    if status == 405:
        response["Allow"] = "POST"
    return response


@require_GET
@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
