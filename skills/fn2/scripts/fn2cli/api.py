"""One function per fn2 endpoint. No printing, no argparse — just the contract.

Mirrors ``/api/v1`` on the fn2 backend:

    agents      POST/GET/PATCH/DELETE /agents[/<id>]
    runs        POST /agents/<id>/run, GET /agents/<id>/runs[/<run_id>]
    account     GET /usage, GET /models
    research    GET /research/{earnings,transcripts,transcripts/read,
                transcripts/search,financials,prices,fred,recall}

The research routes are read-only, need the ``research`` scope, and draw on
the account's weekly research-request allowance (only a 2xx spends it).
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


# -- research (read-only; scope `research`) -------------------------------
# Optional arguments left as None are omitted from the query string, so the
# server's own defaults apply and are never duplicated here.
def earnings(client: Client, symbol: str, *,
             limit: Optional[int] = None) -> Dict[str, Any]:
    """Reported quarters vs analyst consensus, newest first, + the next report."""
    return client.get(f"{_V1}/research/earnings",
                      params={"symbol": symbol, "limit": limit})


def list_transcripts(client: Client, symbol: str, *,
                     limit: Optional[int] = None) -> Dict[str, Any]:
    """The earnings calls FN2 holds for a ticker, newest first."""
    return client.get(f"{_V1}/research/transcripts",
                      params={"symbol": symbol, "limit": limit})


def read_transcript(client: Client, *, symbol: Optional[str] = None,
                    fiscal_year: Optional[int] = None,
                    fiscal_quarter: Optional[int] = None,
                    transcript_id: Optional[str] = None,
                    offset: Optional[int] = None,
                    max_chars: Optional[int] = None) -> Dict[str, Any]:
    """One page of a call's text in speaker order. `symbol` alone reads the
    most recent call; pages chain through the response's `next_offset`."""
    return client.get(f"{_V1}/research/transcripts/read",
                      params={"symbol": symbol, "fiscal_year": fiscal_year,
                              "fiscal_quarter": fiscal_quarter,
                              "transcript_id": transcript_id,
                              "offset": offset, "max_chars": max_chars})


def search_transcripts(client: Client, query: str, *,
                       symbol: Optional[str] = None,
                       after: Optional[str] = None,
                       transcript_id: Optional[str] = None,
                       limit: Optional[int] = None) -> Dict[str, Any]:
    """Relevance-ranked speaker turns; `transcript_id` restricts to one call."""
    return client.get(f"{_V1}/research/transcripts/search",
                      params={"query": query, "symbol": symbol, "after": after,
                              "transcript_id": transcript_id, "limit": limit})


def financials(client: Client, symbol: str, *, variant: Optional[str] = None,
               limit: Optional[int] = None) -> Dict[str, Any]:
    """SEC-filing-derived periods; `variant` is annual | quarterly | ttm."""
    return client.get(f"{_V1}/research/financials",
                      params={"symbol": symbol, "variant": variant,
                              "limit": limit})


def prices(client: Client, symbol: str, *,
           history_range: Optional[str] = None) -> Dict[str, Any]:
    """Quote snapshot, plus a price series when a range is given."""
    return client.get(f"{_V1}/research/prices",
                      params={"symbol": symbol, "range": history_range})


def fred(client: Client, series_id: Optional[str] = None, *,
         limit: Optional[int] = None) -> Dict[str, Any]:
    """Observations for one FRED series, or the catalog when none is named."""
    return client.get(f"{_V1}/research/fred",
                      params={"series_id": series_id, "limit": limit})


def recall(client: Client, *, query: Optional[str] = None,
           agent_id: Optional[str] = None, tag: Optional[str] = None,
           limit: Optional[int] = None) -> Dict[str, Any]:
    """The account's own saved memory (what its agents stored)."""
    return client.get(f"{_V1}/research/recall",
                      params={"query": query, "agent_id": agent_id,
                              "tag": tag, "limit": limit})
