"""Focused regression tests for the local HackAlem EKT demo flows."""
from copy import deepcopy
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
        alternatives = app.respond("лэптоп", "certificate-test-alternatives")
        self.assertEqual(len(alternatives["products"]), 2)


class DemoCartViewTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True
        self.session_id = "cart-view-regression-session"
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        app.DEMO_MODE = self.was_demo
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def test_empty_cart_queries_report_empty_without_mutating_cart(self):
        for message in ("корзина", "покажи корзину", "моя корзина", "Покажи корзину?"):
            with self.subTest(message=message):
                before = dict(app._session(self.session_id)["cart"])
                result = app.respond(message, self.session_id)
                self.assertIn("пуста", result["reply"])
                self.assertEqual(app._session(self.session_id)["cart"], before)

    def test_view_after_add_shows_items_totals_and_link_without_mutation(self):
        app.respond("добавь 2 DEMO-101", self.session_id)
        app.respond("да, добавь", self.session_id)
        before = deepcopy(app._session(self.session_id)["cart"])

        result = app.respond("покажи корзину", self.session_id)

        self.assertIn("Ноутбук для офиса 15 дюймов", result["reply"])
        self.assertIn("2 шт.", result["reply"])
        self.assertIn("Итого: товарных позиций — 1, единиц — 2 шт.", result["reply"])
        self.assertEqual(result["cart_url"], "/demo-cart")
        self.assertEqual(app._session(self.session_id)["cart"], before)

    def test_addition_requires_confirmation(self):
        proposal = app.respond("добавь 2 DEMO-101", self.session_id)
        self.assertEqual(proposal["cart"], [])
        self.assertEqual(app._session(self.session_id)["cart"], {})

        result = app.respond("да, добавь", self.session_id)
        self.assertEqual(result["cart"][0]["quantity"], 2)
        self.assertEqual(result["cart_url"], "/demo-cart")

    def test_refusal_and_cancel_leave_cart_unchanged(self):
        for answer in ("нет", "отмена"):
            with self.subTest(answer=answer):
                app.DEMO_SESSIONS.pop(self.session_id, None)
                app.respond("добавь 2 DEMO-101", self.session_id)
                result = app.respond(answer, self.session_id)
                self.assertIn("не изменена", result["reply"])
                self.assertEqual(result["cart"], [])
                self.assertEqual(app._session(self.session_id)["cart"], {})


class DemoAlternativeTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True

    def tearDown(self):
        app.DEMO_MODE = self.was_demo

    def test_synonym_query_gets_same_category_alternatives_with_rationale(self):
        result = app.respond("лэптоп", "alternative-synonym-test")

        self.assertEqual(result["mode"], "demo")
        self.assertEqual(len(result["products"]), 2)
        for product in result["products"]:
            self.assertIn("ноутбук", product["name"].casefold())
            self.assertGreater(int(product["stock"]), 0)
            self.assertIn("та же категория", product["alternative_reason"].casefold())
            self.assertIn("характеристики из demo-карточки", product["alternative_reason"])
        mouse = app.respond("pointer", "alternative-pointer-test")
        self.assertEqual([row["article"] for row in mouse["products"]], ["DEMO-201"])
        self.assertIn("Подключение", mouse["products"][0]["alternative_reason"])

    def test_out_of_stock_item_gets_available_same_category_alternative(self):
        demo_products = deepcopy(app.DEMO_PRODUCTS)
        demo_products[0]["stock"] = 0
        with patch.object(app, "DEMO_PRODUCTS", demo_products):
            result = app.respond("DEMO-101", "alternative-out-of-stock-test")

        self.assertIn("нет в demo-остатке", result["reply"])
        self.assertEqual([row["article"] for row in result["products"]], ["DEMO-102"])
        self.assertIn("Та же категория", result["products"][0]["alternative_reason"])
        self.assertIn("Экран", result["products"][0]["alternative_reason"])

    def test_no_relevant_alternative_is_reported_instead_of_random_item(self):
        for query in ("холодильник", "laptop RTX 4090"):
            with self.subTest(query=query):
                result = app.respond(query, "alternative-none-test")
                self.assertEqual(result["products"], [])
                self.assertIn("не нашлось", result["reply"])
                self.assertIn("релевантной", result["reply"])

    def test_out_of_stock_category_without_available_replacement_is_reported(self):
        demo_products = deepcopy(app.DEMO_PRODUCTS)
        demo_products[0]["stock"] = 0
        demo_products[1]["stock"] = 0
        with patch.object(app, "DEMO_PRODUCTS", demo_products):
            result = app.respond("DEMO-101", "alternative-no-stock-test")

        self.assertEqual(result["products"], [])
        self.assertIn("нет доступной релевантной альтернативы", result["reply"])


if __name__ == "__main__":
    unittest.main()
