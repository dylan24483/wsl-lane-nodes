"""Execute the embedded :8766 dashboard JavaScript against mocked fetch."""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_SOURCE = REPO_ROOT / "server" / "lane_node_server.py"


def _display_html():
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
                isinstance(target, ast.Name)
                and target.id == "DISPLAY_HTML"
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("DISPLAY_HTML assignment not found")


def _script():
    match = re.search(
        r"<script>(.*?)</script>", _display_html(), re.DOTALL)
    assert match is not None
    return match.group(1)


def _run_js(*, actions, scoring=None, responses=None, prompt="TEST",
            confirm=True):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for embedded-dashboard JS tests")
    configuration = {
        "actions": actions,
        "scoring": list(scoring or []),
        "responses": list(responses or []),
        "prompt": prompt,
        "confirm": confirm,
    }
    runner = f"""
const vm = require('vm');
const configuration = {json.dumps(configuration)};
const calls = [];
const messages = [];
const storage = new Map();
function response(status, body) {{
  return {{ok: status >= 200 && status < 300, status,
           json: async () => body}};
}}
const context = {{
  console,
  crypto: {{randomUUID: () => '11111111-2222-4333-8444-555555555555'}},
  fetch: async (url, options = {{}}) => {{
    calls.push({{url, options}});
    if (url.endsWith('/scoring')) {{
      const body = configuration.scoring.shift();
      return response(body && body._status || 200, body);
    }}
    if (url === '/api/state') return response(200, {{}});
    const item = configuration.responses.shift() ||
      {{status: 200, body: {{ok: true}}}};
    return response(item.status, item.body);
  }},
  localStorage: {{
    getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  }},
  window: {{
    prompt: () => configuration.prompt,
    confirm: () => configuration.confirm,
    addEventListener: () => {{}},
  }},
  document: {{
    getElementById: () => ({{
      textContent: '',
      classList: {{add: () => {{}}, remove: () => {{}}}},
    }}),
  }},
  setInterval: () => 0,
  setTimeout: () => 0,
}};
vm.createContext(context);
void (async () => {{
  vm.runInContext({json.dumps(_script())}, context);
  for (const item of configuration.actions) {{
    await context.action(item.lane, item.op);
  }}
  await new Promise(resolve => setImmediate(resolve));
  process.stdout.write(JSON.stringify({{
    calls,
    storage: Object.fromEntries(storage),
  }}));
}})().catch(error => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-"], input=runner, text=True,
        capture_output=True, cwd=REPO_ROOT, timeout=20)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _post_calls(result):
    return [
        call for call in result["calls"]
        if call["options"].get("method") == "POST"]


def test_closed_open_derives_next_generation_and_prompts_roster():
    result = _run_js(
        actions=[{"lane": 21, "op": "open"}],
        scoring=[{
            "ok": True,
            "open": False,
            "retired_session_generation": 4,
            "players": [],
        }],
        responses=[{"status": 200, "body": {"ok": True}}],
        prompt="ALICE, BOB")
    posts = _post_calls(result)
    assert len(posts) == 1
    assert posts[0]["url"] == "/api/lane/21/open"
    assert posts[0]["options"]["headers"] == {
        "Content-Type": "application/json"}
    assert json.loads(posts[0]["options"]["body"]) == {
        "bowlers": ["ALICE", "BOB"],
        "send_open_command": True,
        "session_generation": 5,
    }


def test_active_open_replays_exact_generation_and_visible_roster():
    result = _run_js(
        actions=[{"lane": 21, "op": "open"}],
        scoring=[{
            "ok": True,
            "open": True,
            "mode": "single_lane",
            "session_generation": 7,
            "players": [{"name": "ALICE"}, {"name": "BOB"}],
        }],
        responses=[{"status": 200, "body": {"ok": True}}],
        prompt="MUST NOT BE USED")
    post = _post_calls(result)[0]
    assert json.loads(post["options"]["body"]) == {
        "bowlers": ["ALICE", "BOB"],
        "send_open_command": True,
        "session_generation": 7,
    }


def test_close_uses_active_or_retired_generation():
    active = _run_js(
        actions=[{"lane": 21, "op": "close"}],
        scoring=[{
            "ok": True, "open": True, "session_generation": 9}],
        responses=[{"status": 200, "body": {"ok": True}}])
    assert json.loads(
        _post_calls(active)[0]["options"]["body"]
    ) == {"session_generation": 9}

    retired = _run_js(
        actions=[{"lane": 21, "op": "close"}],
        scoring=[{
            "ok": True, "open": False,
            "retired_session_generation": 9}],
        responses=[{"status": 200, "body": {
            "ok": True, "replayed": True}}])
    assert json.loads(
        _post_calls(retired)[0]["options"]["body"]
    ) == {"session_generation": 9}


def test_reset_power_retry_reuses_stable_operation_identity():
    result = _run_js(
        actions=[
            {"lane": 22, "op": "power-off"},
            {"lane": 22, "op": "power-off"},
        ],
        responses=[
            {"status": 503, "body": {
                "ok": False, "reconciliation_required": True}},
            {"status": 200, "body": {"ok": True}},
        ])
    posts = _post_calls(result)
    assert len(posts) == 2
    first = posts[0]["options"]["headers"]
    second = posts[1]["options"]["headers"]
    assert first["X-Operation-Key"] == second["X-Operation-Key"]
    assert (first["X-Operation-Issued-At"]
            == second["X-Operation-Issued-At"])
    assert first["X-Operation-Key"].startswith(
        "bench-ui:22:power-off:")
    assert result["storage"] == {}


def test_cross_lane_open_and_trigger_are_explicitly_unsupported():
    cross = _run_js(
        actions=[{"lane": 21, "op": "open"}],
        scoring=[{
            "ok": True,
            "open": True,
            "mode": "cross_lane",
            "cross_lane": True,
            "session_generation": 1,
            "players": [{"name": "ALICE"}],
        }])
    assert _post_calls(cross) == []

    trigger = _run_js(
        actions=[{"lane": 21, "op": "trigger-ball"}])
    assert trigger["calls"] == []
    html = _display_html()
    assert html.count('class="trigger-ball" disabled') == 2
    assert "onclick=\"action(21, 'trigger-ball')\"" not in html
    assert "onclick=\"action(22, 'trigger-ball')\"" not in html
