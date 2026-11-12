"""源站点配置：广东省 / 国家部委 / 港澳台地区 / 其他省级单位。首次启动时按名称幂等入库。

港澳台地区使用独立的 region_area 维度与 level="area"，不写 region_city，
避免污染广东省地市榜、趋势与周月报统计；标签一律采用规范表述。
其他省级单位定义在 province_sources.py，统一 level="province" + region_province，
广东省口径的统计会单独排除外省省级新闻。
"""
from __future__ import annotations

from .province_sources import PROVINCE_LABELS, PROVINCE_SOURCES  # noqa: F401

# 港澳台地区分组（固定展示顺序）。「港澳综合」收中央港澳工作部门的跨地区稿件。
AREA_LABELS = ("中国香港", "中国澳门", "中国台湾", "港澳综合")

SEED_SOURCES = [
    {
        "name": "广州市人民政府 - 广州要闻",
        "region_province": "广东省",
        "region_city": "广州市",
        "level": "city",
        "base_url": "https://www.gz.gov.cn",
        "list_url": "https://www.gz.gov.cn/xw/gzyw/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".content_article",
        },
    },
    {
        "name": "广州市人民政府 - 通知公告",
        "region_province": "广东省",
        "region_city": "广州市",
        "level": "city",
        "base_url": "https://www.gz.gov.cn",
        "list_url": "https://www.gz.gov.cn/xw/tzgg/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".content_article",
        },
    },
    {
        "name": "深圳市人民政府 - 政务动态",
        "region_province": "广东省",
        "region_city": "深圳市",
        "level": "city",
        "base_url": "https://www.sz.gov.cn",
        "list_url": "https://www.sz.gov.cn/cn/xxgk/zfxxgj/zwdt/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".news_cont_d_wrap, #ivs_content",
        },
    },
    {
        "name": "深圳市人民政府 - 通知公告",
        "region_province": "广东省",
        "region_city": "深圳市",
        "level": "city",
        "base_url": "https://www.sz.gov.cn",
        "list_url": "https://www.sz.gov.cn/cn/xxgk/zfxxgj/tzgg/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".news_cont_d_wrap, #ivs_content",
        },
    },
    {
        "name": "佛山市人民政府 - 今日聚焦",
        "region_province": "广东省",
        "region_city": "佛山市",
        "level": "city",
        "base_url": "https://www.foshan.gov.cn",
        "list_url": "https://www.foshan.gov.cn/zwgk/zwdt/jryw/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".TRS_Editor, .zoom, #zoom",
        },
    },
    {
        "name": "佛山市人民政府 - 部门动态",
        "region_province": "广东省",
        "region_city": "佛山市",
        "level": "city",
        "base_url": "https://www.foshan.gov.cn",
        "list_url": "https://www.foshan.gov.cn/zwgk/zwdt/bmdt/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": ".TRS_Editor, .zoom, #zoom",
        },
    },
    # ============ 一期 1.5 扩容：省级 + 其余地市（2026-11-05 自动探测验证） ============
    {
        "name": "广东省人民政府 - 要闻动态",
        "region_province": "广东省",
        "region_city": "",
        "level": "province",
        "base_url": "https://www.gd.gov.cn",
        "list_url": "https://www.gd.gov.cn/gdywdt/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "汕头市人民政府 - 汕头要闻",
        "region_province": "广东省", "region_city": "汕头市", "level": "city",
        "base_url": "https://www.shantou.gov.cn",
        "list_url": "https://www.shantou.gov.cn/cnst/ywdt/styw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "韶关市人民政府 - 韶关要闻",
        "region_province": "广东省", "region_city": "韶关市", "level": "city",
        "base_url": "https://www.sg.gov.cn",
        "list_url": "https://www.sg.gov.cn/xw/xwzx/bdxw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "湛江市人民政府 - 要闻",
        "region_province": "广东省", "region_city": "湛江市", "level": "city",
        "base_url": "https://www.zhanjiang.gov.cn",
        "list_url": "https://www.zhanjiang.gov.cn/yaowen/",
        "fetch_type": "html",
        "selector_config": {"item": "a[href*='/content/post_']"},
    },
    {
        "name": "肇庆市人民政府 - 肇庆要闻",
        "region_province": "广东省", "region_city": "肇庆市", "level": "city",
        "base_url": "https://www.zhaoqing.gov.cn",
        "list_url": "https://www.zhaoqing.gov.cn/xwzx/zqyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "江门市人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "江门市", "level": "city",
        "base_url": "https://www.jiangmen.gov.cn",
        "list_url": "https://www.jiangmen.gov.cn/home/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "茂名市人民政府 - 茂名要闻",
        "region_province": "广东省", "region_city": "茂名市", "level": "city",
        "base_url": "http://www.maoming.gov.cn",
        "list_url": "http://www.maoming.gov.cn/ywdt/rdyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": "#zoomcon, .zw, .TRS_Editor"},
    },
    {
        "name": "惠州市人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "惠州市", "level": "city",
        "base_url": "https://www.huizhou.gov.cn",
        "list_url": "https://www.huizhou.gov.cn/zwgk/hzsz/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "汕尾市人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "汕尾市", "level": "city",
        "base_url": "https://www.shanwei.gov.cn",
        "list_url": "https://www.shanwei.gov.cn/shanwei/zwgk/jcxx/zwdt/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "河源市人民政府 - 要闻动态",
        "region_province": "广东省", "region_city": "河源市", "level": "city",
        "base_url": "https://www.heyuan.gov.cn",
        "list_url": "https://www.heyuan.gov.cn/ywdt/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "阳江市人民政府 - 要闻动态",
        "region_province": "广东省", "region_city": "阳江市", "level": "city",
        "base_url": "https://www.yangjiang.gov.cn",
        "list_url": "https://www.yangjiang.gov.cn/yj/ywdt/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "清远市人民政府 - 动态要闻",
        "region_province": "广东省", "region_city": "清远市", "level": "city",
        "base_url": "https://www.qy.gov.cn",
        "list_url": "https://www.qy.gov.cn/qy/0400/list.shtml",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "东莞市人民政府 - 东莞要闻",
        "region_province": "广东省", "region_city": "东莞市", "level": "city",
        "base_url": "https://www.dg.gov.cn",
        "list_url": "https://www.dg.gov.cn/jjdz/dzyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": "#zoomcon, .zw, .TRS_Editor"},
    },
    {
        "name": "中山市人民政府 - 要闻动态",
        "region_province": "广东省", "region_city": "中山市", "level": "city",
        "base_url": "https://www.zs.gov.cn",
        "list_url": "https://www.zs.gov.cn/ywdt/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "潮州市人民政府 - 要闻动态",
        "region_province": "广东省", "region_city": "潮州市", "level": "city",
        "base_url": "https://www.chaozhou.gov.cn",
        "list_url": "https://www.chaozhou.gov.cn/ywdt/",
        "fetch_type": "html",
        "selector_config": {"item": "a[href*='/content/post_']", "content": ".detail_content"},
    },
    {
        "name": "揭阳市人民政府 - 揭阳新闻",
        "region_province": "广东省", "region_city": "揭阳市", "level": "city",
        "base_url": "http://www.jieyang.gov.cn",
        "list_url": "http://www.jieyang.gov.cn/xwdt/jyxw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "云浮市人民政府 - 云浮要闻",
        "region_province": "广东省", "region_city": "云浮市", "level": "city",
        "base_url": "https://www.yunfu.gov.cn",
        "list_url": "https://www.yunfu.gov.cn/zxzx/yfyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "珠海市人民政府 - 珠海要闻",
        "region_province": "广东省", "region_city": "珠海市", "level": "city",
        "base_url": "https://www.zhuhai.gov.cn",
        "list_url": "https://www.zhuhai.gov.cn/xw/xwzx/zhyw/index.html",
        "fetch_type": "json",
        "selector_config": {
            "list_api": "https://www.zhuhai.gov.cn/postmeta/i/4013.json",
            "content": "#new_zh .nr, .xlcontent, .article-content, .TRS_Editor",
        },
    },
    {
        "name": "珠海市人民政府 - 各区动态",
        "region_province": "广东省", "region_city": "珠海市", "level": "city",
        "base_url": "https://www.zhuhai.gov.cn",
        "list_url": "https://www.zhuhai.gov.cn/xw/xwzx/gqdt/index.html",
        "fetch_type": "json",
        "selector_config": {
            "list_api": "https://www.zhuhai.gov.cn/postmeta/i/4012.json",
            "content": "#new_zh .nr, .xlcontent, .article-content, .TRS_Editor",
        },
    },
    # 梅州：站点挂创宇盾 JS 挑战（521），waf.py 用 quickjs 解通行 cookie 后接入
    {
        "name": "梅州市人民政府 - 梅州开新局",
        "region_province": "广东省",
        "region_city": "梅州市",
        "level": "city",
        "base_url": "https://www.meizhou.gov.cn",
        "list_url": "https://www.meizhou.gov.cn/zwgk/gzdt/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": "#show_con, .show_con, #container",
        },
    },
    {
        "name": "梅州市人民政府 - 部门动态",
        "region_province": "广东省",
        "region_city": "梅州市",
        "level": "city",
        "base_url": "https://www.meizhou.gov.cn",
        "list_url": "https://www.meizhou.gov.cn/zwgk/gzdt/bmdt/index.html",
        "fetch_type": "html",
        "selector_config": {
            "item": "a[href*='/content/post_']",
            "content": "#show_con, .show_con, #container",
        },
    },
    # ============ 广州市 11 个区（2026-11-08 逐站探测 + 详情页实测） ============
    # 区级源统一 region_city=广州市 + region_district=XX区 + level=district。
    # 判重第 2 层已按 (city, district) 收窄，避免各区转发同一篇市/中央通稿时互相误杀。
    # 越秀/南沙/增城的正文容器不在通用兜底里，必须显式配置 content。
    {
        "name": "广州市越秀区人民政府 - 越秀快讯",
        "region_province": "广东省", "region_city": "广州市", "region_district": "越秀区",
        "level": "district",
        "base_url": "https://www.yuexiu.gov.cn",
        "list_url": "https://www.yuexiu.gov.cn/yxdt/yxkx/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": ".conNews, .con"},
    },
    {
        "name": "广州市海珠区人民政府 - 海珠要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "海珠区",
        "level": "district",
        "base_url": "https://www.haizhu.gov.cn",
        "list_url": "https://www.haizhu.gov.cn/hzdt/hzyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市荔湾区人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "荔湾区",
        "level": "district",
        "base_url": "https://www.lw.gov.cn",
        "list_url": "https://www.lw.gov.cn/ywdt/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市天河区人民政府 - 天河要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "天河区",
        "level": "district",
        "base_url": "https://www.thnet.gov.cn",
        "list_url": "https://www.thnet.gov.cn/thdt/thyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": ".article-content, #zoomcon"},
    },
    {
        "name": "广州市白云区人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "白云区",
        "level": "district",
        "base_url": "https://www.by.gov.cn",
        "list_url": "https://www.by.gov.cn/ywdt/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市黄埔区人民政府 - 政务要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "黄埔区",
        "level": "district",
        "base_url": "https://www.hp.gov.cn",
        "list_url": "https://www.hp.gov.cn/xwzx/zwyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市花都区人民政府 - 花都新闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "花都区",
        "level": "district",
        "base_url": "https://www.huadu.gov.cn",
        "list_url": "https://www.huadu.gov.cn/hdzx/hdxw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市番禺区人民政府 - 番禺新闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "番禺区",
        "level": "district",
        "base_url": "https://www.panyu.gov.cn",
        # 番禺把新闻挂在「政府信息公开目录 > 政务动态 > 番禺新闻」下，
        # 首页的 /gkmlpt/index#7523 是 JS 渲染，静态列表页才是这个路径。
        "list_url": "https://www.panyu.gov.cn/zwgk/zfxxgkml/xxgkml/zwdt/fzxw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市南沙区人民政府 - 南沙要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "南沙区",
        "level": "district",
        "base_url": "https://www.gzns.gov.cn",
        "list_url": "https://www.gzns.gov.cn/nsdt/nsyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": "#zoomcon, .xl-nr"},
    },
    {
        "name": "广州市从化区人民政府 - 从化要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "从化区",
        "level": "district",
        "base_url": "https://www.conghua.gov.cn",
        "list_url": "https://www.conghua.gov.cn/zwgk/chyw/index.html",
        "fetch_type": "html",
        "selector_config": {"item": "a"},
    },
    {
        "name": "广州市增城区人民政府 - 增城要闻",
        "region_province": "广东省", "region_city": "广州市", "region_district": "增城区",
        "level": "district",
        "base_url": "https://www.zc.gov.cn",
        "list_url": "https://www.zc.gov.cn/zx/zcyw/index.html",
        "fetch_type": "html",
        # 列表页 href 带前导空格，base.py 已 strip；正文容器是 .detailCon
        "selector_config": {"item": "a", "content": ".detailCon, .tyxl_nr_con"},
    },
    # ============ 国家部委 / 国务院机构（2026-11-08 逐站探测 + 临时库全链路实测） ============
    # 统一 level=national + region_province=全国 + region_city/district 为空 + region_org=机构简称。
    # 判重第 2 层按 (level, city, district) 收窄：国家级各机构共享一个命名空间，
    # 十几个部委站同时转载的中央通稿只保留最先抓到的那条，省下大量 AI 额度。
    #
    # 部委站与地市站的三点显著差异，已在 base.py 里做成通用能力：
    #   1) 大量文章 URL 以 .htm 结尾（财政部/农业农村部/中国政府网）；
    #   2) 人民银行把每篇文章放在 /<14位时间戳>/index.html，不能当栏目首页排除；
    #   3) 列表页普遍不显示日期，靠 URL 里的日期 + 详情页 meta PubDate 兜底。
    {
        "name": "中国政府网 - 要闻",
        "region_province": "全国", "region_city": "", "region_org": "中国政府网",
        "level": "national",
        "base_url": "https://www.gov.cn",
        # 列表页 /yaowen/liebiao/ 是 ajax 空壳，真正的 400 条带日期清单在这个静态 JSON
        "list_url": "https://www.gov.cn/yaowen/liebiao/",
        "fetch_type": "json",
        "selector_config": {"list_api": "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json"},
    },
    {
        "name": "中国政府网 - 国务院政策",
        "region_province": "全国", "region_city": "", "region_org": "中国政府网",
        "level": "national",
        "base_url": "https://www.gov.cn",
        "list_url": "https://www.gov.cn/",
        "fetch_type": "html",
        "selector_config": {"item": "a[href*='/zhengce/content/']"},
    },
    {
        "name": "国家发展改革委 - 新闻发布",
        "region_province": "全国", "region_city": "", "region_org": "国家发展改革委",
        "level": "national",
        "base_url": "https://www.ndrc.gov.cn",
        "list_url": "https://www.ndrc.gov.cn/xwdt/xwfb/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "工业和信息化部 - 工信动态",
        "region_province": "全国", "region_city": "", "region_org": "工业和信息化部",
        "level": "national",
        "base_url": "https://www.miit.gov.cn",
        # 栏目页是 CMS 的 JS 空壳（只有 11 个 a 标签），首页才有静态文章链接
        "list_url": "https://www.miit.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/art/']"},
    },
    {
        "name": "财政部 - 财政新闻",
        "region_province": "全国", "region_city": "", "region_org": "财政部",
        "level": "national",
        "base_url": "https://www.mof.gov.cn",
        "list_url": "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/",
        "fetch_type": "html",
        # 本部文章是 ./202611/t...htm 相对链接；其余是各地监管局子站，用前缀排除
        "selector_config": {"item": "a[href^='./']"},
    },
    {
        "name": "教育部 - 工作动态",
        "region_province": "全国", "region_city": "", "region_org": "教育部",
        "level": "national",
        "base_url": "https://www.moe.gov.cn",
        "list_url": "https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "科学技术部 - 科技动态",
        "region_province": "全国", "region_city": "", "region_org": "科学技术部",
        "level": "national",
        "base_url": "https://www.most.gov.cn",
        "list_url": "https://www.most.gov.cn/kjbgz/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "民政部 - 民政要闻",
        "region_province": "全国", "region_city": "", "region_org": "民政部",
        "level": "national",
        "base_url": "https://www.mca.gov.cn",
        "list_url": "https://www.mca.gov.cn/n152/n164/index.html",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "自然资源部 - 动态",
        "region_province": "全国", "region_city": "", "region_org": "自然资源部",
        "level": "national",
        "base_url": "https://www.mnr.gov.cn",
        "list_url": "https://www.mnr.gov.cn/dt/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "生态环境部 - 环境要闻",
        "region_province": "全国", "region_city": "", "region_org": "生态环境部",
        "level": "national",
        "base_url": "https://www.mee.gov.cn",
        "list_url": "https://www.mee.gov.cn/ywdt/hjywnews/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "住房城乡建设部 - 建设要闻",
        "region_province": "全国", "region_city": "", "region_org": "住房城乡建设部",
        "level": "national",
        "base_url": "https://www.mohurd.gov.cn",
        # 栏目页同样是 CMS 空壳，用首页静态链接
        "list_url": "https://www.mohurd.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/xinwen/']"},
    },
    {
        "name": "交通运输部 - 交通要闻",
        "region_province": "全国", "region_city": "", "region_org": "交通运输部",
        "level": "national",
        "base_url": "https://www.mot.gov.cn",
        "list_url": "https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "农业农村部 - 部动态",
        "region_province": "全国", "region_city": "", "region_org": "农业农村部",
        "level": "national",
        "base_url": "https://www.moa.gov.cn",
        "list_url": "https://www.moa.gov.cn/xw/zwdt/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "商务部 - 新闻发布",
        "region_province": "全国", "region_city": "", "region_org": "商务部",
        "level": "national",
        "base_url": "https://www.mofcom.gov.cn",
        "list_url": "https://www.mofcom.gov.cn/xwfb/index.html",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "应急管理部 - 要闻",
        "region_province": "全国", "region_city": "", "region_org": "应急管理部",
        "level": "national",
        "base_url": "https://www.mem.gov.cn",
        "list_url": "https://www.mem.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "中国人民银行 - 新闻发布",
        "region_province": "全国", "region_city": "", "region_org": "中国人民银行",
        "level": "national",
        "base_url": "http://www.pbc.gov.cn",
        "list_url": "http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
        "fetch_type": "html", "selector_config": {"item": "a[href*='113469/']"},
    },
    {
        "name": "国家税务总局 - 税务新闻",
        "region_province": "全国", "region_city": "", "region_org": "国家税务总局",
        "level": "national",
        "base_url": "https://www.chinatax.gov.cn",
        "list_url": "https://www.chinatax.gov.cn/chinatax/n810219/n810724/common_list_swxw.html",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "市场监管总局 - 新闻总览",
        "region_province": "全国", "region_city": "", "region_org": "市场监管总局",
        "level": "national",
        "base_url": "https://www.samr.gov.cn",
        "list_url": "https://www.samr.gov.cn/xw/index.html",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/xw/']"},
    },
    {
        "name": "中国证监会 - 要闻",
        "region_province": "全国", "region_city": "", "region_org": "中国证监会",
        "level": "national",
        "base_url": "https://www.csrc.gov.cn",
        "list_url": "https://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "国家统计局 - 统计新闻",
        "region_province": "全国", "region_city": "", "region_org": "国家统计局",
        "level": "national",
        "base_url": "https://www.stats.gov.cn",
        "list_url": "https://www.stats.gov.cn/xw/tjxw/",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        "name": "国家能源局 - 能源要闻",
        "region_province": "全国", "region_city": "", "region_org": "国家能源局",
        "level": "national",
        "base_url": "https://www.nea.gov.cn",
        # /xwzx/nyyw.htm 是 Vue 空壳，首页的 /c.html 才是静态文章链接
        "list_url": "https://www.nea.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/c.html']"},
    },
    {
        "name": "国家医保局 - 医保动态",
        "region_province": "全国", "region_city": "", "region_org": "国家医保局",
        "level": "national",
        "base_url": "https://www.nhsa.gov.cn",
        # /col/col14/index.html 是 urite JS 空壳，用首页静态 art 链接
        "list_url": "https://www.nhsa.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/art/']"},
    },
    {
        "name": "国家数据局 - 数据要闻",
        "region_province": "全国", "region_city": "", "region_org": "国家数据局",
        "level": "national",
        "base_url": "https://www.nda.gov.cn",
        "list_url": "https://www.nda.gov.cn/sjj/index_pc.html",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/sjj/']"},
    },

    # ---- 二次攻坚：原先被 WAF / 自签证书 / JS 列表挡住的 5 家机构 ----
    {
        # 创宇盾新版 412（$_ts 动态 VM），由 waf.solve_wzws 用本机 Chrome headless 预热
        "name": "国家卫生健康委员会 - 新闻动态",
        "region_province": "全国", "region_city": "", "region_org": "国家卫生健康委",
        "level": "national",
        "base_url": "https://www.nhc.gov.cn",
        "list_url": "https://www.nhc.gov.cn/wjw/xwdt/list.shtml",
        "fetch_type": "html", "selector_config": {"item": "a", "content": ".con"},
    },
    {
        "name": "国家药品监督管理局 - 药监动态",
        "region_province": "全国", "region_city": "", "region_org": "国家药监局",
        "level": "national",
        "base_url": "https://www.nmpa.gov.cn",
        "list_url": "https://www.nmpa.gov.cn/yaowen/ypjgyw/index.html",
        "fetch_type": "html", "selector_config": {"item": "a"},
    },
    {
        # 首页返回 200 但正文只有 EO_Bot_Ssid 挑战 JS，waf.solve_eo 用 quickjs 解
        "name": "人力资源和社会保障部 - 部内要闻",
        "region_province": "全国", "region_city": "", "region_org": "人力资源社会保障部",
        "level": "national",
        "base_url": "https://www.mohrss.gov.cn",
        "list_url": "https://www.mohrss.gov.cn/SYrlzyhshbzb/dongtaixinwen/buneiyaowen/",
        "fetch_type": "html",
        "selector_config": {"item": "a", "content": ".TRS_Editor"},
    },
    {
        # 详情页 ItemDetail.html 是 Vue 空壳，列表与正文都走 cbircweb JSON 接口
        "name": "国家金融监督管理总局 - 监管动态",
        "region_province": "全国", "region_city": "", "region_org": "金融监管总局",
        "level": "national",
        "base_url": "https://www.nfra.gov.cn",
        "list_url": ("https://www.nfra.gov.cn/cbircweb/DocInfo/"
                     "SelectDocByItemIdAndChild?itemId=915&pageSize=18&pageIndex=1"),
        "fetch_type": "json",
        "selector_config": {
            "url_template": ("https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html"
                             "?docId={docId}&itemId=915&generaltype=0"),
            "detail_api_template": ("https://www.nfra.gov.cn/cbircweb/DocInfo/"
                                    "SelectByDocId?docId={docId}"),
        },
    },
    {
        # 2026-11-10 复查结论（此前误判为"网络策略未放行"）：
        #   该站挂在创宇云防御后面，且边缘节点回源持续 502/504（"连接超时/服务器状态未知"），
        #   即源站本身当前不可达；http 明文稳定回 412 瑞数挑战（识别条件与 is_wzws_challenge
        #   完全匹配，waf.solve_wzws 可解），但多重探测后本机 IP 已被 WAF 升级为 403。
        #   结论：故障在对方服务端，代码侧无法启用；站点恢复后按 README「海关总署」行
        #   的步骤重测，通过后把 enabled 改成 True 即可。
        "name": "海关总署 - 要闻",
        "region_province": "全国", "region_city": "", "region_org": "海关总署",
        "level": "national",
        "base_url": "http://www.customs.gov.cn",
        "list_url": "http://www.customs.gov.cn/",
        "fetch_type": "html", "selector_config": {"item": "a[href*='/customs/']"},
        "enabled": False,
    },

    # ===== 港澳台地区（2026-11-12 接入）=====
    # 统一约束：
    #   * level="area" + region_area=规范地区名，region_province/city/district/org 全部留空，
    #     不参与广东省地市榜、趋势矩阵与周月报的「广东省」口径；
    #   * 只采集大陆官方渠道（中央港澳办、驻港/驻澳联络办、中央台办），
    #     不接入境外站点，也不与「国家部委」层级并列；
    #   * skip_ai=True：这批稿件默认不做 AI 解读，避免模型对敏感表述拒答后
    #     堆积 failed 终态；原文、标题、日期与列表展示均不受影响。
    {
        "name": "中共中央港澳办/国务院港澳办 - 时政要闻",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "港澳综合", "level": "area",
        "base_url": "https://www.hmo.gov.cn",
        "list_url": "https://www.hmo.gov.cn/szyw/index.shtml",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中央政府驻香港特别行政区联络办公室 - 港澳要闻",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国香港", "level": "area",
        "base_url": "https://www.locpg.gov.cn",
        "list_url": "https://www.locpg.gov.cn/gayw/index.htm",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中央政府驻香港特别行政区联络办公室 - 最新消息",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国香港", "level": "area",
        "base_url": "https://www.locpg.gov.cn",
        "list_url": "https://www.locpg.gov.cn/zxxx/index.htm",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中央政府驻澳门特别行政区联络办公室 - 我办要闻",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国澳门", "level": "area",
        "base_url": "https://www.zlb.gov.cn",
        "list_url": "https://www.zlb.gov.cn/wbyw.htm",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中央政府驻澳门特别行政区联络办公室 - 新闻中心",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国澳门", "level": "area",
        "base_url": "https://www.zlb.gov.cn",
        "list_url": "https://www.zlb.gov.cn/zysy.htm",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中共中央台办/国务院台办 - 新闻动态",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国台湾", "level": "area",
        # 国台办列表页为 GB2312，Fetcher._decode 统一按 GB18030 解码
        "base_url": "https://www.gwytb.gov.cn",
        "list_url": "https://www.gwytb.gov.cn/xwdt/",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
    {
        "name": "中共中央台办/国务院台办 - 最新发布",
        "region_province": "", "region_city": "", "region_district": "", "region_org": "",
        "region_area": "中国台湾", "level": "area",
        "base_url": "https://www.gwytb.gov.cn",
        "list_url": "https://www.gwytb.gov.cn/zxfb/",
        "fetch_type": "html",
        "selector_config": {"item": "a", "skip_ai": True},
    },
]

# ===== 广东以外省级行政单位（2026-11-13 接入，27 启用 / 3 待接入）=====
# 单独放一个模块，避免本文件继续随扩源线性膨胀；seed_sources() 按 name 幂等入库。
SEED_SOURCES.extend(PROVINCE_SOURCES)
