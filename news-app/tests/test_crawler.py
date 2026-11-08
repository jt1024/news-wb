"""抓取层：标题清洗、同站过滤、列表解析、噪音行剔除、日期解析。"""
import unittest
from datetime import datetime
from types import SimpleNamespace

from app.crawler.base import (
    Fetcher,
    _clean_text_lines,
    _clean_title,
    _detail_publish_date,
    _is_footer_only,
    _parse_date,
    _parse_date_from_url,
    same_site,
)
from bs4 import BeautifulSoup


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

    def test_trailing_publish_date_is_stripped(self):
        """交通运输部把日期拼在链接文本尾部，不能进标题。"""
        self.assertEqual(
            _clean_title("全国首个游艇水污染物全接收政策落地三亚 2026-11-06"),
            "全国首个游艇水污染物全接收政策落地三亚",
        )
        self.assertEqual(_clean_title("会议召开 2026年11月6日"), "会议召开")


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

    def test_public_suffix_is_not_a_parent_domain(self):
        """所有政务站都在 .gov.cn 下；gov.cn 不能当 samr.gov.cn 的父域放行。

        回归：市场监管总局首页曾把中国政府网通稿当成本部新闻抓入库。
        """
        self.assertFalse(same_site("https://www.gov.cn/yaowen/202611/content_1.htm",
                                   "https://www.samr.gov.cn"))
        self.assertFalse(same_site("https://www.gov.cn/zhengce/content/1.htm",
                                   "https://www.mca.gov.cn"))
        # 真实父子域仍然放行
        self.assertTrue(same_site("https://vod.mnr.gov.cn/ztp/1.htm",
                                  "https://www.mnr.gov.cn"))


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

    def test_href_with_leading_space_is_trimmed(self):
        """增城区列表页 href 写成 ' http://...'，不 strip 会让 httpx 报 UnsupportedProtocol。"""
        html = ('<li><a href=" https://www.example.gov.cn/a/content/post_1.html" '
                'title="增城区人大常委会党组召开扩大会议">x</a></li>')
        items = Fetcher(self.source)._parse_list(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://www.example.gov.cn/a/content/post_1.html")
        self.assertNotIn(" ", items[0].url)

    def test_date_in_grandparent_container(self):
        """白云区把标题放 div.tit、日期放父级 div.box，逐层向上才能取到日期。"""
        html = ('<li><div class="box"><div class="tit">'
                '<a href="/ywdt/content/post_2.html" title="白云区传达学习贯彻全会精神干部大会召开">x</a>'
                '</div><span>白云时事 2026-11-05</span></div></li>')
        items = Fetcher(self.source)._parse_list(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].publish_time, datetime(2026, 11, 5))

    def test_each_item_keeps_its_own_date(self):
        """同属一个 ul 的条目各取各的日期，不会被相邻条目或首条日期覆盖。"""
        html = ('<ul><li><a href="/a/content/post_1.html" title="第一条新闻标题内容足够长">1</a>'
                '<span>2026-01-01</span></li>'
                '<li><a href="/a/content/post_2.html" title="第二条新闻标题内容足够长">2</a>'
                '<span>2026-11-05</span></li></ul>')
        items = Fetcher(self.source)._parse_list(html)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].publish_time, datetime(2026, 11, 5))


class FooterOnlyTests(unittest.TestCase):
    def test_detects_footer_text(self):
        raw = "版权所有：广州市南沙区人民政府\n粤ICP备19092744号\n网站标识码：4401150002"
        self.assertTrue(_is_footer_only(raw))

    def test_keeps_short_real_body(self):
        raw = "11月5日，区人大常委会党组召开扩大会议，研究部署下一阶段重点工作。"
        self.assertFalse(_is_footer_only(raw))

    def test_detail_returns_empty_for_footer_only_page(self):
        html = ('<html><body><div class="content">'
                '<p>版权所有：广州市南沙区人民政府</p><p>粤ICP备19092744号</p>'
                '<p>网站标识码：4401150002</p><p>联系电话：020-12345</p>'
                '</div></body></html>')
        src = SimpleNamespace(name="测试源", base_url="https://www.example.gov.cn",
                              list_url="https://www.example.gov.cn/index.html",
                              fetch_type="html", selector_config={})
        self.assertEqual(Fetcher(src)._extract_detail(html).content_text, "")


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


class DistrictSourceConfigTests(unittest.TestCase):
    """广州 11 区源配置的完整性与唯一性（seed 按 name 幂等，重名会静默漏源）。"""

    EXPECTED = {"越秀区", "海珠区", "荔湾区", "天河区", "白云区", "黄埔区",
                "花都区", "番禺区", "南沙区", "从化区", "增城区"}

    def test_eleven_gz_districts_covered(self):
        from app.crawler.sources import SEED_SOURCES

        districts = [c for c in SEED_SOURCES if c.get("region_district")]
        self.assertEqual({c["region_district"] for c in districts}, self.EXPECTED)
        self.assertEqual(len(districts), 11)
        for c in districts:
            self.assertEqual(c["region_city"], "广州市")
            self.assertEqual(c["level"], "district")
            self.assertTrue(c["list_url"].startswith(("http://", "https://")))

    def test_seed_names_are_unique(self):
        from app.crawler.sources import SEED_SOURCES

        names = [c["name"] for c in SEED_SOURCES]
        self.assertEqual(len(names), len(set(names)))

    def test_all_sources_have_valid_level(self):
        from app.crawler.sources import SEED_SOURCES

        for c in SEED_SOURCES:
            self.assertIn(c["level"], ("national", "province", "city", "district"))


class UrlDateTests(unittest.TestCase):
    """部委站列表页多不显示日期，靠 URL 里的发布日期兜底。"""

    def test_energy_admin_date_dir(self):
        self.assertEqual(
            _parse_date_from_url("https://www.nea.gov.cn/20261105/abc123/c.html"),
            datetime(2026, 11, 5),
        )

    def test_trs_article_id(self):
        self.assertEqual(
            _parse_date_from_url("https://www.mof.gov.cn/x/202611/t20261105_4004145.htm"),
            datetime(2026, 11, 5),
        )

    def test_urite_article_path(self):
        self.assertEqual(
            _parse_date_from_url("https://www.nhsa.gov.cn/art/2026/9/23/art_14_22334.html"),
            datetime(2026, 9, 23),
        )

    def test_no_date_in_url(self):
        self.assertIsNone(_parse_date_from_url("https://www.gov.cn/yaowen/202611/content_1.htm"))
        self.assertIsNone(_parse_date_from_url("https://www.samr.gov.cn/xw/zj/art/2026/art_abc.html"))


class JsonListTests(unittest.TestCase):
    def setUp(self):
        self.source = SimpleNamespace(
            name="中国政府网 - 要闻", base_url="https://www.gov.cn",
            list_url="https://www.gov.cn/yaowen/liebiao/", fetch_type="json",
            selector_config={"list_api": "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json"},
        )

    def test_gov_cn_array_format_and_external_filter(self):
        import json

        raw = json.dumps([
            {"TITLE": "国务院常务会议部署四季度经济工作",
             "URL": "https://www.gov.cn/yaowen/202611/content_7085000.htm",
             "DOCRELPUBTIME": "2026-11-07"},
            {"TITLE": "外站视频新闻不应被收录进本平台",
             "URL": "https://tv.cctv.com/2026/11/07/VIDEabc.shtml",
             "DOCRELPUBTIME": "2026-11-07"},
            {"TITLE": "国务院发布关于进一步优化营商环境的通知",
             "URL": "https://www.gov.cn/zhengce/content/202611/content_7085001.htm",
             "DOCRELPUBTIME": "2026-11-06"},
        ], ensure_ascii=False)
        items = Fetcher(self.source)._parse_json_list(raw)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].publish_time, datetime(2026, 11, 7))
        self.assertTrue(all("gov.cn" in i.url for i in items))

    def test_legacy_postmeta_format_still_works(self):
        import json

        zhuhai = SimpleNamespace(
            name="珠海市人民政府 - 珠海要闻", base_url="https://www.zhuhai.gov.cn",
            list_url="https://www.zhuhai.gov.cn/postmeta/i/4013.json", fetch_type="json",
            selector_config={},
        )
        raw = json.dumps({"articles": [{
            "title": "珠海市召开推进粤港澳大湾区建设工作会议",
            "url": "https://www.zhuhai.gov.cn/xw/content/post_123.html",
            "publish_time": 1762502400000,
        }]}, ensure_ascii=False)
        items = Fetcher(zhuhai)._parse_json_list(raw)
        self.assertEqual(len(items), 1)
        self.assertIsNotNone(items[0].publish_time)


class DetailDateTests(unittest.TestCase):
    def test_pubdate_meta(self):
        html = ('<html><head><meta name="PubDate" content="2026-11-07 10:22"></head>'
                '<body><p>市场监管总局发布合规提示。</p></body></html>')
        self.assertEqual(_detail_publish_date(BeautifulSoup(html, "lxml"), html),
                         datetime(2026, 11, 7))

    def test_labeled_inline_date(self):
        html = '<html><body><span>发布时间：2026-11-05</span><p>正文内容</p></body></html>'
        self.assertEqual(_detail_publish_date(BeautifulSoup(html, "lxml"), html),
                         datetime(2026, 11, 5))

    def test_historical_date_in_body_is_ignored(self):
        html = '<html><body><p>根据2020年1月1日印发的暂行办法，现就有关事项通知如下。</p></body></html>'
        self.assertIsNone(_detail_publish_date(BeautifulSoup(html, "lxml"), html))


class NationalSourceConfigTests(unittest.TestCase):
    def test_national_sources_are_well_formed(self):
        from app.crawler.sources import SEED_SOURCES

        national = [c for c in SEED_SOURCES if c.get("level") == "national"]
        self.assertEqual(len(national), 23)
        for c in national:
            self.assertEqual(c["region_province"], "全国")
            self.assertEqual(c["region_city"], "")
            self.assertEqual(c.get("region_district", ""), "")
            self.assertTrue(c["region_org"], c["name"])
            self.assertTrue(c["list_url"].startswith(("http://", "https://")))
            self.assertTrue(c["base_url"])

    def test_covers_22_ministry_orgs(self):
        from app.crawler.sources import SEED_SOURCES

        orgs = {c["region_org"] for c in SEED_SOURCES if c.get("level") == "national"}
        self.assertEqual(len(orgs), 22)
        for name in ("国家发展改革委", "财政部", "商务部", "中国人民银行",
                     "市场监管总局", "中国政府网", "国家数据局"):
            self.assertIn(name, orgs)

    def test_extract_detail_carries_publish_date(self):
        f = Fetcher(SimpleNamespace(
            name="t", base_url="https://www.samr.gov.cn",
            list_url="https://www.samr.gov.cn/xw/index.html",
            fetch_type="html", selector_config={"item": "a"},
        ))
        html = ('<html><head><meta name="PubDate" content="2026-11-07"></head>'
                '<body><div id="zoom">'
                '<p>市场监管总局发布合规提示，规范网络集中促销经营活动，要求平台企业严格落实主体责任。</p>'
                '<p>各地市场监管部门要加强督促检查，重点查处先提价后打折、虚假宣传等违法行为，'
                '维护公平有序的网络交易秩序和消费者合法权益。</p></div></body></html>')
        d = f._extract_detail(html)
        self.assertEqual(d.publish_time, datetime(2026, 11, 7))
        self.assertGreater(len(d.content_text), 10)


if __name__ == "__main__":
    unittest.main()
