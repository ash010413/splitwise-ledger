"""Provider adapter: no outbound expense mutations."""

from datetime import UTC, datetime, timedelta

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client

from .domain import normalize_expense

AUTHORIZE_URL = "https://secure.splitwise.com/oauth/authorize"
TOKEN_URL = "https://secure.splitwise.com/oauth/token"
API_URL = "https://secure.splitwise.com/api/v3.0/"


class SplitwiseClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def oauth(self):
        return AsyncOAuth2Client(
            self.client_id,
            self.client_secret,
            redirect_uri=self.redirect_uri,
            token_endpoint_auth_method="client_secret_post",
            timeout=30,
        )

    async def authorize_url(self, state: str) -> str:
        async with self.oauth() as client:
            url, _ = client.create_authorization_url(AUTHORIZE_URL, state=state)
            return url

    async def exchange(self, code: str) -> dict:
        async with self.oauth() as client:
            return dict(await client.fetch_token(TOKEN_URL, code=code))

    async def current_user(self, token: dict) -> int:
        return (await self.current_profile(token))["user_id"]

    async def current_profile(self, token: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            data = await self._get(client, "get_current_user", token)
        user = data["user"]
        return {
            "user_id": int(user["id"]),
            "name": " ".join(
                str(user.get(k) or "").strip() for k in ("first_name", "last_name")
            ).strip(),
            "email": str(user.get("email") or ""),
        }

    async def groups(self, token: dict) -> dict[str, str]:
        """Retain titles only; discard member identities, balances and invite links."""
        async with httpx.AsyncClient(timeout=30) as client:
            data = await self._get(client, "get_groups", token)
        return {
            str(int(group["id"])): str(group["name"]).strip()[:160]
            for group in data["groups"]
            if int(group["id"]) > 0 and isinstance(group.get("name"), str)
        }

    @staticmethod
    async def _get(client, endpoint, token, params=None):
        response = await client.get(
            API_URL + endpoint,
            headers={"Authorization": "Bearer " + token["access_token"]},
            params=params,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            raise ValueError("Splitwise returned provider errors")
        return data

    async def fetch(self, token: dict, user_id: int, cursor: str | None):
        end = datetime.now(UTC)
        params = {"limit": 100, "offset": 0, "updated_before": end.isoformat()}
        if cursor:
            params["updated_after"] = (
                datetime.fromisoformat(cursor) - timedelta(minutes=5)
            ).isoformat()
        records = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(1000):
                page = await self._get(client, "get_expenses", token, params)
                for raw in page["expenses"]:
                    record = normalize_expense(raw, user_id)
                    records[record["id"]] = record
                if not page["expenses"]:
                    return list(records.values()), end.isoformat()
                params["offset"] += len(page["expenses"])
        raise ValueError("Pagination safety limit reached; sync cursor was not advanced")
