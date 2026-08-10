"""One function per fn2 endpoint. No printing, no argparse — just the contract.

Mirrors ``/api/v1`` on the fn2 backend:

    agents      POST/GET/PATCH/DELETE /agents[/<id>]
    runs        POST /agents/<id>/run, GET /agents/<id>/runs[/<run_id>]
    account     GET /usage, GET /models
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import Client

_V1 = "/api/v1"


# -- agents --------------------------------------------------------------
def list_agents(client: Client, *, status: Optional[str] = None,
                limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    return client.get(f"{_V1}/agents",
                      params={"status": status, "limit": limit, "offset": offset})


def get_agent(client: Client, agent_id: str) -> Dict[str, Any]:
    return client.get(f"{_V1}/agents/{agent_id}")


def create_agent(client: Client, *, prompt: str, name: Optional[str] = None,
                 model: Optional[str] = None, labels: Optional[List[str]] = None,
                 schedule: Optional[Dict[str, Any]] = None,
                 email: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"prompt": prompt}
    if name:
        body["name"] = name
    if model:
        body["model"] = model
    if labels:
        body["labels"] = labels
    if schedule:
        body["schedule"] = schedule
    if email:
        # Deliver each completed run to the account's OWN verified email. The
        # server resolves the recipient + honors opt-out; no address is sent.
        body["delivery"] = {"email": True}
    return client.post(f"{_V1}/agents", body=body)


def update_agent(client: Client, agent_id: str, **fields: Any) -> Dict[str, Any]:
    body = {k: v for k, v in fields.items() if v is not None}
    return client.patch(f"{_V1}/agents/{agent_id}", body=body)


def delete_agent(client: Client, agent_id: str) -> None:
    client.delete(f"{_V1}/agents/{agent_id}")


# -- runs ----------------------------------------------------------------
def run_agent(client: Client, agent_id: str) -> Dict[str, Any]:
    return client.post(f"{_V1}/agents/{agent_id}/run")


def list_runs(client: Client, agent_id: str, *, limit: int = 20,
              offset: int = 0, wait: Optional[int] = None) -> Dict[str, Any]:
    # `wait` long-polls server-side (0-25s) for the first run to appear, which
    # beats hammering the endpoint from a client loop.
    return client.get(f"{_V1}/agents/{agent_id}/runs",
                      params={"limit": limit, "offset": offset, "wait": wait})


def get_run(client: Client, agent_id: str, run_id: str, *,
            wait: Optional[int] = None) -> Dict[str, Any]:
    """`wait` (0-25s) long-polls until the run is terminal or the deadline passes."""
    return client.get(f"{_V1}/agents/{agent_id}/runs/{run_id}",
                      params={"wait": wait})


# -- account -------------------------------------------------------------
def usage(client: Client) -> Dict[str, Any]:
    return client.get(f"{_V1}/usage")


def list_models(client: Client) -> Any:
    return client.get(f"{_V1}/models")
