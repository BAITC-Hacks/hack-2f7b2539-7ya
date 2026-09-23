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


class DemoContextTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True
        self.session_id = "dialog-context-regression"
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        app.DEMO_MODE = self.was_demo
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def test_stock_followup_uses_last_selected_product(self):
        app.respond("покажи DEMO-101", self.session_id)
        result = app.respond("какой остаток?", self.session_id)
        self.assertIn("DEMO-101", result["reply"])
        self.assertIn("доступно 8 шт.", result["reply"])

    def test_full_sentence_followups_use_exactly_selected_product(self):
        cases = (
            ("Какие характеристики у этого товара?", "15.6 дюйма"),
            ("Сколько этого товара есть в наличии?", "8 шт."),
            ("Какая цена у этого товара?", "цена в синтетических demo-данных не указана"),
            ("Есть ли сертификат на этот товар?", "DEMO-CERT-101"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                app.DEMO_SESSIONS.pop(self.session_id, None)
                selected = app.respond("Найди товар DEMO-101", self.session_id)
                self.assertEqual([row["article"] for row in selected["products"]], ["DEMO-101"])
                result = app.respond(message, self.session_id)
                self.assertIn("DEMO-101", result["reply"])
                self.assertIn(expected, result["reply"])

    def test_selecting_another_product_switches_context(self):
        app.respond("покажи DEMO-101", self.session_id)
        app.respond("покажи DEMO-201", self.session_id)
        result = app.respond("какой остаток?", self.session_id)
        self.assertIn("DEMO-201", result["reply"])
        self.assertIn("доступно 24 шт.", result["reply"])

    def test_certificate_followup_uses_last_selected_product(self):
        app.respond("покажи DEMO-101", self.session_id)
        result = app.respond("а сертификат есть?", self.session_id)
        self.assertIn("DEMO-101", result["reply"])
        self.assertIn("DEMO-CERT-101", result["reply"])
        self.assertEqual(result["certificate_url"], "/demo-certificates/DEMO-101")

    def test_add_quantity_uses_context_and_waits_for_confirmation(self):
        app.respond("покажи DEMO-101", self.session_id)
        proposal = app.respond("добавь 2", self.session_id)
        self.assertIn("DEMO-101", proposal["reply"])
        self.assertIn("количество 2 шт.", proposal["reply"])
        self.assertEqual(proposal["cart"], [])
        self.assertEqual(app._session(self.session_id)["cart"], {})
        self.assertEqual(app._session(self.session_id)["pending"]["product"]["article"], "DEMO-101")

    def test_explicit_article_add_with_unit_waits_for_quantity_confirmation(self):
        app.respond("Найди товар DEMO-101", self.session_id)
        state = app._session(self.session_id)
        before = deepcopy(state["cart"])

        proposal = app.respond("Добавь 2 штуки DEMO-101", self.session_id)
        self.assertIn("DEMO-101", proposal["reply"])
        self.assertIn("количество 2 шт.", proposal["reply"])
        self.assertEqual(proposal["cart"], [])
        self.assertEqual(state["cart"], before)
        self.assertEqual(state["pending"]["product"]["article"], "DEMO-101")

        result = app.respond("Да, добавь 2 штуки", self.session_id)
        self.assertEqual(result["cart"][0]["article"], "DEMO-101")
        self.assertEqual(result["cart"][0]["quantity"], 2)

    def test_ambiguous_product_selection_requests_clarification_and_clears_context(self):
        app.respond("покажи DEMO-101", self.session_id)
        result = app.respond("покажи ноутбук", self.session_id)
        self.assertIn("Уточните", result["reply"])
        self.assertEqual({row["article"] for row in result["products"]}, {"DEMO-101", "DEMO-102"})
        followup = app.respond("какой остаток?", self.session_id)
        self.assertIn("Уточните артикул", followup["reply"])

    def test_cart_view_does_not_change_context_or_cart(self):
        app.respond("покажи DEMO-101", self.session_id)
        app.respond("добавь 2", self.session_id)
        app.respond("да, добавь", self.session_id)
        state = app._session(self.session_id)
        before_cart = deepcopy(state["cart"])
        before_context = state["last_selected"]
        result = app.respond("покажи корзину", self.session_id)
        self.assertEqual(result["cart_url"], "/demo-cart")
        self.assertEqual(state["cart"], before_cart)
        self.assertEqual(state["last_selected"], before_context)
        self.assertIn("DEMO-101", state["last_selected"])

    def test_explicit_confirmation_still_adds_context_product(self):
        app.respond("покажи DEMO-101", self.session_id)
        app.respond("добавь 2", self.session_id)
        result = app.respond("да, добавь", self.session_id)
        self.assertEqual(result["cart"][0]["article"], "DEMO-101")
        self.assertEqual(result["cart"][0]["quantity"], 2)
        self.assertEqual(result["cart_url"], "/demo-cart")

    def test_price_followup_uses_context_without_inventing_price(self):
        app.respond("покажи DEMO-101", self.session_id)
        result = app.respond("сколько стоит?", self.session_id)
        self.assertIn("DEMO-101", result["reply"])
        self.assertIn("цена в синтетических demo-данных не указана", result["reply"])

    def test_cancel_without_pending_does_not_change_cart(self):
        app.respond("покажи DEMO-101", self.session_id)
        state = app._session(self.session_id)
        before = deepcopy(state["cart"])
        app.respond("отмени", self.session_id)
        self.assertEqual(state["cart"], before)


class DemoKazakhTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True
        self.session_id = "kazakh-regression-session"
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        app.DEMO_MODE = self.was_demo
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def test_stock_price_characteristics_and_certificate_queries(self):
        stock = app.respond("DEMO-101 бар ма?", self.session_id)
        self.assertIn("DEMO-101", stock["reply"])
        self.assertIn("8 шт.", stock["reply"])
        price = app.respond("Бағасы қанша?", self.session_id)
        self.assertIn("DEMO-101", price["reply"])
        self.assertIn("цена в синтетических demo-данных не указана", price["reply"])
        specs = app.respond("Сипаттамалары қандай?", self.session_id)
        self.assertIn("DEMO-101", specs["reply"])
        self.assertIn("15.6 дюйма", specs["reply"])
        certificate = app.respond("Сертификаты бар ма?", self.session_id)
        self.assertIn("DEMO-CERT-101", certificate["reply"])

    def test_kazakh_cart_view_add_confirmation_and_cancel(self):
        app.respond("покажи DEMO-101", self.session_id)
        proposal = app.respond("2 дана қос", self.session_id)
        self.assertIn("DEMO-101", proposal["reply"])
        self.assertEqual(proposal["cart"], [])
        declined = app.respond("Жоқ, қоспа", self.session_id)
        self.assertIn("не изменена", declined["reply"])
        self.assertEqual(app._session(self.session_id)["cart"], {})

        app.respond("2 дана қос", self.session_id)
        confirmed = app.respond("Иә, қос", self.session_id)
        self.assertEqual(confirmed["cart"][0]["article"], "DEMO-101")
        self.assertEqual(confirmed["cart"][0]["quantity"], 2)
        viewed = app.respond("Себетті көрсет", self.session_id)
        self.assertEqual(viewed["cart_url"], "/demo-cart")
        self.assertEqual(viewed["cart"][0]["quantity"], 2)

    def test_kazakh_terms_and_alternative_queries(self):
        terms = app.respond("Төлем және жеткізу шарттары", self.session_id)
        self.assertIn("DEMO / СИНТЕТИЧЕСКИЕ ПРИМЕРЫ", terms["reply"])
        self.assertIn("Оплата:", terms["reply"])
        self.assertIn("Доставка:", terms["reply"])
        app.respond("покажи DEMO-101", self.session_id)
        alternatives = app.respond("Балама бар ма?", self.session_id)
        self.assertTrue(alternatives["products"])
        self.assertTrue(all(row.get("alternative_reason") for row in alternatives["products"]))


class DemoSearchPhraseTests(unittest.TestCase):
    def setUp(self):
        self.was_demo = app.DEMO_MODE
        app.DEMO_MODE = True
        self.session_id = "demo-search-phrase-regression"
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def tearDown(self):
        app.DEMO_MODE = self.was_demo
        app.DEMO_SESSIONS.pop(self.session_id, None)

    def test_find_product_phrase_matches_exact_demo_article(self):
        result = app.respond("Найди товар DEMO-101", self.session_id)
        self.assertEqual(result["mode"], "demo")
        self.assertEqual([row["article"] for row in result["products"]], ["DEMO-101"])
        self.assertIn("Нашёл товар", result["reply"])


if __name__ == "__main__":
    unittest.main()
