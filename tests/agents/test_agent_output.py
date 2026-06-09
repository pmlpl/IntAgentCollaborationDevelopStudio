import json

from agents.agent_output import normalize_opencode_capture, opencode_capture_argv
from core.dispatch.decompose import MARKER, parse_manager_output


def test_opencode_capture_argv():
    argv = ["opencode", "run", "hello task"]
    assert opencode_capture_argv(argv) == [
        "opencode",
        "run",
        "--format",
        "json",
        "hello task",
    ]


def test_opencode_capture_argv_node_resolved():
    argv = ["node.exe", "opencode.js", "run", "hello task"]
    assert opencode_capture_argv(argv) == [
        "node.exe",
        "opencode.js",
        "run",
        "--format",
        "json",
        "hello task",
    ]


def test_normalize_opencode_capture_ndjson():
    raw = '\n'.join(
        [
            '{"type":"text","part":{"text":"分工说明\\n"}}',
            '{"type":"text","part":{"text":"' + MARKER + '"}}',
            '{"type":"text","part":{"text":"[{\\"assignee\\":\\"a\\",\\"description\\":\\"d\\",\\"waits_on\\":[]}]"}}',
        ]
    )
    text = normalize_opencode_capture(raw)
    subs = parse_manager_output(text)
    assert subs[0]["assignee"] == "a"


def test_parse_loose_subtask_objects_without_marker():
    body = (
        "好的，分工如下。\n"
        '{"assignee":"xiaohong","description":"前端页面","waits_on":[]}\n'
        '{"assignee":"dazhuang","description":"后端 API","waits_on":["xiaohong"]}'
    )
    subs = parse_manager_output(body)
    assert len(subs) == 2
    assert subs[1]["waits_on"] == ["xiaohong"]
