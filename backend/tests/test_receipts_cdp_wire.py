"""The CDP wire format, against a server that answers like Chrome does.

`HttpWsCdp` is the one part of the browser path that talks to something
outside this codebase, and the fake in `test_receipts_browser` replaces
it wholesale. So the calls themselves — the verbs, the endpoints, the
message shape — were never exercised until a deployment tried them.

This closes most of it. The server below is not a mock of our client; it
answers the way Chrome 149 was observed to answer, including the rule
that cost a day: a request whose `Host` is neither localhost nor an IP
is refused. What it cannot check is that `/json/new` needs a PUT — the
upgrade-oriented server here never sees the method — so that one is
still only asserted by the deployment that works.
"""
import json

import pytest
from websockets.asyncio.server import serve

from app.receipts.browser import HttpWsCdp

TAB = "TAB-1"
HTML = "<html><body>nota</body></html>"


def _host_is_allowed(headers) -> bool:
    """Chrome's own rule: localhost or an IP, nothing else."""
    host = (headers.get("Host") or "").split(":")[0]
    return host == "localhost" or host.replace(".", "").isdigit()


async def _handler(websocket):
    async for raw in websocket:
        message = json.loads(raw)
        assert message["method"] == "Runtime.evaluate"
        assert message["params"]["returnByValue"] is True
        expression = message["params"]["expression"]
        value = (
            json.dumps({"url": "https://portal/x", "state": "complete", "body": len(HTML)})
            if "readyState" in expression
            else HTML
        )
        await websocket.send(
            json.dumps({"id": message["id"], "result": {"result": {"value": value}}})
        )


def _process_request(connection, request):
    """Everything that is not the WebSocket upgrade, plus the host check
    that applies to all of it."""
    if not _host_is_allowed(request.headers):
        return connection.respond(421, "wrong host\n")
    path = request.path.split("?")[0]
    if path.startswith("/devtools/page/"):
        return None  # let the upgrade proceed
    if path == "/json/new":
        return connection.respond(200, json.dumps({"id": TAB, "type": "page"}))
    if path == "/json/list":
        return connection.respond(
            200,
            json.dumps([
                {"id": TAB, "webSocketDebuggerUrl": f"ws://localhost/devtools/page/{TAB}"}
            ]),
        )
    if path.startswith("/json/close/"):
        return connection.respond(200, "Target is closing")
    return connection.respond(404, "not found\n")


@pytest.mark.asyncio
async def test_the_three_calls_work_against_chrome_s_own_answers():
    async with serve(_handler, "127.0.0.1", 0, process_request=_process_request) as server:
        port = server.sockets[0].getsockname()[1]
        cdp = HttpWsCdp(f"http://127.0.0.1:{port}", timeout_seconds=5)

        target_id = await cdp.open_tab("https://consultadfe.fazenda.rj.gov.br/x")
        assert target_id == TAB

        assert json.loads(await cdp.evaluate(target_id, "document.readyState"))["state"] == "complete"
        assert await cdp.evaluate(target_id, "document.documentElement.outerHTML") == HTML

        await cdp.close_tab(target_id)


@pytest.mark.asyncio
async def test_a_request_chrome_would_drop_is_never_sent():
    """The client's Host is what gets it past the door. Without the
    override the same calls are refused — which is exactly what a raw
    request against the deployed browser did."""
    async with serve(_handler, "127.0.0.1", 0, process_request=_process_request) as server:
        port = server.sockets[0].getsockname()[1]
        cdp = HttpWsCdp(f"http://127.0.0.1:{port}", timeout_seconds=5)

        import httpx

        # What a request arriving through the forwarder looks like: the
        # Host is the forwarder's name, and a name is what Chrome refuses.
        async with httpx.AsyncClient(timeout=5, headers={"Host": "kasm-chrome:9223"}) as raw:
            refused = await raw.put(f"http://127.0.0.1:{port}/json/new", params={"url": "x"})
        assert refused.status_code == 421

        assert await cdp.open_tab("https://x") == TAB
