"""山东区级政府门户源 · 第一批（2026-11-18 接入，17 源）。

统一约束（沿用 province_sources.py 的隔离设计）：
  * level="district"，region_province=山东省，region_city=规范地级市，region_district=规范区县；
  * region_org / region_area 留空，不参与国家部委与港澳台口径；
  * 趋势页 / 周月报维持「广东省 + 国家部委」口径，已按 region_province 排除外省；
  * 淄博 / 威海各站 https 证书域名不匹配，只能走 http 明文，域名已登记在
    base.Fetcher.HTTP_ONLY_HOSTS；兰山/兰陵/莒南/蒙阴/临沭用 https；
  * 临沭详情页正文在 .v_news_content，用 selector_config.content 显式指定。

17 源均用项目 Fetcher 实测：列表 7~90 条、带发布日期、正文 192~1876 字，无空正文源。
后续批次（区县域名尚未取得或被网络策略拦截）按同样格式追加即可。
"""
from __future__ import annotations

SHANDONG_DISTRICT_SOURCES = [
    {
        "name": "淄博市淄川区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "淄川区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.zichuan.gov.cn",
        "list_url": "http://www.zichuan.gov.cn/col/col4625/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市张店区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "张店区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.zhangdian.gov.cn",
        "list_url": "http://www.zhangdian.gov.cn/col/col6078/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市博山区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "博山区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.boshan.gov.cn",
        "list_url": "http://www.boshan.gov.cn/col/col4423/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市临淄区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "临淄区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.linzi.gov.cn",
        "list_url": "http://www.linzi.gov.cn/col/col5302/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市周村区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "周村区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.zhoucun.gov.cn",
        "list_url": "http://www.zhoucun.gov.cn/col/col5349/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市桓台县人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "桓台县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.huantai.gov.cn",
        "list_url": "http://www.huantai.gov.cn/col/col4853/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市高青县人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "高青县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.gaoqing.gov.cn",
        "list_url": "http://www.gaoqing.gov.cn/col/col4596/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "淄博市沂源县人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "淄博市", "region_district": "沂源县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.yiyuan.gov.cn",
        "list_url": "http://www.yiyuan.gov.cn/col/col5601/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "威海市环翠区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "威海市", "region_district": "环翠区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.huancui.gov.cn",
        "list_url": "http://www.huancui.gov.cn/col/col41522/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "威海市文登区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "威海市", "region_district": "文登区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.wendeng.gov.cn",
        "list_url": "http://www.wendeng.gov.cn/col/col37135/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "威海市荣成市人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "威海市", "region_district": "荣成市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.rongcheng.gov.cn",
        "list_url": "http://www.rongcheng.gov.cn/col/col40743/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "威海市乳山市人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "威海市", "region_district": "乳山市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.rushan.gov.cn",
        "list_url": "http://www.rushan.gov.cn/col/col51289/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市兰山区人民政府 - 今日关注",
        "region_province": "山东省", "region_city": "临沂市", "region_district": "兰山区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.lanshan.gov.cn",
        "list_url": "https://www.lanshan.gov.cn/lanshan/zwdt/list.shtml",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市兰陵县人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "临沂市", "region_district": "兰陵县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.lanling.gov.cn",
        "list_url": "https://www.lanling.gov.cn/xw/zwyw.htm",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市莒南县人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "临沂市", "region_district": "莒南县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.junan.gov.cn",
        "list_url": "http://www.junan.gov.cn/xw/zwyw.htm",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市蒙阴县人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "临沂市", "region_district": "蒙阴县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.mengyin.gov.cn",
        "list_url": "http://www.mengyin.gov.cn/xw/zwyw.htm",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "临沂市临沭县人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "临沂市", "region_district": "临沭县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.linshu.gov.cn",
        "list_url": "https://www.linshu.gov.cn/yw/zwyw.htm",
        "fetch_type": "html", "selector_config": {"content": ".v_news_content"},
    },
]
