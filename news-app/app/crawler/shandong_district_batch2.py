"""山东区级政府门户源 · 第二批（2026-11-18 接入，41 源）。

覆盖烟台 / 青岛 / 济南 / 潍坊四市的区县政府门户，沿用第一批的隔离设计：
  * level="district"，region_province=山东省，region_city=规范地级市，
    region_district=规范区县（与 app/data/regions.json 一致，保证前台三级筛选可命中）；
  * region_org / region_area 留空，不参与国家部委与港澳台口径；
  * 趋势页 / 周月报维持「广东省 + 国家部委」口径，已按 region_province 排除外省。

接入方式（分批 + 后台验证，与第一批量产路径一致）：
  * 域名由四市政府门户首页的「区市政府网站」导航外链提取，41 站裸 http 实测 200；
  * 8 站用项目 Fetcher 实测拿到了精确栏目地址（下文逐条注明条数/日期），其余 33 站
    以首页为列表入口，靠 base._parse_list 自动提取要闻链接（第一批枣庄/东营/烟台市/
    青岛市同样用首页，运行稳定）；后台首轮全量抓取后按执行报告再微调栏目。
  * 33 站 https 自签 / TLS 握手失败 / 升级回 502，域名已登记在
    base.Fetcher.HTTP_ONLY_HOSTS 走 http 明文；已实测 https 可用的 8 站不登记，
    由 _prefer_https 自动升级。

未纳入本批（域名不通或非本省，留待后续核域名）：
  * 济南长清区 / 章丘区：www.changqing.gov.cn / www.zhangqiu.gov.cn 及候选域名均 403；
  * 烟台莱山区 / 栖霞市：www.laishan.gov.cn / www.qixia.gov.cn 及候选域名均 403；
  * 烟台福山区：www.fushan.gov.cn 实为「山西浮山县人民政府」，非烟台福山，已排除。
"""
from __future__ import annotations

SHANDONG_DISTRICT_BATCH2 = [
    # ===== 青岛市 10 区市 =====
    {
        "name": "青岛市市南区人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "市南区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.qdsn.gov.cn",
        "list_url": "http://www.qdsn.gov.cn/zwgk_8/ywdt_8/zwyw_8/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市市北区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "市北区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.qingdaoshibei.gov.cn",
        "list_url": "http://www.qingdaoshibei.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市李沧区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "李沧区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.qdlc.gov.cn",
        "list_url": "http://www.qdlc.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市崂山区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "崂山区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.laoshan.gov.cn",
        "list_url": "http://www.laoshan.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市黄岛区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "黄岛区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.huangdao.gov.cn",
        "list_url": "http://www.huangdao.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市城阳区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "城阳区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.chengyang.gov.cn",
        "list_url": "http://www.chengyang.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市即墨区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "即墨区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.jimo.gov.cn",
        "list_url": "http://www.jimo.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市胶州市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "胶州市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.jiaozhou.gov.cn",
        "list_url": "http://www.jiaozhou.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市平度市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "平度市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.pingdu.gov.cn",
        "list_url": "http://www.pingdu.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "青岛市莱西市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "青岛市", "region_district": "莱西市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.laixi.gov.cn",
        "list_url": "http://www.laixi.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },

    # ===== 济南市 10 区（长清/章丘域名不通，留待后续） =====
    {
        "name": "济南市历下区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "历下区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.lixia.gov.cn",
        "list_url": "http://www.lixia.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市市中区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "市中区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.shizhong.gov.cn",
        "list_url": "http://www.shizhong.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市槐荫区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "槐荫区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.huaiyin.gov.cn",
        "list_url": "http://www.huaiyin.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市天桥区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "天桥区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.tianqiao.gov.cn",
        "list_url": "http://www.tianqiao.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市历城区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "历城区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.licheng.gov.cn",
        "list_url": "http://www.licheng.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：政务新闻栏目 37 条；日期靠 URL / 详情兜底，https 可用
        "name": "济南市济阳区人民政府 - 政务新闻",
        "region_province": "山东省", "region_city": "济南市", "region_district": "济阳区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.jiyang.gov.cn",
        "list_url": "https://www.jiyang.gov.cn/col/col16534/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市莱芜区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "莱芜区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.laiwu.gov.cn",
        "list_url": "http://www.laiwu.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市钢城区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "钢城区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.gangcheng.gov.cn",
        "list_url": "http://www.gangcheng.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市平阴县人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "平阴县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.pingyin.gov.cn",
        "list_url": "http://www.pingyin.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "济南市商河县人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "济南市", "region_district": "商河县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.shanghe.gov.cn",
        "list_url": "http://www.shanghe.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },

    # ===== 烟台市 9 区市（莱山/栖霞域名不通、福山为外省同名站，留待后续） =====
    {
        "name": "烟台市芝罘区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "芝罘区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.zhifu.gov.cn",
        "list_url": "http://www.zhifu.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市牟平区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "牟平区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.muping.gov.cn",
        "list_url": "http://www.muping.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市长岛县人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "长岛县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.changdao.gov.cn",
        "list_url": "http://www.changdao.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：政务新媒体矩阵栏目 10 条 / 10 有日期，https 可用
        "name": "烟台市龙口市人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "龙口市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.longkou.gov.cn",
        "list_url": "https://www.longkou.gov.cn/col/col49224/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市莱阳市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "莱阳市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.laiyang.gov.cn",
        "list_url": "http://www.laiyang.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市莱州市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "莱州市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.laizhou.gov.cn",
        "list_url": "http://www.laizhou.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "烟台市蓬莱市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "蓬莱市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.penglai.gov.cn",
        "list_url": "http://www.penglai.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：政务公开栏目 60 条 / 60 有日期，https 可用
        "name": "烟台市招远市人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "招远市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.zhaoyuan.gov.cn",
        "list_url": "https://www.zhaoyuan.gov.cn/col/col24052/index.html",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：政务新媒体栏目 12 条 / 12 有日期，https 可用
        "name": "烟台市海阳市人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "烟台市", "region_district": "海阳市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.haiyang.gov.cn",
        "list_url": "https://www.haiyang.gov.cn/col/col46328/index.html",
        "fetch_type": "html", "selector_config": {},
    },

    # ===== 潍坊市 12 区市 =====
    {
        "name": "潍坊市潍城区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "潍城区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.weicheng.gov.cn",
        "list_url": "http://www.weicheng.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：要闻动态栏目 8 条 / 8 有日期，https 可用
        "name": "潍坊市寒亭区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "寒亭区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.hanting.gov.cn",
        "list_url": "https://www.hanting.gov.cn/htywdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市坊子区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "坊子区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.fangzi.gov.cn",
        "list_url": "http://www.fangzi.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：要闻动态栏目 37 条 / 22 有日期，https 可用
        "name": "潍坊市奎文区人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "奎文区",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.kuiwen.gov.cn",
        "list_url": "https://www.kuiwen.gov.cn/kwqywdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：临朐动态栏目 37 条 / 37 有日期，https 可用
        "name": "潍坊市临朐县人民政府 - 临朐动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "临朐县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.linqu.gov.cn",
        "list_url": "https://www.linqu.gov.cn/lqdt",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市昌乐县人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "昌乐县",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.changle.gov.cn",
        "list_url": "http://www.changle.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市青州市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "青州市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.qingzhou.gov.cn",
        "list_url": "http://www.qingzhou.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市诸城市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "诸城市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.zhucheng.gov.cn",
        "list_url": "http://www.zhucheng.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        # Fetcher 实测：部门动态栏目 20 条 / 20 有日期，https 可用
        "name": "潍坊市寿光市人民政府 - 政务要闻",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "寿光市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "https://www.shouguang.gov.cn",
        "list_url": "https://www.shouguang.gov.cn/news/bmdt/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市安丘市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "安丘市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.anqiu.gov.cn",
        "list_url": "http://www.anqiu.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市高密市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "高密市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.gaomi.gov.cn",
        "list_url": "http://www.gaomi.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
    {
        "name": "潍坊市昌邑市人民政府 - 要闻动态",
        "region_province": "山东省", "region_city": "潍坊市", "region_district": "昌邑市",
        "region_org": "", "region_area": "", "level": "district",
        "base_url": "http://www.changyi.gov.cn",
        "list_url": "http://www.changyi.gov.cn/",
        "fetch_type": "html", "selector_config": {},
    },
]
