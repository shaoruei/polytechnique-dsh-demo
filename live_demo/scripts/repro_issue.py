"""Reproduce the reported bug from the issue text (NOT the benchmark test).

Uses the issue's own view and URL pattern and sends GET through Django's real
ASGI request handler (django.test.AsyncClient).  Run from anywhere with the
workspace interpreter:
    ~/dsh-live/venv/bin/python live_demo/scripts/repro_issue.py
Before a fix: exit 1, "BUG REPRODUCED: ... can't be used in 'await' expression".
After a fix:  exit 0, "GET /demo -> 405 Method Not Allowed".
"""
import asyncio
import logging

from django.conf import settings

settings.configure(
    DEBUG=False,
    ALLOWED_HOSTS=["*"],
    ROOT_URLCONF=__name__,
    MIDDLEWARE=[],
    LOGGING_CONFIG=None,
)
logging.disable(logging.CRITICAL)  # keep the demo output to one line

import django  # noqa: E402

django.setup()

from django.http import HttpResponse  # noqa: E402
from django.test import AsyncClient  # noqa: E402
from django.urls import path  # noqa: E402
from django.views import View  # noqa: E402


class Demo(View):
    """This basic view supports only POST requests"""

    async def post(self, request):
        return HttpResponse("ok")


urlpatterns = [path("demo", Demo.as_view())]


async def main():
    client = AsyncClient(raise_request_exception=True)
    return await client.get("/demo")


try:
    resp = asyncio.run(main())
except TypeError as exc:
    print(f"BUG REPRODUCED: TypeError: {exc}")
    raise SystemExit(1)
print(f"GET /demo -> {resp.status_code} {resp.reason_phrase}; Allow: {resp.get('Allow')}")
post = asyncio.run(AsyncClient().post("/demo"))
print(f"POST /demo -> {post.status_code} {post.content.decode()}")
