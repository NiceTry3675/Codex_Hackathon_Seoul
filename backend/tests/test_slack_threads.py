import pytest

from backend.slack_threads import parse_thread_link, read_thread


LINK = "https://synq-test.slack.com/archives/CTEST/p1789170000123456"


def test_thread_link_supports_reply_permalink_and_slack_wrapping():
    ref = parse_thread_link(f"<{LINK}?thread_ts=1789160000.654321&cid=CTEST|Thread>", "CTEST")
    assert ref.timestamp == "1789160000.654321"
    assert ref.permalink.endswith("p1789160000654321")
    assert ref.channel == "CTEST"


@pytest.mark.parametrize("link", [
    LINK.replace("CTEST", "COTHER"), LINK.replace("https:", "http:"),
    LINK.replace("slack.com", "slack.com.evil.test"),
    LINK.replace("synq-test", "synq|test"), LINK + "?thread_ts=wrong",
    LINK + "?thread_ts=1789160000.123456&thread_ts=1789160000.123457",
    "https://[invalid", "https://127.0.0.1/",
])
def test_rejects_other_channels_and_invalid_links(link):
    with pytest.raises(ValueError):
        parse_thread_link(link, "CTEST")


def test_reads_pages_and_omits_bot_content_and_user_identifiers():
    calls = []

    def page(channel, timestamp, cursor):
        calls.append((channel, timestamp, cursor))
        if not cursor:
            return {"messages": [{"ts": "1", "user": "UPRIVATE", "text": "<@UPRIVATE> 후보 A"},
                                 {"ts": "2", "bot_id": "BPRIVATE", "text": "BOT TEXT"}],
                    "response_metadata": {"next_cursor": "next"}}
        return {"messages": [{"ts": "1", "text": "Repeated parent"}, {"ts": "3", "text": "후보 B"}]}

    thread = read_thread(parse_thread_link(LINK, "CTEST"), page)
    assert thread.messages == ["[참여자] 후보 A", "후보 B"]
    assert thread.partial is False
    assert calls[1] == ("CTEST", "1789170000.123456", "next")


def test_long_thread_marks_partial_and_bounds_ai_input():
    thread = read_thread(parse_thread_link(LINK, "CTEST"), lambda *_: {
        "messages": [{"ts": "1", "text": "가" * 25000}],
    })
    assert thread.partial
    assert len(thread.messages[0]) == 20000


def test_page_with_more_but_no_cursor_is_not_reported_as_complete():
    thread = read_thread(parse_thread_link(LINK, "CTEST"), lambda *_: {
        "messages": [{"ts": "1", "text": "A"}], "has_more": True,
    })
    assert thread.partial


def test_repeated_cursor_stops_instead_of_looping():
    with pytest.raises(ValueError):
        read_thread(parse_thread_link(LINK, "CTEST"), lambda *_: {
            "messages": [{"ts": "1", "text": "A"}], "response_metadata": {"next_cursor": "repeat"},
        })
