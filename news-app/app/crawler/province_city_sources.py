"""山东 / 辽宁地级市政府门户源（2026-11-17 接入，24 市）。

统一约束（沿用 province_sources.py 的隔离设计）：
  * level="city"，region_province=规范省名，region_city=规范地级市名，
    region_district / region_org / region_area 留空；
  * 统计隔离：周月报 / 趋势页只统计广东省 + 国家部委，外省 city 级源
    已在这些查询里按 region_province 排除，不会混进「广东省」地市榜；
  * HTTP_ONLY：日照/枣庄/东营/聊城/滨州/菏泽/鞍山/辽阳等站证书域名不匹配，
    只能走 http 明文，域名已登记在 base.Fetcher.HTTP_ONLY_HOSTS；
  * TRS WCM / jpage 站点（日照/泰安/威海/淄博/济宁/大连等）首屏列表嵌在
    <script> 的 CDATA 里，base._parse_list 已加 CDATA 回退解析；
  * 临沂正文在 form 容器内，用 selector_config.content 显式指定并保留 form。

30 个源均用项目 Fetcher 实测：列表可解析（10~30 条）、带发布日期、
详情页正文 46~4564 字，无空正文源。

2026-11-17 二轮补齐首批未接入的 6 市（济南/聊城/本溪/锦州/葫芦岛/铁岭）：
  * 济南：JCMS(jpaas) 站，列表由 /api-gateway/jpaas-publish-server/front/page/build/unit
    返回 JSON，正文在 data.html 片段里 → fetch_type="html_api"，list_base 指向真实栏目页。
  * 聊城：真实栏目是 channel_t_156_11221（要闻动态），doc_xxx.html 详情正文在 .details_1。
    首批误用了搜索页 channel_t_156_11232（无文章）。
  * 本溪：文章链接是 content_<id>（无扩展名），base.py URL 正则已加 content_数字 模式。
  * 锦州：主域 www.jinzhou.gov.cn 本机 DNS 不通，改用 www.jz.gov.cn；正文 .v_news_content。
  * 葫芦岛：主域 www.huludao.gov.cn 本机 DNS 不通，改用 www.hld.gov.cn。
  * 铁岭：首批站点瞬时不可达，本轮恢复；文章是 /<19位数字>/index.html，
    base.py 的 has_article_id 规则已放行。
"""
from __future__ import annotations

PROVINCE_CITY_SOURCES = [
    # ===== 山东省 14 市 =====
    {
        "name": "青岛市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.qingdao.gov.cn",
        "list_url": "http://www.qingdao.gov.cn/ywdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "枣庄市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "枣庄市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.zaozhuang.gov.cn",
        "list_url": "http://www.zaozhuang.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "东营市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "东营市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.dongying.gov.cn",
        "list_url": "http://www.dongying.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.yantai.gov.cn",
        "list_url": "https://www.yantai.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.weifang.gov.cn",
        "list_url": "https://www.weifang.gov.cn/wfywdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济宁市人民政府 - 今日济宁",
        "region_province": "山东省", "region_city": "济宁市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.jining.gov.cn",
        "list_url": "https://www.jining.gov.cn/col/col182/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "泰安市人民政府 - 今日泰安",
        "region_province": "山东省", "region_city": "泰安市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.taian.gov.cn",
        "list_url": "https://www.taian.gov.cn/col/col46736/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "威海市人民政府 - 今日威海",
        "region_province": "山东省", "region_city": "威海市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.weihai.gov.cn",
        "list_url": "https://www.weihai.gov.cn/col/col58817/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "日照市人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "日照市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.rizhao.gov.cn",
        "list_url": "http://www.rizhao.gov.cn/col/col207400/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "临沂市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.linyi.gov.cn",
        "list_url": "https://www.linyi.gov.cn/xw/zwyw.htm",
        "fetch_type": "html",
        "selector_config": {"content": ".v_news_content"},
    },
    {
        "name": "德州市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "德州市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.dezhou.gov.cn",
        "list_url": "https://www.dezhou.gov.cn/n42860412/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "滨州市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "滨州市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.binzhou.gov.cn",
        "list_url": "http://www.binzhou.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "菏泽市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "菏泽市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.heze.gov.cn",
        "list_url": "http://www.heze.gov.cn/ywdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.zibo.gov.cn",
        "list_url": "https://www.zibo.gov.cn/col/col10/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    # ===== 辽宁省 10 市 =====
    {
        "name": "沈阳市人民政府 - 要闻动态",
        "region_province": "辽宁省", "region_city": "沈阳市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.shenyang.gov.cn",
        "list_url": "https://www.shenyang.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "大连市人民政府 - 今日大连",
        "region_province": "辽宁省", "region_city": "大连市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.dl.gov.cn",
        "list_url": "https://www.dl.gov.cn/col/col1185/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "鞍山市人民政府 - 今日鞍山",
        "region_province": "辽宁省", "region_city": "鞍山市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.anshan.gov.cn",
        "list_url": "http://www.anshan.gov.cn/asszf/jras/glist.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "抚顺市人民政府 - 今日抚顺",
        "region_province": "辽宁省", "region_city": "抚顺市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.fushun.gov.cn",
        "list_url": "https://www.fushun.gov.cn/ywdt/001001/moreinfo.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "丹东市人民政府 - 今日丹东",
        "region_province": "辽宁省", "region_city": "丹东市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.dandong.gov.cn",
        "list_url": "https://www.dandong.gov.cn/ddszf/xw/jrdd/glist.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "营口市人民政府 - 营口要闻",
        "region_province": "辽宁省", "region_city": "营口市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.yingkou.gov.cn",
        "list_url": "https://www.yingkou.gov.cn/001/001001/about_zydt.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "阜新市人民政府 - 部门动态",
        "region_province": "辽宁省", "region_city": "阜新市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.fuxin.gov.cn",
        "list_url": "https://www.fuxin.gov.cn/channel/list/12797.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "辽阳市人民政府 - 本市要闻",
        "region_province": "辽宁省", "region_city": "辽阳市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.liaoyang.gov.cn",
        "list_url": "http://www.liaoyang.gov.cn/zwzx/002002/002002001/com_list_zwzx.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "盘锦市人民政府 - 要闻动态",
        "region_province": "辽宁省", "region_city": "盘锦市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.panjin.gov.cn",
        "list_url": "http://www.panjin.gov.cn/html/1736/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "朝阳市人民政府 - 政务要闻",
        "region_province": "辽宁省", "region_city": "朝阳市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.chaoyang.gov.cn",
        "list_url": "https://www.chaoyang.gov.cn/cyszf/ywdt/zwyw/glist.html",
        "fetch_type": "html", "selector_config": {},
    },
    # ===== 2026-11-17 二轮补齐 6 市（山东 2 + 辽宁 4）=====
    {
        "name": "济南市人民政府 - 济南动态",
        "region_province": "山东省", "region_city": "济南市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.jinan.gov.cn",
        "list_url": ("https://www.jinan.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit"
                     "?parseType=bulidstatic&webId=1&tplSetId=T7OHq9iquBxjUIFa3Xk4O"
                     "&pageType=column&tagId=%E5%BD%93%E5%89%8D%E6%A0%8F%E7%9B%AElist"
                     "&editType=null&pageId=52"),
        "fetch_type": "html_api",
        "selector_config": {"list_base": "https://www.jinan.gov.cn/col/col52/index.html"},
    },
    {
        "name": "聊城市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "聊城市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "http://www.liaocheng.gov.cn",
        "list_url": "http://www.liaocheng.gov.cn/channel_t_156_11221/",
        "fetch_type": "html", "selector_config": {"content": ".details_1"},
    },
    {
        "name": "本溪市人民政府 - 政务要闻",
        "region_province": "辽宁省", "region_city": "本溪市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.benxi.gov.cn",
        "list_url": "https://www.benxi.gov.cn/xw/zwyw",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "锦州市人民政府 - 政务要闻",
        "region_province": "辽宁省", "region_city": "锦州市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.jz.gov.cn",
        "list_url": "https://www.jz.gov.cn/zwyw.htm",
        "fetch_type": "html", "selector_config": {"content": ".v_news_content"},
    },
    {
        "name": "葫芦岛市人民政府 - 政务要闻",
        "region_province": "辽宁省", "region_city": "葫芦岛市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.hld.gov.cn",
        "list_url": "https://www.hld.gov.cn/xwdt/zwyw/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "铁岭市人民政府 - 要闻动态",
        "region_province": "辽宁省", "region_city": "铁岭市",
        "region_district": "", "region_org": "", "region_area": "",
        "level": "city",
        "base_url": "https://www.tieling.gov.cn",
        "list_url": "https://www.tieling.gov.cn/tieling/ywdt/index.html",
        "fetch_type": "html", "selector_config": {},
    },
]
