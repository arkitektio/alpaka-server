"""A fake api.typesafe.ai for alpaka's test suite.

Speaks the systemone wire protocol the way the hosted service does where it
differs from a local Ollaya: a bearer key is required, ``jev-latest`` is an
alias the response resolves to ``jev-1.13.0``, a score takes 2-10 levels, and it
answers 429 / 529 under load. Answers are deterministic so tests can assert
them: a noul is 0.9, a choice picks its first option, a score its last level.

* ``POST /_admin/fail``   ``{"status": 529, "times": 2}``: answer the next N systemone calls with that status
* ``POST /_admin/reset``  forget failures and the log
* ``GET  /_admin/log``    every systemone request body, with its Authorization header
* ``GET  /_admin/health``
"""

from aiohttp import web

API_KEY = "ts-test-key"
MODELS = [
    {"name": "jev-1.13.0", "description": "Jev 1.13", "release_date": "2026-09-15"},
    {"name": "jev-latest", "description": "Alias of jev-1.13.0", "release_date": "2026-09-15"},
]
ALIASES = {"jev-latest": "jev-1.13.0", "jev-1.13.0": "jev-1.13.0"}
STATE: dict = {"fail": None, "log": []}


def _unauthorized(request: web.Request):
    if request.headers.get("Authorization") != f"Bearer {API_KEY}":
        return web.json_response({"error": "Invalid API key", "code": "UNAUTHORIZED"}, status=401)
    return None


def _invalid(loc: list, msg: str) -> web.Response:
    return web.json_response({"error": f"{'.'.join(map(str, loc))}: {msg}", "code": "INVALID_REQUEST", "detail": [{"loc": ["body", *loc], "msg": msg, "type": "value_error"}]}, status=422)


def _answer(question: dict) -> dict:
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": 0.9}
    if kind == "choice":
        options = list(question["criteria"])
        rest = 0.2 / max(len(options) - 1, 1)
        probabilities = {option: (0.8 if i == 0 else rest) for i, option in enumerate(options)}
        return {"type": "choice", "choice": options[0], "confidence": 0.8, "probabilities": probabilities}
    levels = question["criteria"]
    top = len(levels) - 1
    probabilities = {str(i): (0.7 if i == top else 0.3 / top) for i in range(len(levels))}
    score = sum(i * p for i, p in enumerate(probabilities.values()))
    return {"type": "score", "score": round(score, 4), "confidence": 0.7, "legend": {str(i): level for i, level in enumerate(levels)}, "probabilities": probabilities}


async def systemone(request: web.Request) -> web.Response:
    body = await request.json()
    STATE["log"].append({"body": body, "authorization": request.headers.get("Authorization")})
    if (denied := _unauthorized(request)) is not None:
        return denied

    fail = STATE["fail"]
    if fail and fail["times"] > 0:
        fail["times"] -= 1
        return web.json_response({"error": "Service overloaded", "code": "OVERLOADED"}, status=fail["status"], headers={"Retry-After": "0"})

    for field in ("model", "state", "questions"):
        if field not in body:
            return _invalid([field], "Field required")
    model = ALIASES.get(body["model"])
    if model is None:
        return web.json_response({"error": f"model {body['model']!r} not found", "code": "MODEL_NOT_FOUND"}, status=404)
    questions = body["questions"]
    if not questions:
        return _invalid(["questions"], "At least one question is required")

    answers, words = {}, len(str(body["state"]).split())
    for key, question in questions.items():
        kind = question.get("type")
        if kind not in ("noul", "choice", "score"):
            return _invalid(["questions", key, "type"], "Input tag does not match any of the expected tags: 'noul', 'choice', 'score'")
        if kind == "choice" and not 1 <= len(question.get("criteria") or {}) <= 255:
            return _invalid(["questions", key, "choice", "criteria"], "A choice takes 1 to 255 options")
        if kind == "score" and not 2 <= len(question.get("criteria") or []) <= 10:
            return _invalid(["questions", key, "score", "criteria"], "A score takes 2 to 10 levels")
        answers[key] = _answer(question)
        words += len(str(question.get("instructions", "")).split())

    return web.json_response({"model": model, "answers": answers, "usage": {"input_tokens": 10 * words, "output_tokens": len(answers)}})


async def models(request: web.Request) -> web.Response:
    if (denied := _unauthorized(request)) is not None:
        return denied
    return web.json_response({"models": MODELS})


async def admin_fail(request: web.Request) -> web.Response:
    body = await request.json()
    STATE["fail"] = {"status": int(body["status"]), "times": int(body.get("times", 1))}
    return web.json_response({"ok": True})


async def admin_reset(request: web.Request) -> web.Response:
    STATE["fail"] = None
    STATE["log"].clear()
    return web.json_response({"ok": True})


async def admin_log(request: web.Request) -> web.Response:
    return web.json_response(STATE["log"])


async def admin_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


app = web.Application()
app.add_routes(
    [
        web.post("/v1/systemone", systemone),
        web.get("/v1/models", models),
        web.post("/_admin/fail", admin_fail),
        web.post("/_admin/reset", admin_reset),
        web.get("/_admin/log", admin_log),
        web.get("/_admin/health", admin_health),
    ]
)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8000)
