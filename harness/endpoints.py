"""Endpoint registry: which Token Factory deployment a run talks to. Explicit, never inferred.

Each endpoint has an `origin` (scheme://host the relay forwards to) and a `model` (the exact model id
or dedicated routing key sent in every request). The relay refuses any chat request whose model
differs, and it records the `model` field of every response, so each saved request can be checked
against the endpoint it is labelled with (`endpoint_verified`).

Dedicated `ecole-demo` (4x H100, eu-north1). The routing key comes from the Token Factory control
plane (GET /v0/dedicated_endpoints, saved in data/provenance/dedicated_endpoint_2026-11-02.json).
The documented regional base URL https://api.tokenfactory.eu-north1.nebius.com/v1 answers 401
"token is not present" from this cloud session: the Network Secret is configured only for
api.tokenfactory.nebius.com. The global API host serves the same routing key with that credential,
so dedicated traffic uses the global host. Override with TOFA_DEDICATED_ORIGIN when a credential
for the regional host is configured.
"""

import os

ENDPOINTS = {
    "public": {
        "name": "public",
        "label": "Public serverless endpoint",
        "origin": os.environ.get("TOFA_PUBLIC_ORIGIN", "https://api.tokenfactory.nebius.com"),
        "model": "openai/gpt-oss-120b",
        "billing": "per token",
    },
    "dedicated": {
        "name": "dedicated",
        "label": "Dedicated endpoint ecole-demo (4x H100, 1 replica, eu-north1)",
        "origin": os.environ.get("TOFA_DEDICATED_ORIGIN", "https://api.tokenfactory.nebius.com"),
        "regional_origin": "https://api.tokenfactory.eu-north1.nebius.com",
        "model": os.environ.get("TOFA_DEDICATED_MODEL", "dedicated/openai/gpt-oss-120b-ZkdOyl"),
        "endpoint_id": "3456b982-6f35-4a9e-b4bc-965baf020995",
        "billing": "per GPU-hour ($18.80/h for 4x H100)",
    },
}


def get_endpoint(name: str) -> dict:
    if name not in ENDPOINTS:
        raise SystemExit(f"unknown endpoint {name!r}; choose from {sorted(ENDPOINTS)}")
    return dict(ENDPOINTS[name])
