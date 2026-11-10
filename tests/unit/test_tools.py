import tools
from tools import read, list_files, write
from unittest.mock import patch, AsyncMock, Mock
import pytest
import httpx


@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_updates_file_correctly_when_sha_is_provided(
    mocked_client_get, mocked_client_put
):

    mocked_client_get.return_value = Mock()

    mocked_client_put.return_value = Mock()

    mocked_client_get.return_value.json.return_value = {"sha": 123}
    mocked_client_put.return_value.json.return_value = {
        "content": {"path": "test_file.md"}
    }

    result = await write.ainvoke(
        {
            "path": "Base de conhecimento/test_file.md",
            "content": "content for the update path",
            "commit_message": "update existing file",
        }
    )
    assert result == "test_file.md"
    assert mocked_client_put.call_args.kwargs["json"]["sha"] == "123"


@pytest.mark.asyncio
@patch("tools.client.put", new_callable=AsyncMock)
@patch("tools.client.get", new_callable=AsyncMock)
async def test_write_tool_creates_new_file_correctly_when_no_sha_is_provided(
    mocked_client_get, mocked_client_put
):

    request = Mock()
    response = Mock(status_code=404)

    mocked_client_get.return_value = Mock()
    mocked_client_put.return_value = Mock()
    mocked_client_get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "any message", request=request, response=response
    )
    mocked_client_put.return_value.json.return_value = {
        "content": {"path": "test_file.md"}
    }

    result = await write.ainvoke(
        {
            "path": "Base de conhecimento/test_file.md",
            "content": "content for the create path",
            "commit_message": "create new file",
        }
    )
    assert result == "test_file.md"
    assert mocked_client_put.call_args.kwargs["json"]["message"] == "create new file"


# ---- safe_path: the path comes from the model and goes into the GitHub URL ----


@pytest.fixture
def requests_sent(monkeypatch):
    """Swap the module's HTTP client for one that only records method + URL (no network)."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, str(request.url)))
        if request.method == "PUT":
            return httpx.Response(201, json={"content": {"path": "x"}})
        # what GitHub answers when write looks up the sha of a file that does not exist yet
        if request.url.path.endswith("new-file.md"):
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=[], request=request)

    monkeypatch.setattr(
        tools, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(tools, "owner", "OWNER")
    monkeypatch.setattr(tools, "repo", "REPO")
    return sent


CONTENTS = "https://api.github.com/repos/OWNER/REPO/contents"
WRITE_ARGS = {"content": "a", "commit_message": "m"}

PATHS_THAT_MUST_NOT_REACH_GITHUB = [
    (read, {"path": "../../../OTHER/REPO/contents/secret.md"}),
    (read, {"path": "../../../../user/repos"}),
    (read, {"path": "../actions/secrets"}),
    (read, {"path": "projetos/../../actions/secrets"}),
    (read, {"path": "projetos/x.md?ref=other-branch"}),
    (read, {"path": "projetos/x.md#fragment"}),
    (read, {"path": "projetos/%2e%2e/%2e%2e/actions/secrets"}),
    (read, {"path": "/projetos/x.md"}),
    (read, {"path": "\\projetos\\x.md"}),
    (read, {"path": "projetos//x.md"}),
    (read, {"path": "projetos/./x.md"}),
    (read, {"path": ""}),
    (read, {"path": ".claude/settings.json"}),
    (read, {"path": "projetos-other/x.md"}),
    (list_files, {"path": "../../../OTHER/REPO/contents"}),
    (list_files, {"path": ".github/workflows"}),
    (write, {"path": "../../../OTHER/REPO/contents/x.md", **WRITE_ARGS}),
    (write, {"path": "../collaborators/ATTACKER", **WRITE_ARGS}),
    (write, {"path": ".claude/settings.json", **WRITE_ARGS}),
    (write, {"path": ".claude/hooks/x.py", **WRITE_ARGS}),
    (write, {"path": ".github/workflows/x.yml", **WRITE_ARGS}),
    (write, {"path": "projetos/_lint.py", **WRITE_ARGS}),
    (write, {"path": "projetos/x.md", **WRITE_ARGS}),
    (write, {"path": "CLAUDE.md", **WRITE_ARGS}),
    (write, {"path": "Base de conhecimento/script.py", **WRITE_ARGS}),
    (write, {"path": "Base de conhecimento/../.claude/x.md", **WRITE_ARGS}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool, args", PATHS_THAT_MUST_NOT_REACH_GITHUB)
async def test_path_outside_the_allowed_folders_sends_no_request(
    tool, args, requests_sent
):
    with pytest.raises(ValueError):
        await tool.ainvoke(args)
    assert requests_sent == []


@pytest.mark.asyncio
async def test_read_sends_the_allowed_path_encoded(requests_sent):
    await read.ainvoke({"path": "Base de conhecimento/x.md"})
    assert requests_sent == [("GET", f"{CONTENTS}/Base%20de%20conhecimento/x.md")]


@pytest.mark.asyncio
async def test_read_reaches_the_repo_map_and_the_other_readable_folders(requests_sent):
    await read.ainvoke({"path": "CLAUDE.md"})
    await read.ainvoke({"path": "projetos/TrustWise/Administração/x.md"})
    await read.ainvoke({"path": "memory/MEMORY.md"})
    assert [url for _, url in requests_sent] == [
        f"{CONTENTS}/CLAUDE.md",
        f"{CONTENTS}/projetos/TrustWise/Administra%C3%A7%C3%A3o/x.md",
        f"{CONTENTS}/memory/MEMORY.md",
    ]


@pytest.mark.asyncio
async def test_list_files_accepts_the_root_and_a_folder_ending_in_slash(requests_sent):
    await list_files.ainvoke({"path": ""})
    await list_files.ainvoke({"path": "Base de conhecimento/"})
    assert requests_sent == [
        ("GET", f"{CONTENTS}?ref=main"),
        ("GET", f"{CONTENTS}/Base%20de%20conhecimento?ref=main"),
    ]


@pytest.mark.asyncio
async def test_write_sends_get_and_put_to_the_same_encoded_path(requests_sent):
    await write.ainvoke(
        {"path": "Base de conhecimento/life-areas/new-file.md", **WRITE_ARGS}
    )
    url = f"{CONTENTS}/Base%20de%20conhecimento/life-areas/new-file.md"
    assert requests_sent == [("GET", url), ("PUT", url)]
