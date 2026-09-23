"""Minimal safe EKT product assistant web app (Python standard library only)."""
from __future__ import annotations

import json
import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from ekt_api_client import EKTAPIError, get_product_detail, get_products

DEMO_MODE = False
DEMO_PRODUCTS = [
    {"id": "demo-101", "article": "DEMO-101", "name": "Ноутбук для офиса 15 дюймов", "stock": 8,
     "characteristics": {"Экран": "15.6 дюйма", "Память": "16 ГБ", "Накопитель": "512 ГБ SSD"}},
    {"id": "demo-102", "article": "DEMO-102", "name": "Ноутбук для офиса 14 дюймов", "stock": 3,
     "characteristics": {"Экран": "14 дюймов", "Память": "8 ГБ", "Накопитель": "256 ГБ SSD"}},
    {"id": "demo-201", "article": "DEMO-201", "name": "Беспроводная мышь", "stock": 24,
     "characteristics": {"Подключение": "USB адаптер", "Цвет": "Чёрный"}},
]


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


def respond(message):
    query = message.strip()
    if not query:
        return {"reply": "Напишите артикул или название товара.", "products": []}
    # The assistant performs catalog lookup only. It cannot place orders, reserve stock,
    # request credentials/payment data, or claim availability absent an API value.
    try:
        matches, count, catalog_rows = search(query)
    except EKTAPIError as exc:
        return {"reply": f"Не удалось проверить каталог EKT: {exc}", "products": [], "mode": "api"}
    mode = "demo" if DEMO_MODE else "api"
    mode_note = "ДЕМО: синтетические данные, не отражают реальный каталог." if DEMO_MODE else ""
    if not matches:
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
    return {"reply": (mode_note + " " if mode_note else "") + reply, "products": products, "mode": mode}


PAGE = r'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HackAlem AI · EKT</title>
<style>body{margin:0;background:#f4f7fb;color:#172033;font:16px system-ui}main{max-width:760px;margin:5vh auto;padding:24px}.box{background:white;border:1px solid #e0e6ef;border-radius:18px;box-shadow:0 12px 40px #1e355512;overflow:hidden}.head{padding:22px 26px;background:#102d50;color:white}.head h1{margin:0;font-size:22px}.head p{margin:5px 0 0;color:#c7d7e9}.messages{padding:24px;min-height:290px;max-height:55vh;overflow:auto}.msg{padding:12px 15px;border-radius:14px;background:#edf3f9;margin:0 0 14px;line-height:1.5;white-space:pre-wrap}.user{background:#dcecff;margin-left:18%}.card{border:1px solid #dce3ed;border-radius:13px;padding:14px;margin:9px 0}.card h3{font-size:16px;margin:0 0 8px}.muted{color:#66748a;font-size:14px}.attrs{margin:9px 0 0;padding-left:20px}.form{display:flex;gap:10px;padding:16px 20px;border-top:1px solid #e5eaf1}input{flex:1;min-width:0;border:1px solid #cbd5e1;border-radius:10px;padding:13px;font:inherit}button{background:#1769aa;color:white;border:0;border-radius:10px;padding:0 20px;font:inherit;cursor:pointer}button:disabled{opacity:.6}small{display:block;padding:0 24px 14px;color:#778398}</style>
<main><section class="box"><header class="head"><h1>Помощник по каталогу EKT</h1><p>Поиск товара по артикулу или названию</p><p style="font-weight:700;color:#ffe18a">__MODE_LABEL__</p></header><div class="messages" id="messages"><div class="msg">Здравствуйте! Укажите артикул или название товара — проверю каталог, наличие и характеристики.</div></div><form class="form" id="form"><input id="q" maxlength="160" autocomplete="off" placeholder="Например, артикул или название" required><button id="send">Найти</button></form><small>Чат только показывает сведения каталога. Он не оформляет заказы и не запрашивает платёжные данные.</small></section></main>
<script>const log=document.querySelector('#messages'), form=document.querySelector('#form'), input=document.querySelector('#q'), send=document.querySelector('#send');
function msg(text, cls=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;log.append(d);log.scrollTop=log.scrollHeight;return d}
form.onsubmit=async e=>{e.preventDefault();let text=input.value.trim();if(!text)return;msg(text,'user');input.value='';send.disabled=true;try{let r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});let data=await r.json();msg(data.reply||'Не удалось обработать запрос.');for(let p of (data.products||[])){let box=document.createElement('div');box.className='card';let h=document.createElement('h3');h.textContent=p.name;box.append(h);let line=document.createElement('div');line.className='muted';line.textContent='Артикул: '+p.article+' · Наличие: '+p.stock+(p.price?' · Цена: '+p.price:'');box.append(line);if(p.characteristics?.length){let ul=document.createElement('ul');ul.className='attrs';for(let a of p.characteristics){let li=document.createElement('li');li.textContent=(a.name||a.key||'Характеристика')+': '+(a.value??a.valueName??'');ul.append(li)}box.append(ul)}log.append(box)}for(let s of (data.suggestions||[]))msg(s);log.scrollTop=log.scrollHeight}catch{msg('Сервис временно недоступен. Попробуйте позже.')}finally{send.disabled=false;input.focus()}};</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path != "/":
            self.send_error(404); return
        label = "ДЕМО-РЕЖИМ · синтетические данные" if DEMO_MODE else "РЕАЛЬНЫЙ РЕЖИМ · данные из API"
        body = PAGE.replace("__MODE_LABEL__", label).encode()
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
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
            result = respond(message)
            raw = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
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
