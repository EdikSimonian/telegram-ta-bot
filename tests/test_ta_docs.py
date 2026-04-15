"""/doc admin command tests."""
from unittest.mock import MagicMock, patch


def _prepared(*, command_args="", username="alice"):
    p = MagicMock()
    p.user_id = 42
    p.username = username
    p.command = "doc"
    p.command_args = command_args
    p.group_key = "-100123"
    p.is_dm = True
    return p


# ── usage + unknown subcommand ────────────────────────────────────────────
def test_empty_args_show_usage():
    with patch("bot.ta.docs.send_message") as sm:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args=""))
        assert "Usage" in sm.call_args.args[1]


def test_unknown_subcommand_errors():
    with patch("bot.ta.docs.send_message") as sm:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="bogus"))
        assert "Unknown" in sm.call_args.args[1]


# ── /doc list ─────────────────────────────────────────────────────────────
def test_list_empty_state():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]):
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="list"))
        assert "No docs" in sm.call_args.args[1]


def test_list_shows_docs():
    docs = [
        {"slug": "cs101", "title": "CS101", "chunkCount": 4, "addedBy": "alice"},
        {"slug": "np", "title": "NumPy", "chunkCount": 7, "addedBy": "bob"},
    ]
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=docs):
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="list"))
        text = sm.call_args.args[1]
        assert "CS101" in text
        assert "NumPy" in text
        assert "cs101" in text
        assert "@alice" in text


# ── /doc add ──────────────────────────────────────────────────────────────
def test_add_requires_title_and_content():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.blob.put") as put:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="add"))
        assert "Usage" in sm.call_args.args[1]
        put.assert_not_called()


def test_add_happy_path_uploads_and_embeds():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]), \
         patch("bot.ta.docs.blob.put", return_value="https://blob/cs101.md") as put, \
         patch("bot.ta.docs.rag.upsert_doc", return_value=3) as up, \
         patch("bot.ta.docs.add_doc") as add_d:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="add CS101\nPython is a language."))
        put.assert_called_once()
        up.assert_called_once()
        assert up.call_args.kwargs["blob_url"] == "https://blob/cs101.md"
        add_d.assert_called_once()
        meta = add_d.call_args.args[0]
        assert meta["title"] == "CS101"
        assert meta["chunkCount"] == 3


def test_add_refuses_duplicate_title():
    existing = [{"slug": "cs101", "title": "CS101", "chunkCount": 3, "blobUrl": "https://old"}]
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=existing), \
         patch("bot.ta.docs.blob.put") as put:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="add CS101\nnew text"))
        put.assert_not_called()
        assert "already exists" in sm.call_args.args[1].lower()


def test_add_rolls_back_cleanly_when_blob_fails():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]), \
         patch("bot.ta.docs.blob.put", return_value=None), \
         patch("bot.ta.docs.rag.upsert_doc") as up, \
         patch("bot.ta.docs.add_doc") as add_d:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="add T\ncontent"))
        up.assert_not_called()
        add_d.assert_not_called()
        assert "Blob upload failed" in sm.call_args.args[1]


def test_add_reports_when_vector_upsert_fails():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]), \
         patch("bot.ta.docs.blob.put", return_value="https://blob/t.md"), \
         patch("bot.ta.docs.rag.upsert_doc", return_value=0), \
         patch("bot.ta.docs.add_doc") as add_d:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="add T\ncontent"))
        add_d.assert_not_called()
        assert "Vector upsert failed" in sm.call_args.args[1]


# ── /doc update ───────────────────────────────────────────────────────────
def test_update_requires_existing_doc():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]), \
         patch("bot.ta.docs.blob.put") as put:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="update Unknown\nfoo"))
        put.assert_not_called()
        assert "No existing doc" in sm.call_args.args[1]


def test_update_purges_old_then_uploads_new():
    existing = [{"slug": "cs101", "title": "CS101", "chunkCount": 3, "blobUrl": "https://old"}]
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=existing), \
         patch("bot.ta.docs.rag.delete_doc") as vdel, \
         patch("bot.ta.docs.blob.delete") as bdel, \
         patch("bot.ta.docs.remove_doc") as rm, \
         patch("bot.ta.docs.blob.put", return_value="https://blob/new.md"), \
         patch("bot.ta.docs.rag.upsert_doc", return_value=4) as up, \
         patch("bot.ta.docs.add_doc") as add_d:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="update CS101\nnew content"))
        vdel.assert_called_once_with("cs101", 3)
        bdel.assert_called_once_with("https://old")
        rm.assert_called_once_with("cs101")
        up.assert_called_once()
        add_d.assert_called_once()
        assert add_d.call_args.args[0]["chunkCount"] == 4


# ── /doc delete ───────────────────────────────────────────────────────────
def test_delete_unknown_title():
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=[]):
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="delete Nope"))
        assert "No doc matches" in sm.call_args.args[1]


def test_delete_happy_path_purges_everywhere():
    existing = [{"slug": "cs101", "title": "CS101", "chunkCount": 3, "blobUrl": "https://old"}]
    with patch("bot.ta.docs.send_message") as sm, \
         patch("bot.ta.docs.list_docs", return_value=existing), \
         patch("bot.ta.docs.rag.delete_doc") as vdel, \
         patch("bot.ta.docs.blob.delete") as bdel, \
         patch("bot.ta.docs.remove_doc") as rm:
        from bot.ta.docs import dispatch
        dispatch(_prepared(command_args="delete CS101"))
        vdel.assert_called_once()
        bdel.assert_called_once()
        rm.assert_called_once()
        assert "Deleted" in sm.call_args.args[1]
