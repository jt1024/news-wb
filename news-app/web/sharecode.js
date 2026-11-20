/* 发布沙箱网关要求每个 /api/ 请求带 sharecode 查询参数，否则返回 403「链接不完整」。
 * 前端各处 fetch 用的是相对路径，网关不会自动补参数，故在此统一注入：
 *   1) 从当前 URL 读取 sharecode 并持久化（登录/导航跳转后 URL 会丢失，故必须存起来）；
 *   2) 包装 window.fetch，对同源 /api/ 请求自动补上 sharecode 参数。
 * 本地直连（无 sharecode）时不注入，行为与原来完全一致。
 */
(function () {
  try {
    var params = new URLSearchParams(window.location.search);
    var sc = params.get("sharecode");
    if (sc) {
      localStorage.setItem("nb_sharecode", sc);
    } else {
      sc = localStorage.getItem("nb_sharecode") || "";
    }
    if (!sc) return; // 本地环境：不打补丁

    var rawFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      var url;
      if (input instanceof Request) {
        url = new URL(input.url, window.location.origin);
      } else if (typeof input === "string") {
        url = new URL(input, window.location.origin);
      } else {
        return rawFetch(input, init);
      }
      // 只处理同源的 /api/ 请求，外部 URL（如静态资源）原样放行
      if (url.origin === window.location.origin && url.pathname.indexOf("/api/") === 0
          && !url.searchParams.has("sharecode")) {
        url.searchParams.set("sharecode", sc);
        if (input instanceof Request) {
          input = new Request(url.toString(), input);
        } else {
          input = url.pathname + url.search + url.hash;
        }
      }
      return rawFetch(input, init);
    };

    // 页面内部跳转保留 sharecode，避免登录/返回后 URL 丢参数导致网关拦截
    var rawAssign = window.location.assign.bind(window.location);
    window.location.assign = function (u) { return rawAssign(withSC(u)); };
    var rawReplace = window.location.replace.bind(window.location);
    window.location.replace = function (u) { return rawReplace(withSC(u)); };
    function withSC(u) {
      if (typeof u !== "string" || u.charAt(0) !== "/") return u;
      var x = new URL(u, window.location.origin);
      if (!x.searchParams.has("sharecode")) x.searchParams.set("sharecode", sc);
      return x.pathname + x.search + x.hash;
    }
  } catch (e) {
    // 补丁失败不应影响页面基本功能
    console.warn("sharecode patch skipped:", e);
  }
})();
