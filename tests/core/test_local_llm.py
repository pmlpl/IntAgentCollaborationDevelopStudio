import json
from unittest.mock import MagicMock, patch

from core.research.local_llm import (
    lmstudio_available,
    local_llm_available,
    ollama_available,
    run_lmstudio_prompt_capture,
    run_ollama_prompt_capture,
)


@patch("core.research.local_llm._http_json")
def test_lmstudio_available_ok(mock_http):
    mock_http.return_value = (0, {"data": []})
    assert lmstudio_available() is True


@patch("core.research.local_llm._http_json")
def test_run_lmstudio_prompt_capture(mock_http):
    mock_http.return_value = (
        0,
        {
            "choices": [
                {
                    "message": {
                        "content": "ok\n---STUDIO_RESEARCH_JSON---\n"
                        '{"technologies":["Pygame"],"summary":"适合小游戏"}'
                    }
                }
            ]
        },
    )
    rc, out = run_lmstudio_prompt_capture("分析贪吃蛇")
    assert rc == 0
    assert "STUDIO_RESEARCH_JSON" in out


@patch("core.research.local_llm.urllib.request.urlopen")
def test_ollama_available_ok(mock_urlopen):
    mock_urlopen.return_value.__enter__.return_value.status = 200
    assert ollama_available() is True


@patch("core.research.local_llm.urllib.request.urlopen")
def test_run_ollama_prompt_capture(mock_urlopen):
    payload = {
        "message": {
            "content": "ok\n---STUDIO_RESEARCH_JSON---\n"
            '{"technologies":["Pygame"],"summary":"适合小游戏"}'
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    rc, out = run_ollama_prompt_capture("分析贪吃蛇")
    assert rc == 0
    assert "STUDIO_RESEARCH_JSON" in out


def test_local_llm_available_unknown_mode():
    assert local_llm_available("unknown") is False
