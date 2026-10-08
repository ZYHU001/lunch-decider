"""Local-only server for the lunch page and its TypeSafe Jev request."""

from __future__ import annotations

import json
import ipaddress
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from scoring import TAG_FIELDS, SEMANTIC_FIELDS, build_weights, build_questions, calculate_score, finite_number
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_KEY_FILE = ROOT / ".env" if (ROOT / ".env").is_file() else ROOT.parents[1] / "work" / "lunch-decider.env"
API_URL = "https://api.typesafe.ai/v1/systemone"
MAX_BODY = 256_000
MAX_CANDIDATES = 500
PORT = int(os.environ.get("LUNCH_DECIDER_PORT", "4173"))
HOST = os.environ.get("LUNCH_DECIDER_HOST", "127.0.0.1")
REQUEST_TIMES: dict[str, list[float]] = {}
REQUEST_LOCK = threading.Lock()


def api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    key_file = Path(os.environ.get("LUNCH_DECIDER_KEY_FILE", DEFAULT_KEY_FILE))
    try:
        for line in key_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def valid_request(data: object) -> tuple[dict, list[dict]]:
    if not isinstance(data, dict):
        raise ValueError("请求内容无效。")
    prefs, restaurants = data.get("preferences"), data.get("restaurants")
    if not isinstance(prefs, dict) or not isinstance(restaurants, list):
        raise ValueError("缺少用餐条件或餐厅清单。")
    if not 1 <= len(restaurants) <= MAX_CANDIDATES:
        raise ValueError(f"请提供 1 至 {MAX_CANDIDATES} 家符合条件的餐厅。")
    try:
        people = int(prefs["people"])
        min_budget = int(prefs["minBudget"])
        max_budget = int(prefs["maxBudget"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("用餐条件无效。") from None
    cuisine = prefs.get("cuisine", "")
    if not (1 <= people <= 100 and 5 <= min_budget < max_budget <= 150
            and isinstance(cuisine, str) and len(cuisine) <= 30):
        raise ValueError("用餐条件无效。")
    preferred_tag = prefs.get("preferredTag", "")
    if not isinstance(preferred_tag, str) or len(preferred_tag) > 30:
        raise ValueError("用餐偏好无效。")
    clean = []
    seen = set()
    for item in restaurants:
        if not isinstance(item, dict):
            raise ValueError("餐厅资料无效。")
        try:
            rid, name, kind = item["id"], item["name"], item["cuisine"]
            price = finite_number(item.get("price"))
            min_people = optional_number(item.get("minPeople"), 1, 100)
            max_people = optional_number(item.get("maxPeople"), 1, 100)
        except (KeyError, TypeError, ValueError):
            raise ValueError("餐厅资料无效。") from None
        dishes, notes = item.get("dishes", ""), item.get("notes", "")
        if not (isinstance(rid, str) and 1 <= len(rid) <= 80 and rid not in seen
                and isinstance(name, str) and 1 <= len(name.strip()) <= 60
                and isinstance(kind, str) and 1 <= len(kind.strip()) <= 30
                and isinstance(dishes, str) and len(dishes) <= 200
                and isinstance(notes, str) and len(notes) <= 300
                and price is not None and min_budget <= price <= max_budget
                and (min_people is None or min_people <= people)
                and (max_people is None or people <= max_people)):
            raise ValueError("餐厅资料与用餐条件不符。")
        seen.add(rid)
        clean.append({"id": rid, "name": name.strip(), "cuisine": kind.strip(), "price": price,
                      "minPeople": min_people, "maxPeople": max_people,
                      "dishes": dishes.strip(), "notes": notes.strip(),
                      "rating": optional_number(item.get("rating"), 0, 5),
                      "distance_m": optional_number(item.get("distance_m"), 0, 1_000_000)})
    user_prefs = {field: prefs.get(field) is True for field in SEMANTIC_FIELDS}
    tag_field = TAG_FIELDS.get(preferred_tag)
    if tag_field:
        user_prefs[tag_field] = True
    user_prefs.update({"people": people})
    return {"userPrefs": user_prefs, "people": people, "minBudget": min_budget, "maxBudget": max_budget,
            "cuisine": cuisine.strip(), "preferredTag": preferred_tag.strip()}, clean


def optional_number(value, low, high):
    number = finite_number(value)
    return number if number is not None and low <= number <= high else None


def request_jev(payload):
    key = api_key()
    if not key:
        raise RuntimeError("本地服务尚未配置 API Key。")
    request = Request(API_URL, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("API Key 无法使用，请检查 TypeSafe 账户和密钥。") from None
            if exc.code == 429:
                raise RuntimeError("Jev 请求过于频繁，请稍后重试。") from None
            if exc.code in (405, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            if exc.code == 405:
                raise RuntimeError("Jev 暂时无法完成推荐，请稍后重试。") from None
            raise RuntimeError(f"Jev 服务暂时不可用（HTTP {exc.code}）。") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < 2:
                time.sleep(1 + attempt * 2)
                continue
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, TimeoutError):
                raise RuntimeError("Jev 请求超时，请稍后重试。") from None
            raise RuntimeError("Jev 连接被中断，请稍后重试。") from None
        except (ValueError, json.JSONDecodeError):
            raise RuntimeError("Jev 返回了无法读取的结果，请重试。") from None


def choose(preferences, restaurants):
    user_prefs = preferences["userPrefs"]
    weights = build_weights(user_prefs)
    scores, detail = {}, {}
    model, used_jev = None, False
    # Large question sets can be disconnected upstream before Jev responds.
    # Keep each request to at most 15 model questions (and 20 restaurants).
    model_fields = sum(field not in ("rating", "distance") for field in weights)
    batch_size = min(20, max(1, 15 // model_fields)) if model_fields else 20
    batches = [restaurants[offset:offset + batch_size] for offset in range(0, len(restaurants), batch_size)]

    def evaluate_batch(batch):
        questions = build_questions(batch, user_prefs)
        answers = {}
        batch_model = None
        if questions:
            result = request_jev({"model": "jev-latest", "state": {"restaurants": {f"r{i}": r for i, r in enumerate(batch)}}, "questions": questions})
            answers = result.get("answers")
            if not isinstance(answers, dict):
                raise RuntimeError("Jev 返回了无法读取的结果，请重试。")
            batch_model = result.get("model", "jev-latest")
        batch_scores = []
        for index, restaurant in enumerate(batch):
            jev_scores = {}
            for field in weights:
                if field in ("rating", "distance"):
                    continue
                answer = answers.get(f"r{index}_{field}", {})
                if not isinstance(answer, dict):
                    raise RuntimeError("Jev 返回了无法读取的评分，请重试。")
                value = finite_number(answer.get("noul"))
                if value is None or not 0 <= value <= 1:
                    raise RuntimeError("Jev 返回了缺失或无效的评分，请重试。")
                jev_scores[field] = value
            batch_scores.append((restaurant["id"], calculate_score(restaurant, jev_scores, user_prefs), jev_scores))
        return batch_model, batch_scores

    with ThreadPoolExecutor(max_workers=2) as executor:
        for batch_model, batch_scores in executor.map(evaluate_batch, batches):
            if batch_model:
                model, used_jev = batch_model, True
            for rid, score, jev_scores in batch_scores:
                scores[rid] = score
                detail[rid] = jev_scores
    ranked_ids = sorted(scores, key=lambda rid: (-scores[rid], rid))
    return {"choiceId": ranked_ids[0], "rankedIds": ranked_ids[:15], "scores": scores,
            "weights": weights, "jevScores": detail, "source": "jev-weighted" if used_jev else "local-weighted", "model": model}


def load_dataset():
    data = json.loads((ROOT / "beichen_restaurants_2km_full.json").read_text(encoding="utf-8-sig"))
    records = data.get("restaurants")
    if not isinstance(records, list):
        raise ValueError("Invalid restaurant dataset")
    restaurants = []
    for row in records:
        if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
            continue
        tags = row.get("tags") or []
        notes = "; ".join(str(value) for value in (row.get("address"), row.get("area"), row.get("opening_hours")) if value)
        restaurants.append({"id": str(row["id"]), "name": str(row["name"]),
                            "cuisine": str(row.get("category") or "餐厅"),
                            "address": str(row.get("address") or ""),
                            "location": str(row.get("location") or ""),
                            "price": optional_number(row.get("average_cost_yuan"), 0, 10000),
                            "rating": optional_number(row.get("rating"), 0, 5),
                            "distance_m": optional_number(row.get("distance_m"), 0, 1_000_000),
                            "minPeople": None, "maxPeople": None,
                            "dishes": "、".join(str(tag) for tag in tags)[:200],
                            "notes": notes[:300], "photo_url": str(row.get("photo_url") or "")})
    return {"center": data.get("center"), "restaurants": restaurants}

class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/restaurants":
            try:
                self.send_json(200, load_dataset())
            except (OSError, ValueError, TypeError):
                self.send_json(500, {"error": "餐厅数据暂时无法读取。"})
            return
        paths = {"/": ROOT / "index.html", "/index.html": ROOT / "index.html",
                 "/styles.css": ROOT / "styles.css", "/shared.js": ROOT / "shared.js",
                 "/home.js": ROOT / "home.js",
                 "/pile-physics.js": ROOT / "pile-physics.js",
                 "/vendor/matter.min.js": ROOT / "vendor" / "matter.min.js",
                 "/assets/lunch-doodle.png": ROOT / "assets" / "lunch-doodle.png",
                 "/assets/lunch-table.png": ROOT / "assets" / "lunch-table.png",
                 "/assets/brand-icon.svg": ROOT / "assets" / "brand-icon.svg",
                 "/assets/brand-name.svg": ROOT / "assets" / "brand-name.svg",
                 "/assets/rating-star.svg": ROOT / "assets" / "rating-star.svg"}
        path = paths.get(self.path)
        if path is None or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        mime = {".png": "image/png", ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".html": "text/html; charset=utf-8"}
        self.send_header("Content-Type", mime[path.suffix])
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if self.path != "/api/choose":
            self.send_error(404)
            return
        origin = self.headers.get("Origin", "")
        request_host = self.headers.get("Host", "")
        allowed_origins = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", f"http://{HOST}:{PORT}"}
        if HOST == "0.0.0.0" and request_host.endswith(f":{PORT}"):
            try:
                host_ip = ipaddress.ip_address(request_host.rsplit(":", 1)[0])
                if host_ip.is_private or host_ip.is_loopback:
                    allowed_origins.add(f"http://{request_host}")
            except ValueError:
                pass
        # Vercel terminates HTTPS before forwarding to the Python function.
        if os.environ.get("VERCEL") == "1" and request_host:
            allowed_origins.add(f"https://{request_host}")
        if origin and origin not in allowed_origins:
            self.send_json(403, {"error": "请求来源无效。"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_json(415, {"error": "请求格式无效。"})
            return
        client_ip = self.client_address[0]
        now = time.monotonic()
        with REQUEST_LOCK:
            recent = [stamp for stamp in REQUEST_TIMES.get(client_ip, []) if now - stamp < 3600]
            if len(recent) >= 30:
                self.send_json(429, {"error": "请求次数较多，请一小时后再试。"})
                return
            recent.append(now)
            REQUEST_TIMES[client_ip] = recent
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= MAX_BODY:
                raise ValueError("请求内容过大或为空。")
            data = json.loads(self.rfile.read(length))
            preferences, restaurants = valid_request(data)
            result = choose(preferences, restaurants)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
            return
        except RuntimeError as exc:
            self.send_json(502, {"error": str(exc)})
            return
        self.send_json(200, result)

    def log_message(self, format: str, *args: object) -> None:
        # Avoid logging request data or credentials in a local terminal.
        pass


if __name__ == "__main__":
    print(f"午饭网页已启动：http://{HOST}:{PORT}/", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
