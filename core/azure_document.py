"""Análisis opcional de facturas con Azure AI Document Intelligence."""
from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import datetime, timezone
import json
import math
import os
import time
from typing import Any
from urllib import error as urlerror
from urllib import request
from urllib.parse import quote, urlparse


MAX_RESPONSE_BYTES = 8_000_000


class AzureDocumentError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class AzureDocumentConfig:
    enabled: bool
    endpoint: str
    api_key: str
    model_id: str
    api_version: str
    timeout_seconds: int
    poll_interval_seconds: int

    @classmethod
    def from_env(cls) -> "AzureDocumentConfig":
        return cls(
            enabled=_enabled(os.getenv("AI_ENABLED", "false")),
            endpoint=(
                os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").strip()
                or os.getenv("AZURE_AI_ENDPOINT", "").strip()
            ),
            api_key=(
                os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()
                or os.getenv("AZURE_AI_KEY", "").strip()
            ),
            model_id=os.getenv(
                "AZURE_DOCUMENT_INTELLIGENCE_MODEL", "prebuilt-invoice"
            ).strip() or "prebuilt-invoice",
            api_version=os.getenv(
                "AZURE_DOCUMENT_INTELLIGENCE_API_VERSION", "2024-11-30"
            ).strip() or "2024-11-30",
            timeout_seconds=_env_int(
                "AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT_SECONDS", 60, 5, 180,
            ),
            poll_interval_seconds=_env_int(
                "AZURE_DOCUMENT_INTELLIGENCE_POLL_SECONDS", 1, 1, 5,
            ),
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.endpoint.startswith("https://")
            and self.api_key
            and self.model_id
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "mode": "azure" if self.configured else "ocr_local",
            "model": self.model_id if self.configured else "OCR local",
            "label": (
                "Azure AI activo" if self.configured else
                ("Azure sin configurar · OCR local" if self.enabled else "Azure desactivado · OCR local")
            ),
        }


def _service_root(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip("/")
    marker = "/documentintelligence/"
    if marker in endpoint.lower():
        index = endpoint.lower().index(marker)
        endpoint = endpoint[:index]
    return endpoint


def _same_secure_service_url(operation_url: str, service_root: str) -> bool:
    """Evita enviar la clave a una URL de seguimiento ajena al recurso Azure."""
    operation = urlparse(operation_url)
    service = urlparse(service_root)
    return bool(
        operation.scheme == "https"
        and service.scheme == "https"
        and operation.hostname
        and operation.hostname == service.hostname
        and (operation.port or 443) == (service.port or 443)
    )


def _response_json(response) -> dict[str, Any]:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AzureDocumentError("La respuesta de Azure excede el límite permitido.")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AzureDocumentError("Azure devolvió una respuesta que no es JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise AzureDocumentError("Azure devolvió un formato inesperado.")
    return parsed


def _send(req: request.Request, timeout: int) -> tuple[dict[str, Any], Any]:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return _response_json(response), response.headers
    except urlerror.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read(200_000).decode("utf-8"))
            detail = str(payload.get("error", {}).get("message") or payload.get("message") or "")
        except Exception:
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise AzureDocumentError(f"Azure rechazó la solicitud (HTTP {exc.code}){suffix}") from exc
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise AzureDocumentError("No se pudo conectar con el servicio de análisis de documentos.") from exc


def _field_value(field: dict[str, Any]) -> Any:
    if isinstance(field.get("valueArray"), list):
        return [_normalize_field(value) for value in field["valueArray"]]
    if isinstance(field.get("valueObject"), dict):
        return {key: _normalize_field(value) for key, value in field["valueObject"].items()}
    for key in (
        "valueString", "valueNumber", "valueInteger", "valueDate", "valueTime",
        "valuePhoneNumber", "valueCountryRegion", "valueSelectionMark", "valueSignature",
    ):
        if key in field:
            return field[key]
    if isinstance(field.get("valueCurrency"), dict):
        return field["valueCurrency"]
    if isinstance(field.get("valueAddress"), dict):
        return field["valueAddress"]
    return field.get("content")


def _normalize_field(field: Any) -> Any:
    if not isinstance(field, dict):
        return field
    confidence = field.get("confidence")
    normalized = {
        "valor": _field_value(field),
        "contenido": field.get("content"),
        "tipo": field.get("type"),
        "precision_porcentaje": (
            round(float(confidence) * 100, 2)
            if isinstance(confidence, (int, float)) and math.isfinite(float(confidence))
            else None
        ),
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _field_confidences(field: Any) -> list[float]:
    if not isinstance(field, dict):
        return []
    values = []
    confidence = field.get("confidence")
    if isinstance(confidence, (int, float)) and math.isfinite(float(confidence)):
        values.append(float(confidence))
    for child in field.get("valueArray") or []:
        values.extend(_field_confidences(child))
    for child in (field.get("valueObject") or {}).values():
        values.extend(_field_confidences(child))
    return values


def normalize_azure_result(payload: dict[str, Any], config: AzureDocumentConfig) -> dict[str, Any]:
    analyze_result = payload.get("analyzeResult") or {}
    documents = analyze_result.get("documents") or []
    normalized_documents = []
    confidences: list[float] = []
    for document in documents:
        fields = document.get("fields") or {}
        normalized_fields = {key: _normalize_field(value) for key, value in fields.items()}
        for value in fields.values():
            confidences.extend(_field_confidences(value))
        document_confidence = document.get("confidence")
        if isinstance(document_confidence, (int, float)) and math.isfinite(float(document_confidence)):
            confidences.append(float(document_confidence))
        normalized_documents.append({
            "tipo": document.get("docType"),
            "precision_documento_porcentaje": (
                round(float(document_confidence) * 100, 2)
                if isinstance(document_confidence, (int, float)) else None
            ),
            "campos": normalized_fields,
        })
    precision = {
        "porcentaje": round(sum(confidences) / len(confidences) * 100, 2) if confidences else None,
        "campos_evaluados": len(confidences),
        "minimo_porcentaje": round(min(confidences) * 100, 2) if confidences else None,
        "maximo_porcentaje": round(max(confidences) * 100, 2) if confidences else None,
    }
    return {
        "estado": "completado",
        "motor": "azure_document_intelligence",
        "modelo": analyze_result.get("modelId") or config.model_id,
        "version_api": analyze_result.get("apiVersion") or config.api_version,
        "precision": precision,
        "documentos": normalized_documents,
        "texto_extraido": analyze_result.get("content") or "",
        "analizado_en": datetime.now(timezone.utc).isoformat(),
    }


def analyze_pdf(contenido: bytes, config: AzureDocumentConfig | None = None) -> dict[str, Any]:
    config = config or AzureDocumentConfig.from_env()
    if not config.enabled:
        raise AzureDocumentError("Azure AI está desactivado mediante AI_ENABLED.")
    if not config.configured:
        raise AzureDocumentError(
            "Azure AI está activado, pero faltan AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT o "
            "AZURE_DOCUMENT_INTELLIGENCE_KEY."
        )
    root = _service_root(config.endpoint)
    analyze_url = (
        f"{root}/documentintelligence/documentModels/{quote(config.model_id, safe='')}:analyze"
        f"?_overload=analyzeDocument&api-version={quote(config.api_version, safe='')}"
    )
    body = json.dumps({"base64Source": base64.b64encode(contenido).decode("ascii")}).encode("utf-8")
    post = request.Request(analyze_url, data=body, method="POST")
    post.add_header("Content-Type", "application/json")
    post.add_header("Ocp-Apim-Subscription-Key", config.api_key)
    initial, headers = _send(post, config.timeout_seconds)
    operation_url = headers.get("Operation-Location") or headers.get("operation-location")
    if not operation_url:
        if str(initial.get("status", "")).lower() == "succeeded":
            return normalize_azure_result(initial, config)
        raise AzureDocumentError("Azure no devolvió la ubicación del resultado del análisis.")
    if not _same_secure_service_url(operation_url, root):
        raise AzureDocumentError("Azure devolvió una ubicación de resultado no confiable.")

    deadline = time.monotonic() + config.timeout_seconds
    while time.monotonic() < deadline:
        get = request.Request(operation_url, method="GET")
        get.add_header("Ocp-Apim-Subscription-Key", config.api_key)
        result, _headers = _send(get, config.timeout_seconds)
        status = str(result.get("status") or "").lower()
        if status == "succeeded":
            return normalize_azure_result(result, config)
        if status in {"failed", "canceled"}:
            error = result.get("error") or {}
            raise AzureDocumentError(
                str(error.get("message") or "Azure no pudo analizar el documento.")
            )
        time.sleep(config.poll_interval_seconds)
    raise AzureDocumentError("Azure no completó el análisis dentro del tiempo permitido.")


def local_ocr_result(factura) -> dict[str, Any]:
    return {
        "estado": "completado",
        "motor": "ocr_local",
        "modelo": factura.metodo_extraccion or "OCR local",
        "precision": {
            "porcentaje": None,
            "campos_evaluados": 0,
            "mensaje": "El OCR local no proporciona porcentaje de confianza.",
        },
        "documentos": [{
            "tipo": "factura",
            "campos": {
                "Proveedor": {"valor": factura.proveedor},
                "NumeroFactura": {"valor": factura.numero_factura},
                "FechaEmision": {"valor": factura.fecha_emision.isoformat() if factura.fecha_emision else None},
                "Total": {"valor": factura.total_factura},
                "Items": {"valor": [
                    {
                        "codigo": detalle.codigo_proveedor,
                        "descripcion": detalle.descripcion,
                        "cantidad": detalle.cantidad_facturada,
                        "precio_unitario": detalle.precio_unitario,
                        "importe": detalle.importe,
                    }
                    for detalle in factura.detalles
                ]},
            },
        }],
        "texto_extraido": factura.texto_extraido or "",
        "analizado_en": datetime.now(timezone.utc).isoformat(),
    }
