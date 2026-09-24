import unittest

import extract


SHARE_TEXT = """로그인
앱 다운로드
choi.openai
6시간
미래는 이미 정해져있습니다.
인류 역사상 가장 큰 풍요와 ‘영원한 노동계층’이 같은 시대에 나타나는 구조로요.
이 글을 읽게 되면 세상을 바라보는 시선이 달라지게 될 것입니다. 🧵
223
64
choi.openai
6시간
·
작성자
1/ 다리오 아모데이가 9월 12일 에세이에서 프런티어의 속도를 조절하자고 제안했습니다.
AI는 이미 답을 내놓는 단계에서 다음 AI의 개발에 참여하는 단계로 옮겨가고 있습니다.
14
1
choi.openai
2026-08-17
데이비드 삭스와 개빈 베이커는 젠슨 황의 인프라 금융 전략을 분석했습니다.
22
1
choi.openai
6시간
·
작성자
2/ 데이비드 색스의 반론은 바로 그 소유자의 이해관계를 겨냥합니다.
11
1
other.user
5시간
이건 다른 사람 답글입니다.
8
"""

SHARE_HTML = """
<html><body>
<div data-pressable-container="true">
  <a href="/@choi.openai">choi.openai</a>
  <div>미래는 이미 정해져있습니다.</div>
</div>
<div data-pressable-container="true">
  <a href="/@choi.openai">choi.openai</a>
  <div>작성자</div>
  <div>1/ 다리오 아모데이가</div>
</div>
</body></html>
"""


class ThreadsShareParseTests(unittest.TestCase):
    def test_render_handle_from_share_html(self):
        handle = extract._threads_render_handle({"html": SHARE_HTML, "text": ""})
        self.assertEqual(handle, "choi.openai")

    def test_share_thread_keeps_unmarked_opener(self):
        posts = extract._parse_threads_chain(
            SHARE_TEXT, "choi.openai", accept_unmarked_first=True,
        )
        self.assertEqual(len(posts), 3)
        self.assertTrue(posts[0].startswith("미래는 이미 정해져있습니다."))
        self.assertTrue(posts[1].startswith("1/ 다리오 아모데이가"))
        self.assertTrue(posts[2].startswith("2/ 데이비드 색스의 반론"))
        joined = "\n".join(posts)
        self.assertNotIn("젠슨 황의 인프라", joined)
        self.assertNotIn("다른 사람 답글", joined)

    def test_share_thread_without_opener_drops_title(self):
        posts = extract._parse_threads_chain(
            SHARE_TEXT, "choi.openai", accept_unmarked_first=False,
        )
        self.assertEqual(len(posts), 2)
        self.assertTrue(posts[0].startswith("1/ 다리오 아모데이가"))


if __name__ == "__main__":
    unittest.main()
