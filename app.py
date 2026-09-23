"""Minimal safe EKT product assistant web app (Python standard library only)."""
from __future__ import annotations

import json
import argparse
import html
import re
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ekt_api_client import EKTAPIError, get_product_detail, get_products

DEMO_MODE = False
DEMO_SESSIONS = {}
DEMO_SESSIONS_LOCK = threading.Lock()
DEMO_PRODUCTS = [
    {"id": "demo-101", "article": "DEMO-101", "name": "Ноутбук для офиса 15 дюймов", "stock": 8,
     "characteristics": {"Экран": "15.6 дюйма", "Память": "16 ГБ", "Накопитель": "512 ГБ SSD"},
     "certificate": {"title": "Demo-свидетельство соответствия DEMO-CERT-101", "description": "Синтетический макет: ноутбук DEMO-101 условно соответствует демонстрационному профилю офисного оборудования."}},
    {"id": "demo-102", "article": "DEMO-102", "name": "Ноутбук для офиса 14 дюймов", "stock": 3,
     "characteristics": {"Экран": "14 дюймов", "Память": "8 ГБ", "Накопитель": "256 ГБ SSD"}, "certificate": None},
    {"id": "demo-201", "article": "DEMO-201", "name": "Беспроводная мышь", "stock": 24,
     "characteristics": {"Подключение": "USB адаптер", "Цвет": "Чёрный"}, "certificate": None},
]
DEMO_PURCHASE_TERMS = {
    "payment": "Оплата: синтетический пример — условно при получении.",
    "delivery": "Доставка: синтетический пример — условно за 3–5 дней.",
    "minimum": "Минимальная партия: синтетический пример — 1 штука.",
}


def _products(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("products", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = _products(value)
                if nested:
                    return nested
    return []


def _text(product, names):
    for key in names:
        value = product.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return ""


def _detail(product):
    """Fetch by ID when available; preserve list entry when detail is unavailable."""
    pid = _text(product, ("id", "productId", "product_id", "uid"))
    if not pid:
        return product
    try:
        value = get_product_detail(pid)
    except EKTAPIError:
        return product
    if isinstance(value, dict):
        for key in ("product", "data", "item"):
            if isinstance(value.get(key), dict):
                return {**product, **value[key]}
        return {**product, **value}
    return product


def search(query):
    rows = DEMO_PRODUCTS if DEMO_MODE else _products(get_products())
    q = query.casefold().strip()
    sku_keys = ("article", "sku", "articul", "vendorCode", "vendor_code", "code")
    name_keys = ("name", "title", "productName", "product_name", "description")
    def rank(row):
        sku = _text(row, sku_keys).casefold()
        name = _text(row, name_keys).casefold()
        if sku == q: return 0
        if q in sku: return 1
        if q == name: return 2
        if q in name: return 3
        return 99
    matches = sorted((r for r in rows if isinstance(r, dict) and rank(r) < 99), key=rank)
    return [dict(row) if DEMO_MODE else _detail(row) for row in matches[:8]], len(rows), rows


def _safe_product(row):
    # Return catalog fields only; never expose arbitrary raw API data or credentials.
    name = _text(row, ("name", "title", "productName", "product_name")) or "Товар"
    article = _text(row, ("article", "sku", "articul", "vendorCode", "vendor_code", "code"))
    stock = _text(row, ("stock", "quantity", "availability", "available", "inStock", "in_stock", "balance"))
    price = _text(row, ("price", "retailPrice", "retail_price"))
    attrs = row.get("characteristics") or row.get("attributes") or row.get("properties") or {}
    characteristics = []
    if isinstance(attrs, dict):
        characteristics = [{"name": str(k), "value": str(v)} for k, v in list(attrs.items())[:12] if not isinstance(v, (dict, list))]
    elif isinstance(attrs, list):
        characteristics = [x for x in attrs[:12] if isinstance(x, dict)]
    return {"name": name, "article": article or "не указан", "stock": stock or "не указано в ответе API", "price": price,
            "characteristics": characteristics}


DEMO_CATEGORY_ROOTS = {
    "laptop": ("ноутбук", "ноут", "лэптоп", "лаптоп", "laptop", "notebook"),
    "mouse": ("мыш", "mouse", "mice", "мышк", "указател", "pointer"),
}
DEMO_CATEGORY_NAMES = {"laptop": "ноутбук", "mouse": "мышь"}
DEMO_QUERY_FILLER = {
    "a", "an", "the", "for", "i", "need", "find", "show", "please", "alternative", "replacement",
    "подбери", "подобрать", "найди", "найти", "ищу", "нужен", "нужна", "нужно", "покажи", "пожалуйста", "no",
    "альтернатива", "замена", "вместо", "нет", "наличии", "наличие", "товар", "товара", "есть",
    "доступный", "доступная", "stock", "available", "в", "и", "без",
}
DEMO_CATEGORY_SYNONYMS = {word for roots in DEMO_CATEGORY_ROOTS.values() for word in roots} | {"portable", "computer"}


def _demo_category(text):
    tokens = re.findall(r"[\w-]+", str(text).casefold())
    if "portable" in tokens and "computer" in tokens:
        return "laptop"
    for category, roots in DEMO_CATEGORY_ROOTS.items():
        if any(token.startswith(root) for token in tokens for root in roots):
            return category
    return None


def _demo_characteristic_text(product):
    attributes = product.get("characteristics") or product.get("attributes") or {}
    pairs = []
    if isinstance(attributes, dict):
        pairs = [(str(key), str(value)) for key, value in attributes.items() if not isinstance(value, (dict, list))]
    elif isinstance(attributes, list):
        pairs = [(str(item.get("name", item.get("key", "Характеристика"))),
                  str(item.get("value", item.get("valueName", "")))) for item in attributes if isinstance(item, dict)]
    return pairs


def _demo_query_fits_candidate(query, candidate):
    article_free = re.sub(r"\bDEMO-\d+\b", " ", query, flags=re.I)
    tokens = set(re.findall(r"[\w-]+", article_free.casefold()))
    evidence_text = _text(candidate, ("name", "title")) + " " + " ".join(
        f"{key} {value}" for key, value in _demo_characteristic_text(candidate))
    evidence = set(re.findall(r"[\w-]+", evidence_text.casefold()))
    required_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", article_free))
    evidence_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", evidence_text))
    if not required_numbers.issubset(evidence_numbers):
        return False
    for token in tokens:
        if (token in DEMO_QUERY_FILLER or token in DEMO_CATEGORY_SYNONYMS
                or token.isdigit() or _demo_category(token)):
            continue
        if token not in evidence:
            return False
    return True


def _demo_alternative_card(candidate, category):
    product = _safe_product(candidate)
    properties = _demo_characteristic_text(candidate)
    facts = "; ".join(f"{key}: {value}" for key, value in properties[:3])
    explanation = (f"Та же категория ({DEMO_CATEGORY_NAMES[category]}), demo-остаток {candidate.get('stock', 0)} шт.")
    if facts:
        explanation += f"; характеристики из demo-карточки: {facts}."
    else:
        explanation += "."
    product["alternative_reason"] = explanation
    return product


def _demo_alternatives(query, rows, reference_products=()):
    reference_products = tuple(reference_products)
    category = (_demo_category(_text(reference_products[0], ("name", "title")))
                if reference_products else _demo_category(query))
    if category is None:
        return []
    excluded = {_text(row, ("article", "sku", "articul", "code")).casefold() for row in reference_products}
    alternatives = []
    for row in rows:
        if not isinstance(row, dict) or _demo_category(_text(row, ("name", "title"))) != category:
            continue
        article = _text(row, ("article", "sku", "articul", "code")).casefold()
        if article in excluded or _demo_stock(row) <= 0 or not _demo_query_fits_candidate(query, row):
            continue
        alternatives.append(_demo_alternative_card(row, category))
    return alternatives


def _session(session_id):
    with DEMO_SESSIONS_LOCK:
        return DEMO_SESSIONS.setdefault(session_id, {"cart": {}, "pending": None, "last_selected": None})


def _demo_context_product(state):
    article = state.get("last_selected")
    return next((row for row in DEMO_PRODUCTS if row["article"].casefold() == str(article).casefold()), None)


def _demo_search_query(query):
    return re.sub(r"\s+", " ", re.sub(r"\b(покажи(?:те)?|показать|найди|найти|show|find|товар|product)\b", " ", query, flags=re.I)).strip(" ,.!?:;")


def _demo_context_intent(query):
    lowered = query.casefold()
    if re.search(r"сертификат|сертификац|certificate|certification", lowered):
        return "certificate"
    if re.search(r"балама|альтернатив|замен|alternative", lowered):
        return "alternative"
    if re.search(r"сипаттам|қасиет|характеристик|specification", lowered):
        return "characteristics"
    if re.search(r"сколько\s+стоит|цен[аыуе]|price|cost|how\s+much|бағасы|баға\w*\s+қанша", lowered):
        return "price"
    if re.search(r"остаток|наличи|сколько\s+(?:есть|остал)|availability|stock|бар\s+ма|қанша\s+(?:дана\s+)?бар", lowered):
        return "stock"
    return None


def _demo_context_target(query, state, intent):
    text = re.sub(r"\b(какой|какое|какая|какие|какого|каком|сколько|есть|ли|а|и|у|в|на|этот|эта|это|этого|этой|этом|этим|данный|данная|данное|данного|данной|данном|товар|товара|товаре|товару|покажи|показать|остаток|наличие|наличии|осталось|стоит|цена|цену|сертификат\w*|сертификац\w*|характеристик\w*|бар|ма|қанша|дана|бағасы|баға|сипаттам\w*|қасиет\w*|қандай|please|what|is|the|stock|availability|price|cost|how|much|certificate)\b", " ", query, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.!?:;")
    if not text:
        product = _demo_context_product(state)
        return ([product] if product else []), False
    matches, _, _ = search(text)
    return matches, True


def _demo_clarify_product(state, candidates=()):
    state["last_selected"] = None
    if candidates:
        options = ", ".join(f"{_text(row, ('article', 'sku', 'code'))} — {_text(row, ('name', 'title'))}" for row in candidates)
        reply = f"Уточните артикул или товар: {options}."
    else:
        reply = "Уточните артикул или название товара."
    return {"reply": reply, "products": [_safe_product(row) for row in candidates], "mode": "demo", "cart": _cart_view(state)}


def _demo_stock(product):
    try:
        return int(product.get("stock", 0))
    except (TypeError, ValueError):
        return 0


def _cart_view(state):
    return [{"article": article, "name": row["name"], "quantity": row["quantity"]}
            for article, row in state["cart"].items()]


def _cart_reply(state, reply):
    return {"reply": reply, "products": [], "mode": "demo", "cart": _cart_view(state)}


def _demo_cart_intent(message):
    return bool(re.search(r"добавь|добавить|положи|положить|корзин[уы]?|add|cart|қос(?:шы|у)?|себет", message.casefold()))


def _demo_cart_view_intent(message):
    return bool(re.fullmatch(r"\s*(корзина|покажи корзину|моя корзина|себет|себетті көрсет|себетімді көрсет|менің себетім)\s*[.!?]*\s*", message, re.I))


def _demo_cart_contents(state):
    items = _cart_view(state)
    lines = [f"{row['name']} ({row['article']}) — {row['quantity']} шт." for row in items]
    total_quantity = sum(row["quantity"] for row in items)
    summary = (f"Итого: товарных позиций — {len(items)}, единиц — {total_quantity} шт. "
               "Сумма к оплате в demo-режиме не рассчитывается.")
    return "Содержимое demo-корзины:\n" + "\n".join(lines + [summary])


def _requested_quantity(message):
    # Digits inside article codes such as DEMO-101 are not quantities.
    found = re.findall(r"(?<![\w-])\d+(?![\w-])", message)
    return int(found[-1]) if found else None


def _product_query(message):
    cleaned = re.sub(r"\b(DEMO-\d+)(?:-[\w]+)?\b", r"\1", message, flags=re.I)
    cleaned = re.sub(r"добавь|добавить|положи|положить|в|корзину|корзина|корзине|add|to|cart|қос(?:шы|у)?|себетке|себет|дана", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?<![\w-])\d+(?![\w-])", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.!?:;")


def _demo_purchase_terms(query):
    lowered = query.casefold()
    selected = []
    if re.search(r"оплат|плат[её]ж|рассроч|payment|pay\b|төлем", lowered):
        selected.append("payment")
    if re.search(r"достав|привез|сроки?\b|delivery|shipping|жеткіз", lowered):
        selected.append("delivery")
    if re.search(r"миним|парт[ияию]|moq\b|minimum|ең\s+аз|минималды\s+партия", lowered):
        selected.append("minimum")
    if not selected and re.search(r"услови|покупк|приобрести|terms\b|purchase|сатып\s+алу", lowered):
        selected = list(DEMO_PURCHASE_TERMS)
    if not selected:
        return None
    rows = "\n".join(DEMO_PURCHASE_TERMS[key] for key in selected)
    return ("DEMO / СИНТЕТИЧЕСКИЕ ПРИМЕРЫ. Это вымышленные значения только для демонстрации; "
            "они не являются реальными условиями EKT.\n" + rows)


def _demo_certificate_response(query, state, prefix="", default_product=None):
    if not re.search(r"сертификат|сертификац|certificate|certification", query, re.I):
        return None
    product_text = re.sub(
        r"\b(сертификат\w*|сертификац\w*|certificate\w*|certification\w*|покажи(?:те)?|есть|ли|у|для|на|по|этот|эта|это|этого|этой|этом|данный|данная|данное|данного|данной|товар\w*|документ\w*|а|бар|ма|please|show|is|there|any|does|this|have|of|for|product)\b",
        " ", query, flags=re.I)
    product_text = re.sub(r"\s+", " ", product_text).strip(" ,.!?:;")
    if not product_text and default_product is not None:
        product_text = default_product["article"]
    if not product_text:
        return {"reply": prefix + "Уточните товар или артикул, например: «сертификат DEMO-101».",
                "products": [], "mode": "demo", "cart": _cart_view(state)}

    rows = DEMO_PRODUCTS
    article_match = re.search(r"\bDEMO-\d+\b", product_text, re.I)
    if article_match:
        candidates = [row for row in rows if row["article"].casefold() == article_match.group(0).casefold()]
    else:
        terms = set(re.findall(r"[\w-]+", product_text.casefold()))
        scored = [(len(terms & set(re.findall(r"[\w-]+", row["name"].casefold()))), row) for row in rows]
        best = max((score for score, _ in scored), default=0)
        candidates = [row for score, row in scored if score == best and score > 0]

    if len(candidates) != 1:
        state["last_selected"] = None
        if not candidates:
            detail = "Не нашёл товар с таким артикулом или названием."
        else:
            options = ", ".join(f"{row['article']} — {row['name']}" for row in candidates)
            detail = f"Уточните, для какого товара нужен сертификат: {options}."
        return {"reply": prefix + "DEMO: " + detail, "products": [], "mode": "demo", "cart": _cart_view(state)}

    product = candidates[0]
    state["last_selected"] = product["article"]
    certificate = product.get("certificate")
    if not certificate:
        reply = (f"DEMO / СИНТЕТИЧЕСКИЕ ДАННЫЕ: для товара {product['name']} ({product['article']}) "
                 "сертификат в demo-данных отсутствует. Это не говорит о наличии или отсутствии реального документа EKT.")
        return {"reply": prefix + reply, "products": [], "mode": "demo", "cart": _cart_view(state)}

    href = f"/demo-certificates/{product['article']}"
    reply = (f"DEMO / СИНТЕТИЧЕСКИЕ ДАННЫЕ — не реальный документ EKT. Для товара {product['name']}: "
             f"{certificate['title']}. {certificate['description']}")
    return {"reply": prefix + reply, "products": [], "mode": "demo", "cart": _cart_view(state), "certificate_url": href}


def respond(message, session_id="demo"):
    query = message.strip()
    if not query:
        return {"reply": "Напишите артикул или название товара.", "products": []}
    prefix = ""
    if DEMO_MODE:
        state = _session(session_id)
        pending = state.get("pending")
        if pending:
            if re.fullmatch(r"\s*(да|да,?\s*(добавь|подтверждаю)|подтверждаю|подтвердить|yes|иә|ия|иә,?\s*қос(?:шы|у)?)\s*[.!]*\s*", query, re.I):
                product, quantity = pending["product"], pending["quantity"]
                article = product["article"]
                available = _demo_stock(product) - state["cart"].get(article, {}).get("quantity", 0)
                state["pending"] = None
                if quantity > available:
                    return _cart_reply(state, f"Не добавил: сейчас доступно {max(available, 0)} шт. Корзина не изменена.")
                current = state["cart"].setdefault(article, {"name": product["name"], "quantity": 0})
                current["quantity"] += quantity
                return {"reply": f"Добавлено в demo-корзину: {product['name']} — {quantity} шт. Доступный stock до добавления: {available} шт.",
                        "products": [], "mode": "demo", "cart": _cart_view(state), "cart_url": "/demo-cart"}
            if re.fullmatch(r"\s*(нет|отмена|отмени|отменить|не добавляй|no|жоқ|жоқ,?\s*қоспа)\s*[.!]*\s*", query, re.I):
                state["pending"] = None
                return _cart_reply(state, "Хорошо, отменил. Demo-корзина не изменена.")
            state["pending"] = None
            prefix = "Предыдущее предложение отменено без явного подтверждения. "
        else:
            prefix = ""
        if _demo_cart_view_intent(query):
            if not state["cart"]:
                return _cart_reply(state, "Demo-корзина пуста.")
            return {"reply": prefix + _demo_cart_contents(state), "products": [], "mode": "demo",
                    "cart": _cart_view(state), "cart_url": "/demo-cart"}
        if _demo_cart_intent(query):
            quantity = _requested_quantity(query)
            product_text = _product_query(query)
            if not product_text:
                selected = _demo_context_product(state)
                if selected:
                    product_text = selected["article"]
                else:
                    return _cart_reply(state, prefix + "Укажите артикул или название и количество, например: «добавь 2 DEMO-101».")
            if quantity is None or quantity < 1:
                return _cart_reply(state, prefix + "Укажите положительное количество, например: «добавь 2 DEMO-101».")
            candidates, _, _ = search(product_text)
            if not candidates:
                return _cart_reply(state, prefix + "Не нашёл такой товар. Уточните артикул или название; корзина не изменена.")
            product = _safe_product(candidates[0])
            if len(candidates) > 1 and product["article"].casefold() != product_text.casefold():
                state["last_selected"] = None
                return {"reply": prefix + "Нашлось несколько товаров. Выберите один по артикулу, затем укажите количество.",
                        "products": [_safe_product(row) for row in candidates], "mode": "demo", "cart": _cart_view(state)}
            state["last_selected"] = product["article"]
            stock = _demo_stock(candidates[0])
            available = stock - state["cart"].get(product["article"], {}).get("quantity", 0)
            if quantity > available:
                return _cart_reply(state, prefix + f"Запрошено {quantity} шт. {product['name']}; доступный stock — {max(available, 0)} шт. Уменьшите количество. Корзина не изменена.")
            state["pending"] = {"product": product, "quantity": quantity}
            return _cart_reply(state, prefix + f"Подтвердите добавление: {product['name']} (артикул {product['article']}), количество {quantity} шт.; доступный stock сейчас {available} шт. Напишите «да, добавь» для подтверждения или «отмена».")
        terms = _demo_purchase_terms(query)
        if terms:
            return _cart_reply(state, prefix + terms)
        context_intent = _demo_context_intent(query)
        context_product = _demo_context_product(state)
        if context_intent in ("stock", "price", "characteristics"):
            candidates, _ = _demo_context_target(query, state, context_intent)
            if len(candidates) != 1:
                return _demo_clarify_product(state, candidates if len(candidates) > 1 else ())
            selected = candidates[0]
            state["last_selected"] = _text(selected, ("article", "sku", "articul", "vendorCode", "vendor_code", "code"))
            safe = _safe_product(selected)
            if context_intent == "stock":
                reply = f"DEMO: {safe['name']} ({safe['article']}) — доступно {safe['stock']} шт."
            elif context_intent == "price":
                reply = f"DEMO: для {safe['name']} ({safe['article']}) цена в синтетических demo-данных не указана."
            else:
                facts = _demo_characteristic_text(selected)
                detail = "; ".join(f"{key}: {value}" for key, value in facts) or "характеристики не указаны"
                reply = f"DEMO: характеристики {safe['name']} ({safe['article']}): {detail}."
            return _cart_reply(state, prefix + reply)
        certificate_reply = _demo_certificate_response(query, state, prefix, context_product)
        if certificate_reply:
            if "Уточните товар или артикул" in certificate_reply["reply"] and context_product is None:
                state["last_selected"] = None
            return certificate_reply
        if context_intent == "alternative" or re.search(r"балама|альтернатив|замен|alternative", query, re.I):
            reference = context_product
            article_match = re.search(r"\bDEMO-\d+\b", query, re.I)
            if article_match:
                reference = next((row for row in DEMO_PRODUCTS if row["article"].casefold() == article_match.group(0).casefold()), None)
            if reference is None:
                return _cart_reply(state, prefix + "Уточните товар или артикул, для которого нужна альтернатива.")
            state["last_selected"] = reference["article"]
            category = _demo_category(_text(reference, ("name", "title")))
            category_query = DEMO_CATEGORY_NAMES.get(category, "")
            alternatives = _demo_alternatives(category_query, DEMO_PRODUCTS, (reference,))
            reply = ("DEMO: возможные альтернативы; основание выбора показано у каждой позиции."
                     if alternatives else "DEMO: подходящей альтернативы с подтверждаемыми demo-характеристиками не нашлось.")
            return {"reply": prefix + reply, "products": alternatives, "mode": "demo", "cart": _cart_view(state)}
    # The assistant performs catalog lookup only. It cannot place orders, reserve stock,
    # request credentials/payment data, or claim availability absent an API value.
    try:
        search_query = _demo_search_query(query) if DEMO_MODE else query
        matches, count, catalog_rows = search(search_query)
    except EKTAPIError as exc:
        return {"reply": f"Не удалось проверить каталог EKT: {exc}", "products": [], "mode": "api"}
    mode = "demo" if DEMO_MODE else "api"
    mode_note = "ДЕМО: синтетические данные, не отражают реальный каталог." if DEMO_MODE else ""
    if DEMO_MODE:
        mode_note = prefix + mode_note
        if len(matches) == 1:
            state["last_selected"] = _text(matches[0], ("article", "sku", "articul", "vendorCode", "vendor_code", "code")) or None
        elif len(matches) > 1:
            state["last_selected"] = None
        elif not matches:
            state["last_selected"] = None
        if matches and all(_demo_stock(row) <= 0 for row in matches):
            alternatives = _demo_alternatives(query, catalog_rows, matches)
            product_name = _text(matches[0], ("name", "title")) or query
            if alternatives:
                reply = (f"Товар {product_name} найден, но сейчас его нет в demo-остатке. "
                         "Возможные альтернативы той же категории; основание выбора указано у каждой позиции.")
            else:
                reply = (f"Товар {product_name} найден, но сейчас его нет в demo-остатке. "
                         "В demo-каталоге нет доступной релевантной альтернативы с подтверждаемыми характеристиками.")
            return {"reply": (mode_note + " " if mode_note else "") + reply, "products": alternatives, "mode": mode}
    if not matches:
        if DEMO_MODE:
            suggestions = _demo_alternatives(query, catalog_rows)
            if suggestions:
                reply = ("Точного совпадения в demo-каталоге нет. Возможные альтернативы той же категории; "
                         "основание выбора указано у каждой позиции.")
            else:
                reply = ("Точного совпадения в demo-каталоге нет, и для этого запроса не нашлось "
                         "подтверждённой релевантной demo-альтернативы.")
            return {"reply": (mode_note + " " if mode_note else "") + reply,
                    "products": suggestions, "mode": mode}
        # Suggest plausible catalog alternatives by token overlap, and label them
        # clearly as suggestions rather than claiming they are equivalent.
        tokens = {t for t in re.findall(r"[\w-]+", query.casefold()) if len(t) > 1}
        candidates = []
        for row in catalog_rows:
            if not isinstance(row, dict):
                continue
            name = _text(row, ("name", "title", "productName", "product_name", "description"))
            article = _text(row, ("article", "sku", "articul", "vendorCode", "vendor_code", "code"))
            score = len(tokens & set(re.findall(r"[\w-]+", f"{name} {article}".casefold())))
            if score:
                candidates.append((score, row))
        candidates.sort(key=lambda item: item[0], reverse=True)
        suggestions = [_safe_product(dict(row) if DEMO_MODE else _detail(row)) for _, row in candidates[:3]]
        return {"reply": (mode_note + " " if mode_note else "") + "Точного совпадения нет. Возможно, подойдут эти товары из каталога — проверьте характеристики перед выбором:", "products": suggestions, "mode": mode}
    products = [_safe_product(row) for row in matches]
    if len(products) == 1:
        reply = "Нашёл товар в каталоге EKT. Наличие и характеристики показаны по данным API."
        return {"reply": (mode_note + " " if mode_note else "") + reply, "products": products, "mode": mode}
    reply = f"Нашёл {len(products)} совпадений в каталоге (всего записей: {count}). Выберите подходящий:"
    if DEMO_MODE:
        reply = f"В demo-каталоге нашлось несколько товаров. Уточните товар или выберите артикул:"
    return {"reply": (mode_note + " " if mode_note else "") + reply, "products": products, "mode": mode}


PAGE = r'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HackAlem AI · EKT</title>
<style>body{margin:0;background:#f4f7fb;color:#172033;font:16px system-ui}main{max-width:760px;margin:5vh auto;padding:24px}.box{background:white;border:1px solid #e0e6ef;border-radius:18px;box-shadow:0 12px 40px #1e355512;overflow:hidden}.head{padding:22px 26px;background:#102d50;color:white}.head h1{margin:0;font-size:22px}.head p{margin:5px 0 0;color:#c7d7e9}.messages{padding:24px;min-height:290px;max-height:55vh;overflow:auto}.msg{padding:12px 15px;border-radius:14px;background:#edf3f9;margin:0 0 14px;line-height:1.5;white-space:pre-wrap}.user{background:#dcecff;margin-left:18%}.card{border:1px solid #dce3ed;border-radius:13px;padding:14px;margin:9px 0}.card h3{font-size:16px;margin:0 0 8px}.muted{color:#66748a;font-size:14px}.attrs{margin:9px 0 0;padding-left:20px}.form{display:flex;gap:10px;padding:16px 20px;border-top:1px solid #e5eaf1}input{flex:1;min-width:0;border:1px solid #cbd5e1;border-radius:10px;padding:13px;font:inherit}button{background:#1769aa;color:white;border:0;border-radius:10px;padding:0 20px;font:inherit;cursor:pointer}button:disabled{opacity:.6}small{display:block;padding:0 24px 14px;color:#778398}</style>
<main><section class="box"><header class="head"><h1>Помощник по каталогу EKT</h1><p>Поиск товара по артикулу или названию</p><p style="font-weight:700;color:#ffe18a">__MODE_LABEL__</p></header><div class="messages" id="messages"><div class="msg">Здравствуйте! Укажите артикул или название товара — проверю каталог, наличие и характеристики.</div></div><form class="form" id="form"><input id="q" maxlength="160" autocomplete="off" placeholder="Например, артикул или название" required><button id="send">Найти</button></form><small>Чат только показывает сведения каталога. Он не оформляет заказы и не запрашивает платёжные данные.</small></section></main>
<script>const log=document.querySelector('#messages'), form=document.querySelector('#form'), input=document.querySelector('#q'), send=document.querySelector('#send');
function msg(text, cls=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;log.append(d);log.scrollTop=log.scrollHeight;return d}
form.onsubmit=async e=>{e.preventDefault();let text=input.value.trim();if(!text)return;msg(text,'user');input.value='';send.disabled=true;try{let r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});let data=await r.json();msg(data.reply||'Не удалось обработать запрос.');for(let p of (data.products||[])){let box=document.createElement('div');box.className='card';let h=document.createElement('h3');h.textContent=p.name;box.append(h);let line=document.createElement('div');line.className='muted';line.textContent='Артикул: '+p.article+' · Наличие: '+p.stock+(p.price?' · Цена: '+p.price:'');box.append(line);if(p.alternative_reason){let reason=document.createElement('div');reason.className='muted';reason.textContent='Почему предложен: '+p.alternative_reason;box.append(reason)}if(p.characteristics?.length){let ul=document.createElement('ul');ul.className='attrs';for(let a of p.characteristics){let li=document.createElement('li');li.textContent=(a.name||a.key||'Характеристика')+': '+(a.value??a.valueName??'');ul.append(li)}box.append(ul)}log.append(box)}if(data.certificate_url){let a=document.createElement('a');a.href=data.certificate_url;a.textContent='Открыть demo-макет сертификата';a.className='msg';a.style.display='inline-block';log.append(a)}if(data.cart_url){let a=document.createElement('a');a.href=data.cart_url;a.textContent='Открыть demo-корзину';a.className='msg';a.style.display='inline-block';log.append(a)}log.scrollTop=log.scrollHeight}catch{msg('Сервис временно недоступен. Попробуйте позже.')}finally{send.disabled=false;input.focus()}};</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def _session_cookie(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            cookie = SimpleCookie()
        morsel = cookie.get("ekt_demo_session")
        if morsel and re.fullmatch(r"[a-f0-9]{32}", morsel.value):
            return morsel.value, False
        return secrets.token_hex(16), True

    def _send_cookie(self, session_id):
        self.send_header("Set-Cookie", f"ekt_demo_session={session_id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200")

    def do_GET(self):
        path = urlparse(self.path).path
        if DEMO_MODE and path.startswith("/demo-certificates/"):
            article = path.rsplit("/", 1)[-1].upper()
            product = next((row for row in DEMO_PRODUCTS if row["article"] == article), None)
            if product is None or not product.get("certificate"):
                self.send_error(404); return
            certificate = product["certificate"]
            body = ("<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>DEMO certificate</title>"
                    "<style>body{font:16px system-ui;max-width:700px;margin:8vh auto;padding:24px;color:#172033}main{border:4px dashed #bd5e2b;border-radius:16px;padding:28px}strong{color:#a33}</style>"
                    "<main><h1>DEMO / СИНТЕТИЧЕСКИЙ МАКЕТ</h1><strong>НЕ РЕАЛЬНЫЙ СЕРТИФИКАТ EKT · НЕ ЯВЛЯЕТСЯ ДОКУМЕНТОМ</strong>"
                    f"<h2>{html.escape(certificate['title'])}</h2><p>Товар: {html.escape(product['name'])} ({html.escape(article)})</p>"
                    f"<p>{html.escape(certificate['description'])}</p><p>Это демонстрационный текст, а не подтверждение соответствия.</p><a href='/'>Вернуться в чат</a></main></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if DEMO_MODE and path == "/demo-cart":
            session_id, is_new = self._session_cookie()
            state = _session(session_id)
            rows = _cart_view(state)
            listing = "".join(f"<li>{html.escape(row['name'])} · {html.escape(row['article'])} — {row['quantity']} шт.</li>" for row in rows)
            body = ("<!doctype html><html lang='ru'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Demo-корзина</title>"
                    "<style>body{font:16px system-ui;max-width:680px;margin:8vh auto;padding:24px;color:#172033}main{border:1px solid #dce3ed;border-radius:16px;padding:24px}a{color:#1769aa}</style>"
                    "<main><h1>Demo-корзина</h1><p><b>Синтетические данные, не заказ.</b></p>"
                    + (f"<ul>{listing}</ul>" if rows else "<p>Корзина пока пуста.</p>")
                    + "<p>Оплата и оформление заказа недоступны в demo-режиме.</p><a href='/'>Вернуться в чат</a></main></html>").encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            if is_new: self._send_cookie(session_id)
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path != "/":
            self.send_error(404); return
        label = "ДЕМО-РЕЖИМ · синтетические данные" if DEMO_MODE else "РЕАЛЬНЫЙ РЕЖИМ · данные из API"
        body = PAGE.replace("__MODE_LABEL__", label).encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        if DEMO_MODE:
            session_id, is_new = self._session_cookie()
            if is_new: self._send_cookie(session_id)
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_error(404); return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 4096: raise ValueError
            body = json.loads(self.rfile.read(size))
            message = body.get("message", "") if isinstance(body, dict) else ""
            if not isinstance(message, str) or len(message) > 160: raise ValueError
            session_id, is_new = self._session_cookie()
            result = respond(message, session_id)
            raw = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            if DEMO_MODE and is_new: self._send_cookie(session_id)
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        except (ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid request")

    def log_message(self, fmt, *args):
        # Avoid writing user queries or request bodies to terminal logs.
        super().log_message("request completed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HackAlem AI assistant for the EKT catalog")
    parser.add_argument("--demo", action="store_true", help="Run with synthetic sample products; no EKT API calls")
    args = parser.parse_args()
    DEMO_MODE = args.demo
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    label = "synthetic demo data" if DEMO_MODE else "live EKT API"
    print(f"HackAlem AI EKT prototype ({label}): http://127.0.0.1:8000")
    server.serve_forever()
