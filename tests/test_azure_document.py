import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.azure_document import (
    AzureDocumentConfig,
    AzureDocumentError,
    analyze_pdf,
    local_ocr_result,
    normalize_azure_result,
)


def config(enabled=True, key="secret"):
    return AzureDocumentConfig(
        enabled=enabled,
        endpoint="https://facturas.cognitiveservices.azure.com/",
        api_key=key,
        model_id="prebuilt-invoice",
        api_version="2024-11-30",
        timeout_seconds=10,
        poll_interval_seconds=1,
    )


class PruebasAzureDocument(unittest.TestCase):
    def test_ai_disabled_se_presenta_como_ocr_local(self):
        with patch.dict(os.environ, {
            "AI_ENABLED": "false",
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT": "https://example.cognitiveservices.azure.com",
            "AZURE_DOCUMENT_INTELLIGENCE_KEY": "secret",
        }, clear=False):
            current = AzureDocumentConfig.from_env()

        self.assertFalse(current.enabled)
        self.assertFalse(current.configured)
        self.assertEqual(current.public_status()["mode"], "ocr_local")

    def test_normaliza_campos_y_precision_en_porcentaje(self):
        payload = {
            "status": "succeeded",
            "analyzeResult": {
                "modelId": "prebuilt-invoice",
                "apiVersion": "2024-11-30",
                "content": "Factura de prueba",
                "documents": [{
                    "docType": "invoice",
                    "fields": {
                        "InvoiceId": {
                            "type": "string", "valueString": "001-001",
                            "content": "001-001", "confidence": 0.96,
                        },
                        "InvoiceTotal": {
                            "type": "currency", "valueCurrency": {"amount": 50000},
                            "confidence": 0.84,
                        },
                    },
                }],
            },
        }

        result = normalize_azure_result(payload, config())

        self.assertEqual(result["precision"]["porcentaje"], 90.0)
        self.assertEqual(
            result["documentos"][0]["campos"]["InvoiceId"]["precision_porcentaje"],
            96.0,
        )

    def test_post_y_get_de_azure_sin_enviar_clave_a_otro_host(self):
        success = {
            "status": "succeeded",
            "analyzeResult": {"documents": [], "content": "texto"},
        }
        operation = "https://facturas.cognitiveservices.azure.com/documentintelligence/operations/123"
        with patch("core.azure_document._send", side_effect=[
            ({}, {"Operation-Location": operation}),
            (success, {}),
        ]) as send:
            result = analyze_pdf(b"%PDF-prueba", config())

        self.assertEqual(send.call_args_list[0].args[0].get_method(), "POST")
        self.assertEqual(send.call_args_list[1].args[0].get_method(), "GET")
        self.assertEqual(result["estado"], "completado")

        with patch("core.azure_document._send", return_value=(
            {}, {"Operation-Location": "https://sitio-malicioso.example/resultado"},
        )):
            with self.assertRaises(AzureDocumentError):
                analyze_pdf(b"%PDF-prueba", config())

    def test_ocr_local_devuelve_json_sin_inventar_precision(self):
        detalle = SimpleNamespace(
            codigo_proveedor="40001", descripcion="Producto", cantidad_facturada=2,
            precio_unitario=100, importe=200,
        )
        factura = SimpleNamespace(
            metodo_extraccion="ocr_tesseract", proveedor="Helacor",
            numero_factura="001", fecha_emision=None, total_factura=200,
            detalles=[detalle], texto_extraido="texto OCR",
        )

        result = local_ocr_result(factura)

        self.assertEqual(result["motor"], "ocr_local")
        self.assertIsNone(result["precision"]["porcentaje"])
        self.assertEqual(
            result["documentos"][0]["campos"]["Items"]["valor"][0]["codigo"],
            "40001",
        )


if __name__ == "__main__":
    unittest.main()
