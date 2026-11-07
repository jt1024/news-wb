"""抓取层：标题清洗、同站过滤、列表解析、噪音行剔除、日期解析。"""
import unittest
from datetime import datetime
from types import SimpleNamespace

from app.crawler.base import (
    Fetcher,
    _clean_text_lines,
    _clean_title,
    _parse_date,
    same_site,
)


class CleanTitleTests(unittest.TestCase):
    def test_strips_br_tag(self):
        self.assertEqual(
            _clean_title("东莞市召开会议<br/>部署重点工作"),
            "东莞市召开会议 部署重点工作",
        )

    def test_unescapes_entities(self):
        self.assertEqual(
            _clean_title("&quot;十五五&quot;规划编制工作座谈会召开"),
            '"十五五"规划编制工作座谈会召开',
        )

    def test_mixed_html_and_entities(self):
        self.assertEqual(
            _clean_title("<span>关于&nbsp;进一步做好&nbsp; 工作的通知</span>"),
            "关于 进一步做好 工作的通知",
        )

    def test_collapses_whitespace(self):
        self.assertEqual(_clean_title("  甲　乙 \n\t 丙  "), "甲 乙 丙")

    def test_normal_title_unchanged(self):
        t = "市委常委会召开会议 传达学习党的二十届五中全会精神"
        self.assertEqual(_clean_title(t), t)

    def test_non_string_input(self):
        self.assertEqual(_clean_title(123), "123")


class SameSiteTests(unittest.TestCase):
    def test_same_host(self):
        self.assertTrue(same_site("https://www.heyuan.gov.cn/a.html", "https://www.heyuan.gov.cn"))

    def test_sub_and_parent_domain(self):
        self.assertTrue(same_site("https://zwgk.gd.gov.cn/a.html", "https://www.gd.gov.cn"))
        self.assertTrue(same_site("https://gd.gov.cn/a.html", "https://www.gd.gov.cn"))

    def test_external_icon_link_rejected(self):
        self.assertFalse(same_site("https://wza.isc.org.cn/rzpt/x.html", "https://www.yangjiang.gov.cn"))
        self.assertFalse(same_site("https://evil-gov.cn/x.html", "https://www.meizhou.gov.cn"))

    def test_unparsable_host_is_allowed(self):
        self.assertTrue(same_site("/relative/a.html", "https://www.heyuan.gov.cn"))


class ParseListTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(
            name="测试源",
            base_url="https://www.example.gov.cn",
            list_url="https://www.example.gov.cn/ywdt/index.html",
            fetch_type="html",
            selector_config={"item": "a"},
        )

    def test_filters_external_icon_and_index_link(self):
        html = """
        <ul>
          <li><a href="/ywdt/content/post_100.html"
                 title="广州市召开经济工作会议部署四季度重点工作">标题</a>
              <span>2026-11-07</span></li>
          <li><a href="https://wza.isc.org.cn/rzpt/4577.html"
                 title="适老化无障碍服务">图标</a></li>
          <li><a href="/ywdt/index.html" title="返回要闻动态栏目首页">栏目</a></li>
          <li><a href="javascript:;" title="分享到微信朋友圈">分享</a></li>
        </ul>
        """
        items = Fetcher(self.source)._parse_list(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "广州市召开经济工作会议部署四季度重点工作")
        self.assertTrue(items[0].url.endswith("/ywdt/content/post_100.html"))
        self.assertEqual(items[0].publish_time, datetime(2026, 11, 7))

    def test_title_attribute_with_html_is_cleaned(self):
        html = '<li><a href="/a/content/post_1.html" title="会议召开<br/>部署重点工作安排">x</a><span>2026-11-06</span></li>'
        items = Fetcher(self.source)._parse_list(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "会议召开 部署重点工作安排")


class TextCleaningTests(unittest.TestCase):
    def test_removes_layout_noise_but_keeps_body(self):
        lines = [
            "首页 > 要闻动态", "汕头市召开全市高质量发展大会", "2026-11-07",
            "来源：汕头日报", "分享到：", "【字体大小： 大 中 小】",
            "会议强调，要坚持以高质量发展为首要任务，推动产业转型升级。",
        ]
        out = _clean_text_lines(lines)
        self.assertIn("会议强调，要坚持以高质量发展为首要任务，推动产业转型升级。", out)
        self.assertNotIn("分享到：", out)
        self.assertNotIn("2026-11-07", out)
        self.assertNotIn("来源：汕头日报", out)

    def test_parse_date_formats(self):
        for text, expected in [
            ("发布时间：2026-11-07", datetime(2026, 11, 7)),
            ("2026年11月7日", datetime(2026, 11, 7)),
            ("2026/3/9", datetime(2026, 3, 9)),
            ("2026.12.01", datetime(2026, 12, 1)),
            ("无日期", None),
        ]:
            self.assertEqual(_parse_date(text), expected)


if __name__ == "__main__":
    unittest.main()
