"""Focused regression tests for the local HackAlem EKT demo flows."""
import unittest
from unittest.mock import patch

import app


class DemoCertificateTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True
        self.session_id = "certificate-test-session"
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        app.DEMO_MODE = self.was_demo
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def test_certificate_for_product_includes_synthetic_label_and_safe_link(self):
        result = app.respond("сертификат DEMO-101", self.session_id)

        self.assertEqual(result["mode"], "demo")
        self.assertEqual(result["certificate_url"], "/demo-certificates/DEMO-101")
        self.assertIn("DEMO / СИНТЕТИЧЕСКИЕ ДАННЫЕ", result["reply"])
        self.assertIn("DEMO-CERT-101", result["reply"])
        self.assertIn("не реальный документ EKT", result["reply"])
        self.assertEqual(result["cart"], [])
        by_name = app.respond("сертификат ноутбук для офиса 15 дюймов", self.session_id)
        self.assertEqual(by_name["certificate_url"], "/demo-certificates/DEMO-101")

    def test_missing_certificate_is_reported_for_specific_product(self):
        result = app.respond("сертификаты для DEMO-102", self.session_id)

        self.assertEqual(result["mode"], "demo")
        self.assertNotIn("certificate_url", result)
        self.assertIn("DEMO-102", result["reply"])
        self.assertIn("сертификат в demo-данных отсутствует", result["reply"])
        self.assertIn("не говорит о наличии или отсутствии реального документа EKT", result["reply"])

    def test_unspecified_product_prompts_for_article(self):
        result = app.respond("покажи сертификат", self.session_id)

        self.assertIn("Уточните товар или артикул", result["reply"])
        self.assertNotIn("certificate_url", result)

    def test_certificate_faq_is_demo_only_and_preserves_other_flows(self):
        app.DEMO_MODE = False
        with patch("app.get_products", side_effect=app.EKTAPIError("mock API unavailable")):
            api_result = app.respond("сертификат DEMO-101", self.session_id)
        self.assertEqual(api_result["mode"], "api")
        self.assertNotIn("certificate_url", api_result)

        app.DEMO_MODE = True
        product = app.respond("DEMO-101", self.session_id)["products"][0]
        self.assertEqual(product["stock"], "8")
        self.assertTrue(product["characteristics"])
        alternatives = app.respond("ноутбук игровой", "certificate-test-alternatives")
        self.assertEqual(len(alternatives["products"]), 2)


if __name__ == "__main__":
    unittest.main()
