const state = {
  dashboard: null,
  activePage: "home",
  activeRouteId: "",
  settingsTab: "server",
  globalDraft: {
    subscription_url: "",
    export_host: "",
    allowed_c_ports: "",
  },
  routeDraft: null,
  routeDraftId: "",
  testPrefs: {
    test_url: "",
    timeout_ms: 5000,
  },
  aProxies: [],
  aSelectedProxy: "",
  aProxyMetrics: {},
  aProxyQuery: "",
  landingMetrics: {},
  gatewayMetrics: {},
  landingPreview: null,
  exportFormat: "socks5_uri",
  landingSearch: "",
  exportSearch: "",
  pendingOperation: null,
  lastLogRefreshAt: "",
  toastTimer: null,
};

const PAGE_META = {
  home: {
    title: "首页",
    subtitle: "先看清楚这套工具的结构和当前状态，再按 A 订阅、B 落地、C 输出和设置这四类工作逐步操作。",
  },
  dashboard: {
    title: "仪表盘",
    subtitle: "用全局视角看共享订阅 A 是否就绪、B 落地是否可连，以及哪些 C 已经能对外设备直接使用。",
  },
  subscription: {
    title: "Ai订阅管理",
    subtitle: "先录入共享订阅 A，再单独检查节点状态、延迟和可用性，这一步不依赖任何 B。",
  },
  landings: {
    title: "B落地列表",
    subtitle: "这里专门管理多条路由对应的 B 落地信息，并批量判断哪些落地本身就能直接连通。",
  },
  exports: {
    title: "C输出列表",
    subtitle: "这里专门处理 C 的导出格式、复制链接、A 节点应用和外网诊断，不再和 B 录入混在一起。",
  },
  settings: {
    title: "设置",
    subtitle: "集中处理服务器设置、核心管理和运行日志，不把系统级配置分散在多个页面里。",
  },
};

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setText(id, value) {
  const element = byId(id);
  if (element) {
    element.textContent = value ?? "-";
  }
}

function setValue(id, value) {
  const element = byId(id);
  if (!element) {
    return;
  }
  if (document.activeElement === element) {
    return;
  }
  element.value = value ?? "";
}

function showToast(message, isError = false) {
  const toast = byId("toast");
  if (!toast) {
    return;
  }

  toast.textContent = message;
  toast.style.background = isError ? "rgba(167, 40, 78, 0.96)" : "rgba(19, 14, 78, 0.94)";
  toast.classList.remove("hidden");

  if (state.toastTimer) {
    window.clearTimeout(state.toastTimer);
  }

  state.toastTimer = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 3200);
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  try {
    const copied = document.execCommand("copy");
    if (!copied) {
      throw new Error("当前浏览器环境不支持自动复制，请手动复制。");
    }
  } finally {
    document.body.removeChild(textarea);
  }
}

function defaultTestUrl() {
  return document.body.dataset.defaultTestUrl || "https://api.ipify.org";
}

function defaultTimeoutMs() {
  return Number(document.body.dataset.defaultTimeoutMs || 5000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    credentials: "same-origin",
    body: options.body,
  });

  const payload = await response.json();
  if (!payload.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

function setBusy(trigger, loading, text = "处理中...") {
  if (!trigger) {
    return;
  }
  if (loading) {
    trigger.classList.add("is-loading");
    if (trigger.tagName === "BUTTON") {
      if (!trigger.dataset.originalText) {
        trigger.dataset.originalText = trigger.textContent;
      }
      trigger.textContent = text;
      trigger.disabled = true;
    }
    return;
  }

  trigger.classList.remove("is-loading");
  if (trigger.tagName === "BUTTON") {
    if (trigger.dataset.originalText) {
      trigger.textContent = trigger.dataset.originalText;
      delete trigger.dataset.originalText;
    }
    trigger.disabled = false;
  }
}

async function runExclusiveAction({ label, trigger = null, loadingText = "处理中..." }, handler) {
  if (state.pendingOperation) {
    showToast(`请等待“${state.pendingOperation.label}”完成后再试。`, true);
    return;
  }

  state.pendingOperation = { label };
  setBusy(trigger, true, loadingText);

  try {
    return await handler();
  } finally {
    setBusy(trigger, false, loadingText);
    state.pendingOperation = null;
  }
}

function normalizePage(page) {
  return Object.prototype.hasOwnProperty.call(PAGE_META, page) ? page : "home";
}

function normalizeSettingsTab(tab) {
  return ["server", "core", "logs"].includes(tab) ? tab : "server";
}

function setActivePage(page, updateHash = true) {
  state.activePage = normalizePage(page);
  document.querySelectorAll(".page-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `page-${state.activePage}`);
  });
  document.querySelectorAll(".nav-card").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.activePage);
  });

  const meta = PAGE_META[state.activePage];
  setText("page-title", meta.title);
  setText("page-subtitle", meta.subtitle);

  if (updateHash) {
    window.location.hash = state.activePage;
  }
}

function setSettingsTab(tab) {
  state.settingsTab = normalizeSettingsTab(tab);
  document.querySelectorAll(".settings-nav").forEach((button) => {
    button.classList.toggle("active", button.dataset.settingsTab === state.settingsTab);
  });
  document.querySelectorAll(".settings-pane").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `settings-pane-${state.settingsTab}`);
  });
}

function appSettings() {
  return state.dashboard?.app_settings || {};
}

function routes() {
  return state.dashboard?.routes || [];
}

function routeStatuses() {
  return state.dashboard?.route_statuses || {};
}

function inspectorStatus() {
  return state.dashboard?.a_inspector || {};
}

function activeRoute() {
  return routes().find((route) => route.route_id === state.activeRouteId) || null;
}

function activeStatus() {
  return routeStatuses()[state.activeRouteId] || null;
}

function buildRouteDraft(route) {
  if (!route) {
    return null;
  }
  return {
    route_id: route.route_id,
    name: route.name || "",
    landing_socks_url: route.landing_socks_url || "",
    landing_host: route.landing_host || "",
    landing_port: route.landing_port || "",
    landing_username: route.landing_username || "",
    landing_password: route.landing_password || "",
    listen_host: route.listen_host || "0.0.0.0",
    listen_port: route.listen_port || "",
    gateway_username: route.gateway_username || "",
    gateway_password: route.gateway_password || "",
    controller_port: route.controller_port || "",
    selected_proxy: route.selected_proxy || "",
  };
}

function syncDrafts(force = false) {
  const settings = appSettings();
  state.globalDraft = {
    subscription_url: settings.subscription_url || state.globalDraft.subscription_url || "",
    export_host: force ? settings.export_host || "" : state.globalDraft.export_host || settings.export_host || "",
    allowed_c_ports: force ? settings.allowed_c_ports || "" : state.globalDraft.allowed_c_ports || settings.allowed_c_ports || "",
  };

  const route = activeRoute();
  if (!route) {
    state.routeDraft = null;
    state.routeDraftId = "";
    return;
  }
  if (force || !state.routeDraft || state.routeDraftId !== route.route_id) {
    state.routeDraft = buildRouteDraft(route);
    state.routeDraftId = route.route_id;
  }

  if (!state.testPrefs.test_url) {
    state.testPrefs.test_url = defaultTestUrl();
    state.testPrefs.timeout_ms = defaultTimeoutMs();
  }

  syncSelectedProxy(true);
}

function syncSelectedProxy(force = false) {
  const route = activeRoute();
  const status = activeStatus();
  const preferred = status?.current_proxy || route?.selected_proxy || state.routeDraft?.selected_proxy || "";
  const invalidSelection = state.aProxies.length > 0 && state.aSelectedProxy && !state.aProxies.includes(state.aSelectedProxy);
  if (force || !state.aSelectedProxy || invalidSelection) {
    state.aSelectedProxy = preferred || state.aProxies[0] || "";
  }
}

function pruneMetrics() {
  const validIds = new Set(routes().map((route) => route.route_id));
  state.landingMetrics = Object.fromEntries(Object.entries(state.landingMetrics).filter(([routeId]) => validIds.has(routeId)));
  state.gatewayMetrics = Object.fromEntries(Object.entries(state.gatewayMetrics).filter(([routeId]) => validIds.has(routeId)));
}

function formatHostForUri(host) {
  const safeHost = String(host || "").trim();
  if (safeHost.includes(":") && !safeHost.startsWith("[") && !safeHost.endsWith("]")) {
    return `[${safeHost}]`;
  }
  return safeHost;
}

function formatEndpoint(host, port) {
  if (!host || !port) {
    return "-";
  }
  return `${formatHostForUri(host)}:${port}`;
}

function currentExportHost() {
  return state.globalDraft.export_host?.trim() || appSettings().export_host || "";
}

function currentWebUiPort() {
  if (window.location.port) {
    return window.location.port;
  }
  return window.location.protocol === "https:" ? "443" : "80";
}

function currentWebUiEntry() {
  return `${window.location.protocol}//${window.location.host}/`;
}

function currentCPortPool() {
  return state.globalDraft.allowed_c_ports?.trim() || appSettings().allowed_c_ports || "10808-10999";
}

function importLinkForRoute(route, format = state.exportFormat) {
  if (!route) {
    return "";
  }
  const host = currentExportHost();
  if (!host || !route.listen_port) {
    return "";
  }

  const encodedUser = encodeURIComponent(route.gateway_username || "");
  const encodedPassword = encodeURIComponent(route.gateway_password || "");
  const hostForUri = formatHostForUri(host);

  switch (format) {
    case "socks_uri":
      return `socks://${encodedUser}:${encodedPassword}@${hostForUri}:${route.listen_port}`;
    case "socks5h_uri":
      return `socks5h://${encodedUser}:${encodedPassword}@${hostForUri}:${route.listen_port}`;
    case "host_port_user_pass":
      return `${hostForUri}:${route.listen_port}:${route.gateway_username}:${route.gateway_password}`;
    case "user_pass_at_host_port":
      return `${route.gateway_username}:${route.gateway_password}@${hostForUri}:${route.listen_port}`;
    default:
      return `socks5://${encodedUser}:${encodedPassword}@${hostForUri}:${route.listen_port}`;
  }
}

function routeRuntimeLabel(status) {
  return status?.running ? "运行中" : "未运行";
}

function controllerLabel(ready) {
  return ready ? "已就绪" : "未就绪";
}

function currentRouteProxyName(routeId) {
  const route = routes().find((item) => item.route_id === routeId);
  const status = routeStatuses()[routeId] || {};
  return status.current_proxy || status.selected_proxy || route?.selected_proxy || "-";
}

function routeSortValue(route) {
  return `${route.route_id === state.activeRouteId ? "0" : "1"}-${route.name || route.route_id}`;
}

function sortedRoutes() {
  return [...routes()].sort((a, b) => routeSortValue(a).localeCompare(routeSortValue(b), "zh-CN"));
}

function matchesRouteQuery(route, query) {
  const text = query.trim().toLowerCase();
  if (!text) {
    return true;
  }
  const haystack = [
    route.name,
    route.landing_host,
    String(route.landing_port || ""),
    route.gateway_username,
    route.gateway_password,
    currentRouteProxyName(route.route_id),
    formatEndpoint(currentExportHost(), route.listen_port),
    importLinkForRoute(route),
  ].join(" ").toLowerCase();
  return haystack.includes(text);
}

function landingMetric(routeId) {
  return state.landingMetrics[routeId] || null;
}

function gatewayMetric(routeId) {
  return state.gatewayMetrics[routeId] || null;
}

function connectivityResult(metric) {
  return metric?.connectivity || {
    alive: Boolean(metric?.alive),
    delay: metric?.delay ?? null,
    status_text: metric?.status_text || "",
  };
}

function lookupResult(metric) {
  return metric?.ip_lookup || {
    alive: Boolean(metric?.ip_profile?.exit_ip),
    status_text: metric?.ip_profile?.exit_ip ? "已获取" : "",
    exit_ip: metric?.ip_profile?.exit_ip || "",
    ip_profile: metric?.ip_profile || {},
  };
}

function landingStatusText(routeId) {
  const metric = landingMetric(routeId);
  if (!metric) {
    return "未测试";
  }
  return metric.status_text || (metric.alive ? "可用" : "不可用");
}

function gatewayConnectivityText(routeId) {
  const metric = gatewayMetric(routeId);
  const status = routeStatuses()[routeId];
  if (!metric) {
    return status?.running ? "未测试" : "未运行";
  }
  const connectivity = connectivityResult(metric);
  return connectivity.status_text || (connectivity.alive ? "可用" : "不可用");
}

function gatewayDelayText(routeId) {
  const metric = gatewayMetric(routeId);
  const connectivity = connectivityResult(metric);
  return Number.isInteger(connectivity?.delay) ? `${connectivity.delay} ms` : "-";
}

function gatewayLookupText(routeId) {
  const metric = gatewayMetric(routeId);
  if (!metric) {
    return "未测试";
  }
  const lookup = lookupResult(metric);
  return lookup.status_text || (lookup.alive ? "已获取" : "未获取");
}

function gatewayExitIpText(routeId) {
  const metric = gatewayMetric(routeId);
  if (!metric) {
    return "-";
  }
  const lookup = lookupResult(metric);
  return lookup.exit_ip || metric?.ip_profile?.exit_ip || "-";
}

function metricIpProfile(metric) {
  return lookupResult(metric)?.ip_profile || metric?.ip_profile || {};
}

const COUNTRY_ZH_MAP = {
  CN: "中国",
  China: "中国",
  HK: "香港",
  "Hong Kong": "香港",
  MO: "澳门",
  Macau: "澳门",
  TW: "台湾",
  Taiwan: "台湾",
  JP: "日本",
  Japan: "日本",
  KR: "韩国",
  "South Korea": "韩国",
  Korea: "韩国",
  SG: "新加坡",
  Singapore: "新加坡",
  MY: "马来",
  Malaysia: "马来",
  TH: "泰国",
  Thailand: "泰国",
  VN: "越南",
  Vietnam: "越南",
  PH: "菲律宾",
  Philippines: "菲律宾",
  ID: "印尼",
  Indonesia: "印尼",
  US: "美国",
  "United States": "美国",
  CA: "加拿大",
  Canada: "加拿大",
  GB: "英国",
  "United Kingdom": "英国",
  DE: "德国",
  Germany: "德国",
  FR: "法国",
  France: "法国",
  NL: "荷兰",
  Netherlands: "荷兰",
};

const PLACE_ZH_MAP = {
  Batam: "巴淡",
  Sekupang: "廖内",
  Singapore: "新加坡",
  "Hong Kong": "香港",
  Tokyo: "东京",
  Osaka: "大阪",
  Seoul: "首尔",
  Busan: "釜山",
  Jakarta: "雅加达",
  Taipei: "台北",
  Taichung: "台中",
  Kaohsiung: "高雄",
  "Kuala Lumpur": "吉隆坡",
  Bangkok: "曼谷",
  Manila: "马尼拉",
  "Los Angeles": "洛杉矶",
  "San Jose": "圣何塞",
  "New York": "纽约",
  California: "加州",
  "Riau Islands": "廖内群岛",
};

function shortCountryZh(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return COUNTRY_ZH_MAP[text] || text;
}

function shortPlaceZh(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return PLACE_ZH_MAP[text] || text;
}

function chineseLocationFromProfile(profile) {
  const raw = String(profile?.location || "").trim();
  if (!raw) {
    return "";
  }
  const zhTokens = raw.split(/\s+/).filter((token) => /[\u4e00-\u9fff]/.test(token));
  if (!zhTokens.length) {
    return "";
  }
  const country = shortCountryZh(zhTokens[0]);
  const area = shortPlaceZh(zhTokens[1] || zhTokens[zhTokens.length - 1] || "");
  return [country, area].filter(Boolean).join(" / ");
}

function compactNetworkLabel(profile) {
  if (profile?.mobile) {
    return "移动";
  }
  if (profile?.hosting) {
    return "机房";
  }
  if (profile?.proxy) {
    return "代理";
  }
  return "家宽";
}

function compactLocationLabel(profile) {
  if (!profile) {
    return "";
  }
  const country = shortCountryZh(profile.country_code || profile.country || "");
  const city = shortPlaceZh(profile.city || "");
  const province = shortPlaceZh(profile.province || "");
  if (country && city) {
    return [country, city].join(" / ");
  }
  if (country && province) {
    return [country, province].join(" / ");
  }
  const zhLocation = chineseLocationFromProfile(profile);
  if (zhLocation) {
    return zhLocation;
  }
  return [country, city || province].filter(Boolean).join(" / ");
}

function dashboardStatusLabel(text) {
  const raw = String(text || "");
  if (!raw) {
    return "未测试";
  }
  if (raw.includes("可用") || raw.includes("已获取") || raw.includes("运行中") || raw.includes("已启动")) {
    return "可用";
  }
  if (raw.includes("未运行")) {
    return "未运行";
  }
  if (raw.includes("未测试") || raw.includes("等待")) {
    return "未测试";
  }
  return "失败";
}

function compactIpSecondary(metric) {
  if (!metric) {
    return "等待测试";
  }
  const profile = metricIpProfile(metric);
  if (!profile || !Object.keys(profile).length) {
    const lookup = lookupResult(metric);
    return lookup?.alive ? "已拿到出口 IP / 属性待补充" : "IP 属性未获取";
  }
  const location = compactLocationLabel(profile);
  const network = compactNetworkLabel(profile);
  return [location, network].filter(Boolean).join(" / ");
}

function landingMetricPrimary(metric) {
  if (!metric) {
    return "等待测试";
  }
  const delayText = Number.isInteger(metric?.delay) ? `${metric.delay} ms` : "-";
  const lookup = lookupResult(metric);
  const exitIp = lookup.exit_ip || metric?.ip_profile?.exit_ip || "";
  return [delayText, exitIp].filter((part) => part && part !== "-").join(" / ") || delayText;
}

function gatewayMetricPrimary(metric) {
  if (!metric) {
    return "等待测试";
  }
  const lookup = lookupResult(metric);
  return lookup.exit_ip || metric?.ip_profile?.exit_ip || "出口 IP 未获取";
}

function pill(text, kind = "neutral") {
  return `<span class="status-pill ${kind}">${escapeHtml(text)}</span>`;
}

function statusKind(text) {
  if (text.includes("可用") || text.includes("已获取") || text.includes("运行中") || text.includes("已启动")) {
    return "ok";
  }
  if (text.includes("未") || text.includes("等待")) {
    return "neutral";
  }
  return "fail";
}

function populateRouteSelect(selectId) {
  const select = byId(selectId);
  if (!select) {
    return;
  }
  select.innerHTML = sortedRoutes().map((route) => {
    const selected = route.route_id === state.activeRouteId ? " selected" : "";
    return `<option value="${escapeHtml(route.route_id)}"${selected}>${escapeHtml(route.name || route.route_id)}</option>`;
  }).join("");
}

function populateProxySelect(selectId) {
  const select = byId(selectId);
  if (!select) {
    return;
  }
  const options = state.aProxies.length ? state.aProxies : [state.aSelectedProxy || ""].filter(Boolean);
  if (!options.length) {
    select.innerHTML = '<option value="">请先载入 A 节点</option>';
    return;
  }
  select.innerHTML = options.map((name) => {
    const selected = name === state.aSelectedProxy ? " selected" : "";
    return `<option value="${escapeHtml(name)}"${selected}>${escapeHtml(name)}</option>`;
  }).join("");
}

function landingFormatHelpText() {
  return [
    "支持这些带用户名和密码的 Socks5 格式：",
    "1. socks5://user:pass@host:port",
    "2. socks://user:pass@host:port",
    "3. socks5h://user:pass@host:port",
    "4. host:port:user:pass",
    "5. user:pass@host:port",
  ].join("\\n");
}

function parsePortNumber(value) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("端口必须是 1 到 65535 之间的整数。");
  }
  return port;
}

function normalizeHost(host) {
  const text = String(host || "").trim();
  if (text.startsWith("[") && text.endsWith("]")) {
    return text.slice(1, -1);
  }
  return text;
}

function splitCredentialPair(text) {
  const index = text.indexOf(":");
  if (index <= 0 || index >= text.length - 1) {
    return null;
  }
  return {
    username: text.slice(0, index),
    password: text.slice(index + 1),
  };
}

function parseHostPort(text) {
  const trimmed = text.trim();
  const ipv6Match = /^\[([^\]]+)\]:(\d+)$/.exec(trimmed);
  if (ipv6Match) {
    return {
      host: ipv6Match[1],
      port: parsePortNumber(ipv6Match[2]),
    };
  }

  const index = trimmed.lastIndexOf(":");
  if (index <= 0 || index >= trimmed.length - 1) {
    return null;
  }
  return {
    host: normalizeHost(trimmed.slice(0, index)),
    port: parsePortNumber(trimmed.slice(index + 1)),
  };
}

function parseLandingSocksInput(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) {
    throw new Error(`请先粘贴 B 的 Socks5 字符串。\\n\\n${landingFormatHelpText()}`);
  }

  if (/^socks(?:5|5h)?:\/\//i.test(value)) {
    const parsed = new URL(value);
    const scheme = parsed.protocol.replace(":", "").toLowerCase();
    if (!["socks", "socks5", "socks5h"].includes(scheme)) {
      throw new Error(landingFormatHelpText());
    }
    if (!parsed.hostname || !parsed.port || !parsed.username || !parsed.password) {
      throw new Error(`B 链接必须包含主机、端口、用户名和密码。\\n\\n${landingFormatHelpText()}`);
    }
    const username = decodeURIComponent(parsed.username);
    const password = decodeURIComponent(parsed.password);
    const host = normalizeHost(parsed.hostname);
    const port = parsePortNumber(parsed.port);
    return {
      host,
      port,
      username,
      password,
      formatLabel: `${scheme}://user:pass@host:port`,
      normalized: `socks5://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${formatHostForUri(host)}:${port}`,
    };
  }

  const atIndex = value.lastIndexOf("@");
  if (atIndex > 0) {
    const creds = splitCredentialPair(value.slice(0, atIndex));
    const endpoint = parseHostPort(value.slice(atIndex + 1));
    if (!creds || !endpoint) {
      throw new Error(landingFormatHelpText());
    }
    return {
      host: endpoint.host,
      port: endpoint.port,
      username: creds.username,
      password: creds.password,
      formatLabel: "user:pass@host:port",
      normalized: `socks5://${encodeURIComponent(creds.username)}:${encodeURIComponent(creds.password)}@${formatHostForUri(endpoint.host)}:${endpoint.port}`,
    };
  }

  const ipv6RawMatch = /^\[([^\]]+)\]:(\d+):([^:]+):(.+)$/.exec(value);
  if (ipv6RawMatch) {
    return {
      host: ipv6RawMatch[1],
      port: parsePortNumber(ipv6RawMatch[2]),
      username: ipv6RawMatch[3],
      password: ipv6RawMatch[4],
      formatLabel: "host:port:user:pass",
      normalized: `socks5://${encodeURIComponent(ipv6RawMatch[3])}:${encodeURIComponent(ipv6RawMatch[4])}@${formatHostForUri(ipv6RawMatch[1])}:${ipv6RawMatch[2]}`,
    };
  }

  const parts = value.split(":");
  if (parts.length >= 4) {
    const [host, portText, username, ...passwordParts] = parts;
    const password = passwordParts.join(":");
    if (host && portText && username && password) {
      const port = parsePortNumber(portText);
      return {
        host: normalizeHost(host),
        port,
        username,
        password,
        formatLabel: "host:port:user:pass",
        normalized: `socks5://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${formatHostForUri(host)}:${port}`,
      };
    }
  }

  throw new Error(landingFormatHelpText());
}

function updateGlobalDraft(key, value) {
  state.globalDraft[key] = value;
}

function updateRouteDraft(key, value) {
  if (!state.routeDraft) {
    return;
  }
  state.routeDraft[key] = value;
}

function collectGlobalPayload() {
  return {
    subscription_url: state.globalDraft.subscription_url.trim(),
    export_host: state.globalDraft.export_host.trim(),
    allowed_c_ports: state.globalDraft.allowed_c_ports.trim(),
    active_route_id: state.activeRouteId,
  };
}

function collectRoutePayload() {
  if (!state.routeDraft) {
    throw new Error("请先创建或选择一条路由。");
  }
  return {
    route_id: state.routeDraft.route_id,
    name: state.routeDraft.name.trim(),
    landing_socks_url: state.routeDraft.landing_socks_url.trim(),
    landing_host: state.routeDraft.landing_host.trim(),
    landing_port: Number(state.routeDraft.landing_port || 0),
    landing_username: state.routeDraft.landing_username.trim(),
    landing_password: state.routeDraft.landing_password || "",
    listen_host: state.routeDraft.listen_host.trim(),
    listen_port: Number(state.routeDraft.listen_port || 0),
    controller_port: Number(state.routeDraft.controller_port || 0),
    gateway_username: state.routeDraft.gateway_username.trim(),
    gateway_password: state.routeDraft.gateway_password || "",
    selected_proxy: state.aSelectedProxy.trim() || state.routeDraft.selected_proxy.trim(),
  };
}

function renderPageChrome() {
  const route = activeRoute();
  const status = activeStatus();
  setText("header-route-name", route?.name || "-");
  setText(
    "header-route-meta",
    route ? `${routeRuntimeLabel(status)} / ${formatEndpoint(currentExportHost(), route.listen_port)}` : "-"
  );
}

function buildGuideItems() {
  const items = [];
  if (!state.globalDraft.subscription_url.trim()) {
    items.push("先到 Ai订阅管理 页录入并保存共享订阅 A。");
  } else if (!state.aProxies.length) {
    items.push("到 Ai订阅管理 页载入 A 节点，确认这份订阅能正常读取。");
  }

  if (!routes().some((route) => route.landing_host && route.landing_port)) {
    items.push("到 B落地列表 页新增路由并录入至少一条带账号密码的 B 落地。");
  } else if (!Object.keys(state.landingMetrics).length) {
    items.push("在 B落地列表 或 仪表盘 批量测试 B，先筛掉不可用的落地。");
  }

  if (!Object.keys(state.gatewayMetrics).length) {
    items.push("到 C输出列表 批量测试 C，对外导出前先确认哪些入口已经外网可用。");
  }

  if (!items.length) {
    items.push("当前基础配置已经齐备，可以继续维护更多 B 路由，或直接复制 C 链接给外部设备。");
  }
  return items;
}

function renderHomeFirewallReminder() {
  const webUiPort = `${currentWebUiPort()}/tcp`;
  const cPortPool = `${currentCPortPool()}/tcp`;
  const exportHost = currentExportHost() || "not set / 未设置";
  const optionalIpEntry =
    currentWebUiPort() === "80"
      ? "The current WebUI entry is already on port 80. / 当前 WebUI 入口已经是 80 端口。"
      : "If you also want plain IP access on port 80, open 80/tcp too. / 如果你还要用 80 端口直连访问，请额外放行 80/tcp。";

  setText(
    "home-firewall-summary",
    `Open ${webUiPort} for the current WebUI entry, and open ${cPortPool} for C exports. ${optionalIpEntry}`
  );
  setText(
    "home-firewall-webui",
    `${currentWebUiEntry()} -> open ${webUiPort}. / 当前面板入口请放行 ${webUiPort}。`
  );
  setText(
    "home-firewall-c-ports",
    `${cPortPool}. Open only the subset you really use. / 请只放行你真正会用到的 C 端口范围。`
  );
  setText(
    "home-firewall-export-host",
    `${exportHost}. This is the host shown in exported C links. / 这是导出给客户端的 C 链接主机。`
  );
}

function renderHome() {
  const inspector = inspectorStatus();
  const onlineText = inspector.candidate_count ? `${inspector.alive_count}/${inspector.candidate_count}` : "未载入";

  setText("home-route-count", String(routes().length));
  setText("home-running-count", String(routes().filter((route) => routeStatuses()[route.route_id]?.running).length));
  setText("home-a-online", onlineText);
  setText("home-export-host", currentExportHost() || "-");

  const route = activeRoute();
  const status = activeStatus();
  setText("home-active-name", route?.name || "-");
  setText("home-active-status", route ? routeRuntimeLabel(status) : "-");
  setText("home-active-a", route ? currentRouteProxyName(route.route_id) : "-");
  setText("home-active-b", route ? formatEndpoint(route.landing_host, route.landing_port) : "-");
  setValue("home-active-link", route ? importLinkForRoute(route) : "");

  byId("home-guide-list").innerHTML = buildGuideItems().map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  renderHomeFirewallReminder();
}

function renderDashboard() {
  const inspector = inspectorStatus();
  setText("dash-subscription-url", state.globalDraft.subscription_url.trim() || "未填写");
  setText("dash-a-runtime", `${inspector.running ? "已启动" : "未启动"} / ${controllerLabel(inspector.controller_ready)}`);
  setText(
    "dash-a-count",
    inspector.candidate_count ? `${inspector.alive_count}/${inspector.candidate_count} · ${inspector.current_proxy || "未选择"}` : "未载入"
  );

  byId("dashboard-landing-table").innerHTML = sortedRoutes().map((route) => {
    const metric = landingMetric(route.route_id);
    const statusText = landingStatusText(route.route_id);
    const compactStatus = dashboardStatusLabel(statusText);
    return `
      <tr class="route-row" data-route-id="${escapeHtml(route.route_id)}" data-open-page="landings">
        <td>
          <div class="table-name">
            <strong>${escapeHtml(route.name)}</strong>
            <span class="table-sub">${escapeHtml(currentRouteProxyName(route.route_id))}</span>
          </div>
        </td>
        <td>${escapeHtml(formatEndpoint(route.landing_host, route.landing_port))}</td>
        <td class="dashboard-status-cell">${pill(compactStatus, statusKind(compactStatus))}</td>
        <td>
          <div class="table-metric">
            <strong>${escapeHtml(landingMetricPrimary(metric))}</strong>
            <span class="table-sub">${escapeHtml(compactIpSecondary(metric))}</span>
          </div>
        </td>
      </tr>
    `;
  }).join("");

  byId("dashboard-gateway-table").innerHTML = sortedRoutes().map((route) => {
    const statusText = gatewayConnectivityText(route.route_id);
    const metric = gatewayMetric(route.route_id);
    const compactStatus = dashboardStatusLabel(statusText);
    return `
      <tr class="route-row" data-route-id="${escapeHtml(route.route_id)}" data-open-page="exports">
        <td>
          <div class="table-name">
            <strong>${escapeHtml(route.name)}</strong>
            <span class="table-sub">${escapeHtml(currentRouteProxyName(route.route_id))}</span>
          </div>
        </td>
        <td>${escapeHtml(formatEndpoint(currentExportHost(), route.listen_port))}</td>
        <td class="dashboard-status-cell">${pill(compactStatus, statusKind(compactStatus))}</td>
        <td>
          <div class="table-metric">
            <strong>${escapeHtml(gatewayMetricPrimary(metric))}</strong>
            <span class="table-sub">${escapeHtml(compactIpSecondary(metric))}</span>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function renderSubscription() {
  const inspector = inspectorStatus();
  setValue("subscription_url", state.globalDraft.subscription_url);
  setText("subscription-config-state", state.globalDraft.subscription_url.trim() ? "已录入" : "等待保存");
  setText("subscription-a-runtime", `${inspector.running ? "已启动" : "未启动"} / ${controllerLabel(inspector.controller_ready)}`);
  setText("subscription-active-route", activeRoute()?.name || "-");
  setText("a-status-running", inspector.running ? "已启动" : "未启动");
  setText("a-status-controller", controllerLabel(inspector.controller_ready));
  setText("a-status-count", inspector.candidate_count ? `${inspector.alive_count}/${inspector.candidate_count}` : "未载入");
  setText("a-status-current", `${activeRoute() ? currentRouteProxyName(state.activeRouteId) : "-"} / ${state.aSelectedProxy || "未选择"}`);
  setValue("a-proxy-search", state.aProxyQuery);

  const query = state.aProxyQuery.trim().toLowerCase();
  const names = state.aProxies.filter((name) => name.toLowerCase().includes(query));
  byId("a-proxy-table").innerHTML = names.length
    ? names.map((name) => {
        const metric = state.aProxyMetrics[name] || {};
        const selected = name === state.aSelectedProxy;
        const currentForActive = name === currentRouteProxyName(state.activeRouteId);
        const statusText = metric.status_text || "未测试";
        return `
          <tr class="proxy-row ${selected ? "selected" : ""}" data-proxy-name="${escapeHtml(name)}">
            <td><input type="radio" name="a-proxy-select" value="${escapeHtml(name)}" ${selected ? "checked" : ""}></td>
            <td>${escapeHtml(name)}</td>
            <td>${pill(statusText, statusKind(statusText))}</td>
            <td>${escapeHtml(Number.isInteger(metric.delay) ? `${metric.delay} ms` : "-")}</td>
            <td>${currentForActive ? "当前路由正在使用" : "-"}</td>
          </tr>
        `;
      }).join("")
    : '<tr><td colspan="5">请先保存并载入 A 节点，或调整搜索条件。</td></tr>';
}

function renderLandingPreview() {
  const container = byId("landing-import-preview");
  if (!container) {
    return;
  }

  if (!state.landingPreview) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }

  container.classList.remove("hidden");
  container.innerHTML = `
    <div class="preview-card">
      <span>识别格式</span>
      <strong>${escapeHtml(state.landingPreview.formatLabel)}</strong>
    </div>
    <div class="preview-card">
      <span>B 主机</span>
      <strong>${escapeHtml(state.landingPreview.host)}</strong>
    </div>
    <div class="preview-card">
      <span>B 端口</span>
      <strong>${escapeHtml(String(state.landingPreview.port))}</strong>
    </div>
    <div class="preview-card">
      <span>标准化结果</span>
      <strong>${escapeHtml(state.landingPreview.normalized)}</strong>
    </div>
  `;
}

function renderLandings() {
  populateRouteSelect("route-picker-landing");

  const route = activeRoute();
  const status = activeStatus();
  if (!route || !state.routeDraft) {
    return;
  }

  setText("landing-selected-route", route.name);
  setText("landing-selected-status", routeRuntimeLabel(status));
  setText("landing-selected-a", currentRouteProxyName(route.route_id));
  setText("landing-selected-c", formatEndpoint(currentExportHost(), route.listen_port));

  setValue("route_name", state.routeDraft.name);
  setValue("landing_socks_url", state.routeDraft.landing_socks_url);
  setValue("landing_host", state.routeDraft.landing_host);
  setValue("landing_port", state.routeDraft.landing_port);
  setValue("landing_username", state.routeDraft.landing_username);
  setValue("landing_password", state.routeDraft.landing_password);
  renderLandingPreview();
  setValue("landing-route-search", state.landingSearch);

  const filteredRoutes = sortedRoutes().filter((item) => matchesRouteQuery(item, state.landingSearch));
  byId("landing-route-table").innerHTML = filteredRoutes.length
    ? filteredRoutes.map((item) => {
        const statusText = landingStatusText(item.route_id);
        const metric = landingMetric(item.route_id);
        const routeStatus = routeStatuses()[item.route_id];
        const active = item.route_id === state.activeRouteId ? "active" : "";
        return `
          <tr class="route-row ${active}" data-route-id="${escapeHtml(item.route_id)}" data-open-page="landings">
            <td>
              <div class="table-name">
                <strong>${escapeHtml(item.name)}</strong>
                <span class="table-sub">${escapeHtml(item.route_id)}</span>
              </div>
            </td>
            <td>${escapeHtml(formatEndpoint(item.landing_host, item.landing_port))}</td>
            <td>${escapeHtml(currentRouteProxyName(item.route_id))}</td>
            <td>${escapeHtml(formatEndpoint(currentExportHost(), item.listen_port))}</td>
            <td>${pill(routeRuntimeLabel(routeStatus), routeStatus?.running ? "ok" : "neutral")}</td>
            <td>${pill(statusText, statusKind(statusText))}</td>
            <td>${escapeHtml(Number.isInteger(metric?.delay) ? `${metric.delay} ms` : "-")}</td>
            <td><div class="row-actions"><button class="row-button" type="button" data-action="select-route" data-route-id="${escapeHtml(item.route_id)}">选择</button></div></td>
          </tr>
        `;
      }).join("")
    : '<tr><td colspan="8">没有匹配的路由。</td></tr>';
}

function renderExports() {
  populateRouteSelect("route-picker-export");
  populateProxySelect("c-page-proxy-select");

  const route = activeRoute();
  const status = activeStatus();
  if (!route || !state.routeDraft) {
    return;
  }

  setText("export-selected-route", route.name);
  setText("export-selected-status", routeRuntimeLabel(status));
  setText("export-selected-b", formatEndpoint(route.landing_host, route.landing_port));
  setText("export-host-readonly", currentExportHost() || "-");

  setValue("listen_host", state.routeDraft.listen_host);
  setValue("listen_port", state.routeDraft.listen_port);
  setValue("controller_port", state.routeDraft.controller_port);
  setValue("gateway_username", state.routeDraft.gateway_username);
  setValue("gateway_password", state.routeDraft.gateway_password);
  setValue("test_url", state.testPrefs.test_url);
  setValue("timeout_ms", state.testPrefs.timeout_ms);
  setValue("export-route-search", state.exportSearch);

  const formatSelect = byId("export-format");
  if (formatSelect) {
    formatSelect.value = state.exportFormat;
  }

  const link = importLinkForRoute({ ...route, ...state.routeDraft });
  setText("import-link-quick", link || "-");

  setText("export-connectivity-status", gatewayConnectivityText(route.route_id));
  setText("export-connectivity-delay", gatewayDelayText(route.route_id));
  setText("export-iplookup-status", gatewayLookupText(route.route_id));
  setText("export-exit-ip", gatewayExitIpText(route.route_id));

  const filteredRoutes = sortedRoutes().filter((item) => matchesRouteQuery(item, state.exportSearch));
  byId("export-route-table").innerHTML = filteredRoutes.length
    ? filteredRoutes.map((item) => {
        const active = item.route_id === state.activeRouteId ? "active" : "";
        const running = Boolean(routeStatuses()[item.route_id]?.running);
        return `
          <tr class="route-row ${active}" data-route-id="${escapeHtml(item.route_id)}" data-open-page="exports">
            <td>
              <div class="table-name">
                <strong>${escapeHtml(item.name)}</strong>
                <span class="table-sub">${escapeHtml(routeStatuses()[item.route_id]?.running ? "运行中" : "未运行")}</span>
              </div>
            </td>
            <td>${escapeHtml(currentRouteProxyName(item.route_id))}</td>
            <td>${escapeHtml(formatEndpoint(item.landing_host, item.landing_port))}</td>
            <td>${escapeHtml(formatEndpoint(currentExportHost(), item.listen_port))}</td>
            <td>${pill(gatewayConnectivityText(item.route_id), statusKind(gatewayConnectivityText(item.route_id)))}</td>
            <td>${pill(gatewayLookupText(item.route_id), statusKind(gatewayLookupText(item.route_id)))}</td>
            <td>${escapeHtml(gatewayExitIpText(item.route_id))}</td>
            <td>
              <div class="row-actions">
                <button class="row-button" type="button" data-action="copy-route-link" data-route-id="${escapeHtml(item.route_id)}">复制</button>
                <button class="row-button" type="button" data-action="test-route-gateway" data-route-id="${escapeHtml(item.route_id)}">测试</button>
                <button class="row-button" type="button" data-action="start-route" data-route-id="${escapeHtml(item.route_id)}"${running ? " disabled" : ""}>${running ? "运行中" : "运行"}</button>
              </div>
            </td>
          </tr>
        `;
      }).join("")
    : '<tr><td colspan="8">没有匹配的路由。</td></tr>';
}

function renderSettings() {
  populateRouteSelect("route-picker-logs");

  setValue("settings_export_host", state.globalDraft.export_host);
  setValue("settings_allowed_c_ports", state.globalDraft.allowed_c_ports);
  setText("settings-active-route", activeRoute()?.name || "-");
  setText("settings-running-count", String(routes().filter((route) => routeStatuses()[route.route_id]?.running).length));
  setText("settings-port-pool-echo", state.globalDraft.allowed_c_ports || "-");

  const inspector = inspectorStatus();
  const status = activeStatus();
  setText("settings-core-inspector", inspector.running ? "已启动" : "未启动");
  setText("settings-core-controller", inspector.controller_port ? `127.0.0.1:${inspector.controller_port}` : "-");
  setText("settings-core-route-controller", status?.controller_port ? `127.0.0.1:${status.controller_port}` : "-");
  setText("settings-core-listen-port", status?.listen_port ? String(status.listen_port) : "-");
  setText("settings-provider-path", inspector.provider_path || "-");
  setText("settings-log-path", status?.log_path || "-");
  setText("settings-config-path", status?.config_path || "-");
  setText("settings-mihomo-path", status?.mihomo_path || "-");

  const route = activeRoute();
  setText("log-route-name", route?.name || "-");
  setText("log-route-meta", route ? `${routeRuntimeLabel(activeStatus())} / ${formatEndpoint(currentExportHost(), route.listen_port)}` : "-");
  setText("log-refresh-time", state.lastLogRefreshAt || "尚未刷新");
}

function renderAll() {
  renderPageChrome();
  renderHome();
  renderDashboard();
  renderSubscription();
  renderLandings();
  renderExports();
  renderSettings();
  setActivePage(state.activePage, false);
  setSettingsTab(state.settingsTab);
}

async function refreshAProxies(silent = false) {
  const payload = await api("/api/a/proxies");
  state.dashboard = payload.state;
  const proxies = payload.proxies || {};
  state.aProxies = proxies.all || [];
  const aliveSet = new Set(proxies.alive || []);
  const nextMetrics = {};
  for (const name of state.aProxies) {
    nextMetrics[name] = state.aProxyMetrics[name] || {
      status_text: aliveSet.has(name) ? "核心在线" : "未测试",
      delay: null,
    };
  }
  state.aProxyMetrics = nextMetrics;
  syncDrafts(true);
  renderAll();
  if (!silent) {
    showToast("A 节点列表已更新。");
  }
}

async function refreshLogs(silent = false) {
  if (!state.activeRouteId) {
    byId("log-box").textContent = "请选择一条路由后刷新日志。";
    return;
  }

  const payload = await api(`/api/logs?route_id=${encodeURIComponent(state.activeRouteId)}`);
  byId("log-box").textContent = payload.log || "暂无日志。";
  state.lastLogRefreshAt = new Date().toLocaleString("zh-CN", { hour12: false });
  renderSettings();
  if (!silent) {
    showToast("日志已刷新。");
  }
}

async function refreshState({ refreshA = true, refreshLog = true } = {}) {
  const payload = await api("/api/state");
  state.dashboard = payload.state;
  const validIds = new Set(routes().map((route) => route.route_id));
  const preferred = appSettings().active_route_id || routes()[0]?.route_id || "";
  state.activeRouteId = validIds.has(state.activeRouteId) ? state.activeRouteId : preferred;
  pruneMetrics();
  syncDrafts(true);
  renderAll();

  const shouldAutoLoadCachedA = refreshA && state.globalDraft.subscription_url.trim() && !state.aProxies.length;
  if ((refreshA && inspectorStatus().running) || shouldAutoLoadCachedA) {
    await refreshAProxies(true);
  }
  if (refreshLog) {
    await refreshLogs(true);
  }
}

async function activateRoute(routeId, openPage = "") {
  const payload = await api("/api/routes/activate", {
    method: "POST",
    body: JSON.stringify({ route_id: routeId }),
  });
  state.dashboard = payload.state;
  state.activeRouteId = routeId;
  state.landingPreview = null;
  syncDrafts(true);
  renderAll();
  if (openPage) {
    setActivePage(openPage);
  }
  await refreshLogs(true);
}

async function saveGlobal(showSuccess = true) {
  const payload = await api("/api/settings/global", {
    method: "POST",
    body: JSON.stringify(collectGlobalPayload()),
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  if (showSuccess) {
    showToast("共享设置已保存。");
  }
}

async function saveSubscription() {
  await saveGlobal(false);
  if (state.globalDraft.subscription_url.trim()) {
    await refreshAProxies(true);
    showToast("订阅已保存，并已载入缓存中的 A 节点。");
    return;
  }
  showToast("共享订阅已保存。");
}

async function saveServerSettings() {
  await saveGlobal(true);
}

async function installCore() {
  const payload = await api("/api/core/install", {
    method: "POST",
    body: "{}",
  });
  showToast(`mihomo 已就绪：${payload.version}`);
}

async function loadAProxies() {
  await saveGlobal(false);
  await refreshAProxies(true);
  showToast("A 节点已载入，现在可以测速或切换。");
}

async function refreshSubscription() {
  await saveGlobal(false);
  const payload = await api("/api/subscription/refresh", {
    method: "POST",
    body: "{}",
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  await refreshAProxies(true);
  showToast("订阅 A 已刷新。");
}

async function testSelectedAProxy() {
  if (!state.aSelectedProxy) {
    throw new Error("请先选择一个 A 节点。");
  }
  const payload = await api("/api/a/proxies/test", {
    method: "POST",
    body: JSON.stringify({
      proxy_name: state.aSelectedProxy,
      test_url: state.testPrefs.test_url,
      timeout_ms: state.testPrefs.timeout_ms,
    }),
  });
  const result = payload.result;
  state.aProxyMetrics[result.name] = {
    status_text: result.alive ? "可用" : "超时 / 不可用",
    delay: result.delay,
  };
  renderSubscription();
  showToast(result.alive ? `${result.name} ${result.delay} ms` : `${result.name} 不可用`, !result.alive);
}

async function testAllAProxies() {
  if (!state.aProxies.length) {
    throw new Error("请先载入 A 节点。");
  }
  const payload = await api("/api/a/proxies/test-all", {
    method: "POST",
    body: JSON.stringify({
      test_url: state.testPrefs.test_url,
      timeout_ms: state.testPrefs.timeout_ms,
    }),
  });
  const results = payload.result.results || {};
  for (const [name, result] of Object.entries(results)) {
    state.aProxyMetrics[name] = {
      status_text: result.alive ? "可用" : "超时 / 不可用",
      delay: result.delay,
    };
  }
  renderSubscription();
  showToast("A 节点批量测速完成。");
}

async function applySelectedAProxy() {
  if (!state.activeRouteId) {
    throw new Error("请先选择一条路由。");
  }
  if (!activeStatus()?.running) {
    throw new Error("请先启动当前路由，再应用 A 节点。");
  }
  if (!state.aSelectedProxy) {
    throw new Error("请先选择一个 A 节点。");
  }

  const payload = await api("/api/proxies/select", {
    method: "POST",
    body: JSON.stringify({
      route_id: state.activeRouteId,
      proxy_name: state.aSelectedProxy,
    }),
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  showToast(`已将当前路由切换到 ${state.aSelectedProxy}`);
}

async function createRoute() {
  await saveGlobal(false);
  const payload = await api("/api/routes/create", {
    method: "POST",
    body: "{}",
  });
  state.dashboard = payload.state;
  state.activeRouteId = appSettings().active_route_id || routes()[0]?.route_id || "";
  state.landingPreview = null;
  syncDrafts(true);
  renderAll();
  await refreshLogs(true);
  showToast("已创建新路由。");
}

async function duplicateRoute() {
  if (!state.activeRouteId) {
    throw new Error("请先选择一条路由。");
  }
  const payload = await api("/api/routes/create", {
    method: "POST",
    body: JSON.stringify({ source_route_id: state.activeRouteId }),
  });
  state.dashboard = payload.state;
  state.activeRouteId = appSettings().active_route_id || routes()[0]?.route_id || "";
  state.landingPreview = null;
  syncDrafts(true);
  renderAll();
  await refreshLogs(true);
  showToast("已复制当前路由。");
}

async function deleteRoute() {
  if (!state.activeRouteId) {
    throw new Error("请先选择一条路由。");
  }
  if (!window.confirm("确定删除当前路由吗？")) {
    return;
  }
  const payload = await api("/api/routes/delete", {
    method: "POST",
    body: JSON.stringify({ route_id: state.activeRouteId }),
  });
  state.dashboard = payload.state;
  state.activeRouteId = appSettings().active_route_id || routes()[0]?.route_id || "";
  state.landingPreview = null;
  pruneMetrics();
  syncDrafts(true);
  renderAll();
  await refreshLogs(true);
  showToast("当前路由已删除。");
}

async function saveRoute(showSuccess = true) {
  const payload = await api("/api/routes/save", {
    method: "POST",
    body: JSON.stringify(collectRoutePayload()),
  });
  state.dashboard = payload.state;
  state.activeRouteId = appSettings().active_route_id || state.activeRouteId;
  syncDrafts(true);
  renderAll();
  if (showSuccess) {
    showToast("当前路由已保存。");
  }
}

async function startRoute() {
  await saveRoute(false);
  const payload = await api("/api/core/start", {
    method: "POST",
    body: JSON.stringify({ route_id: state.activeRouteId }),
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  await refreshLogs(true);
  showToast("当前路由已启动。");
}

async function startRouteById(routeId) {
  if (!routeId) {
    throw new Error("请先选择一条路由。");
  }
  if (routeId === state.activeRouteId) {
    await saveRoute(false);
  }
  const payload = await api("/api/core/start", {
    method: "POST",
    body: JSON.stringify({ route_id: routeId }),
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  if (routeId === state.activeRouteId) {
    await refreshLogs(true);
  }
  const route = routes().find((item) => item.route_id === routeId);
  showToast(`${route?.name || "该路由"} 已启动。`);
}

async function stopRoute() {
  const payload = await api("/api/core/stop", {
    method: "POST",
    body: JSON.stringify({ route_id: state.activeRouteId }),
  });
  state.dashboard = payload.state;
  syncDrafts(true);
  renderAll();
  await refreshLogs(true);
  showToast("当前路由已停止。");
}

function storeLandingMetric(routeId, result) {
  state.landingMetrics[routeId] = {
    ...result,
    tested_at: new Date().toISOString(),
  };
}

function storeGatewayMetric(routeId, result) {
  state.gatewayMetrics[routeId] = {
    ...result,
    tested_at: new Date().toISOString(),
  };
}

async function testLanding(routeId = state.activeRouteId) {
  if (!routeId) {
    throw new Error("请先选择一条路由。");
  }
  if (routeId === state.activeRouteId) {
    await saveRoute(false);
  }
  const payload = await api("/api/landing/test", {
    method: "POST",
    body: JSON.stringify({
      route_id: routeId,
      test_url: state.testPrefs.test_url,
      timeout_ms: state.testPrefs.timeout_ms,
    }),
  });
  storeLandingMetric(routeId, payload.result);
  renderDashboard();
  renderLandings();
  showToast(payload.result.alive ? "当前 B 可用。" : payload.result.status_text || "当前 B 不可用。", !payload.result.alive);
}

async function testAllLandings() {
  if (!routes().length) {
    throw new Error("当前没有可测试的路由。");
  }
  let okCount = 0;
  let failCount = 0;
  for (const route of sortedRoutes()) {
    try {
      const payload = await api("/api/landing/test", {
        method: "POST",
        body: JSON.stringify({
          route_id: route.route_id,
          test_url: state.testPrefs.test_url,
          timeout_ms: state.testPrefs.timeout_ms,
        }),
      });
      storeLandingMetric(route.route_id, payload.result);
      if (payload.result.alive) {
        okCount += 1;
      } else {
        failCount += 1;
      }
    } catch (_error) {
      failCount += 1;
    }
  }
  renderDashboard();
  renderLandings();
  showToast(`B 落地批量测试完成：${okCount} 可用，${failCount} 失败。`, failCount > 0);
}

function gatewayStoppedResult(route) {
  return {
    alive: false,
    delay: null,
    status_text: "未运行",
    endpoint: formatEndpoint(currentExportHost(), route.listen_port),
    connectivity: {
      alive: false,
      delay: null,
      status_text: "未运行",
    },
    ip_lookup: {
      alive: false,
      status_text: "连通性未通过，未查询出口 IP",
      exit_ip: "",
    },
    ip_profile: {},
  };
}

async function testGateway(routeId = state.activeRouteId) {
  if (!routeId) {
    throw new Error("请先选择一条路由。");
  }

  if (routeId === state.activeRouteId) {
    await saveRoute(false);
  }

  const route = routes().find((item) => item.route_id === routeId);
  const status = routeStatuses()[routeId];
  if (!status?.running && route) {
    storeGatewayMetric(routeId, gatewayStoppedResult(route));
    renderDashboard();
    renderExports();
    showToast("当前路由未运行，已跳过 C 测试。", true);
    return;
  }

  const payload = await api("/api/gateway/test", {
    method: "POST",
    body: JSON.stringify({
      route_id: routeId,
      test_url: state.testPrefs.test_url,
      timeout_ms: state.testPrefs.timeout_ms,
    }),
  });
  storeGatewayMetric(routeId, payload.result);
  renderDashboard();
  renderExports();
  showToast(payload.result.alive ? "当前 C 测试通过。" : payload.result.status_text || "当前 C 测试失败。", !payload.result.alive);
}

async function testAllGateways() {
  const runningRoutes = sortedRoutes().filter((route) => routeStatuses()[route.route_id]?.running);
  if (!runningRoutes.length) {
    throw new Error("当前没有运行中的路由可供批量测试。");
  }

  let okCount = 0;
  let failCount = 0;
  for (const route of runningRoutes) {
    try {
      const payload = await api("/api/gateway/test", {
        method: "POST",
        body: JSON.stringify({
          route_id: route.route_id,
          test_url: state.testPrefs.test_url,
          timeout_ms: state.testPrefs.timeout_ms,
        }),
      });
      storeGatewayMetric(route.route_id, payload.result);
      if (payload.result.alive) {
        okCount += 1;
      } else {
        failCount += 1;
      }
    } catch (_error) {
      failCount += 1;
    }
  }
  renderDashboard();
  renderExports();
  showToast(`C 外网批量测试完成：${okCount} 可用，${failCount} 失败。`, failCount > 0);
}

async function startAllRoutes() {
  if (!routes().length) {
    throw new Error("当前没有可运行的路由。");
  }

  if (state.activeRouteId) {
    await saveRoute(false);
  }

  const pendingRoutes = sortedRoutes().filter((route) => !routeStatuses()[route.route_id]?.running);
  if (!pendingRoutes.length) {
    throw new Error("当前所有路由都已经在运行中。");
  }

  let okCount = 0;
  let failCount = 0;
  for (const route of pendingRoutes) {
    try {
      const payload = await api("/api/core/start", {
        method: "POST",
        body: JSON.stringify({ route_id: route.route_id }),
      });
      state.dashboard = payload.state;
      okCount += 1;
    } catch (_error) {
      failCount += 1;
    }
  }

  syncDrafts(true);
  renderAll();
  if (state.activeRouteId) {
    await refreshLogs(true);
  }
  showToast(`批量运行完成：${okCount} 条已启动，${failCount} 条失败。`, failCount > 0);
}

async function copyCurrentLink() {
  const route = { ...(activeRoute() || {}), ...(state.routeDraft || {}) };
  const value = importLinkForRoute(route);
  if (!value) {
    throw new Error("当前没有可复制的 C 链接。");
  }
  await copyText(value);
  showToast("完整 C 链接已复制。");
}

async function copyHomeLink() {
  const value = byId("home-active-link").value.trim();
  if (!value) {
    throw new Error("当前没有可复制的 C 链接。");
  }
  await copyText(value);
  showToast("当前标准 C 链接已复制。");
}

async function copyRouteLink(routeId) {
  const route = routes().find((item) => item.route_id === routeId);
  if (!route) {
    throw new Error("未找到这条路由。");
  }
  const value = importLinkForRoute(route);
  if (!value) {
    throw new Error("这条路由当前没有可复制的 C 链接。");
  }
  await copyText(value);
  showToast(`已复制 ${route.name} 的 C 链接。`);
}

function applyLandingImport() {
  const parsed = parseLandingSocksInput(state.routeDraft?.landing_socks_url || "");
  state.landingPreview = parsed;
  updateRouteDraft("landing_socks_url", parsed.normalized);
  updateRouteDraft("landing_host", parsed.host);
  updateRouteDraft("landing_port", parsed.port);
  updateRouteDraft("landing_username", parsed.username);
  updateRouteDraft("landing_password", parsed.password);
  renderLandings();
  showToast("B 链接已录入，已自动拆分到下方字段。");
}

function renderSelectedRouteAfterInputChange() {
  renderLandings();
  renderExports();
  renderHome();
}

function bindInput(id, handler) {
  const element = byId(id);
  if (!element) {
    return;
  }
  element.addEventListener("input", (event) => {
    handler(event.target.value);
  });
}

function bindSelect(id, handler) {
  const element = byId(id);
  if (!element) {
    return;
  }
  element.addEventListener("change", (event) => {
    handler(event.target.value);
  });
}

function bindAction(id, label, handler, loadingText = "处理中...") {
  const button = byId(id);
  if (!button) {
    return;
  }
  button.addEventListener("click", async () => {
    try {
      await runExclusiveAction({ label, trigger: button, loadingText }, handler);
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });
}

function bindPageNavigation() {
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      setActivePage(button.dataset.page || "home");
    });
  });

  window.addEventListener("hashchange", () => {
    setActivePage(window.location.hash.replace("#", "") || "home", false);
  });
}

function bindSettingsNavigation() {
  document.querySelectorAll(".settings-nav").forEach((button) => {
    button.addEventListener("click", () => {
      setSettingsTab(button.dataset.settingsTab || "server");
    });
  });
}

function bindProxyTable() {
  const table = byId("a-proxy-table");
  if (!table) {
    return;
  }
  table.addEventListener("change", (event) => {
    if (event.target.name !== "a-proxy-select") {
      return;
    }
    state.aSelectedProxy = event.target.value;
    renderSubscription();
  });

  table.addEventListener("click", (event) => {
    const row = event.target.closest(".proxy-row");
    if (!row || event.target.matches("input")) {
      return;
    }
    state.aSelectedProxy = row.dataset.proxyName || "";
    renderSubscription();
  });
}

function bindRouteTables() {
  ["dashboard-landing-table", "dashboard-gateway-table", "landing-route-table", "export-route-table"].forEach((id) => {
    const table = byId(id);
    if (!table) {
      return;
    }
    table.addEventListener("click", async (event) => {
      const actionButton = event.target.closest("[data-action]");
      if (actionButton) {
        const action = actionButton.dataset.action;
        const routeId = actionButton.dataset.routeId || "";
        try {
          if (action === "select-route") {
            await runExclusiveAction({ label: "切换路由", trigger: actionButton, loadingText: "切换中..." }, () => activateRoute(routeId));
          } else if (action === "copy-route-link") {
            await copyRouteLink(routeId);
          } else if (action === "test-route-gateway") {
            await runExclusiveAction({ label: "测试 C", trigger: actionButton, loadingText: "测试中..." }, () => testGateway(routeId));
          } else if (action === "start-route") {
            await runExclusiveAction({ label: "启动路由", trigger: actionButton, loadingText: "启动中..." }, () => startRouteById(routeId));
          }
        } catch (error) {
          showToast(error.message || String(error), true);
        }
        return;
      }

      const row = event.target.closest(".route-row");
      if (!row) {
        return;
      }

      const openPage = row.dataset.openPage || "";
      try {
        await runExclusiveAction({ label: "切换路由", trigger: row, loadingText: "切换中..." }, () => activateRoute(row.dataset.routeId || "", openPage));
      } catch (error) {
        showToast(error.message || String(error), true);
      }
    });
  });
}

function bindDraftInputs() {
  bindInput("subscription_url", (value) => {
    updateGlobalDraft("subscription_url", value);
    renderSubscription();
  });

  bindInput("settings_export_host", (value) => {
    updateGlobalDraft("export_host", value);
    renderSettings();
    renderExports();
    renderHome();
    renderDashboard();
  });

  bindInput("settings_allowed_c_ports", (value) => {
    updateGlobalDraft("allowed_c_ports", value);
    renderSettings();
  });

  [
    "route_name",
    "landing_socks_url",
    "landing_host",
    "landing_port",
    "landing_username",
    "landing_password",
    "listen_host",
    "listen_port",
    "controller_port",
    "gateway_username",
    "gateway_password",
  ].forEach((id) => {
    bindInput(id, (value) => {
      const fieldMap = {
        route_name: "name",
        landing_socks_url: "landing_socks_url",
        landing_host: "landing_host",
        landing_port: "landing_port",
        landing_username: "landing_username",
        landing_password: "landing_password",
        listen_host: "listen_host",
        listen_port: "listen_port",
        controller_port: "controller_port",
        gateway_username: "gateway_username",
        gateway_password: "gateway_password",
      };
      updateRouteDraft(fieldMap[id], value);
      renderSelectedRouteAfterInputChange();
    });
  });

  bindInput("test_url", (value) => {
    state.testPrefs.test_url = value || defaultTestUrl();
    renderExports();
  });

  bindInput("timeout_ms", (value) => {
    state.testPrefs.timeout_ms = Number(value || defaultTimeoutMs());
    renderExports();
  });

  bindInput("a-proxy-search", (value) => {
    state.aProxyQuery = value || "";
    renderSubscription();
  });

  bindInput("landing-route-search", (value) => {
    state.landingSearch = value || "";
    renderLandings();
  });

  bindInput("export-route-search", (value) => {
    state.exportSearch = value || "";
    renderExports();
  });

  bindSelect("route-picker-landing", async (routeId) => {
    try {
      await activateRoute(routeId, "landings");
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });

  bindSelect("route-picker-export", async (routeId) => {
    try {
      await activateRoute(routeId, "exports");
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });

  bindSelect("route-picker-logs", async (routeId) => {
    try {
      await activateRoute(routeId, "settings");
      setSettingsTab("logs");
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });

  bindSelect("c-page-proxy-select", (value) => {
    state.aSelectedProxy = value || "";
    renderExports();
  });

  bindSelect("export-format", (value) => {
    state.exportFormat = value || "socks5_uri";
    renderExports();
    renderHome();
  });
}

function bindStandaloneButtons() {
  byId("copy-home-link").addEventListener("click", async () => {
    try {
      await copyHomeLink();
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });

  byId("copy-import-quick").addEventListener("click", async () => {
    try {
      await copyCurrentLink();
    } catch (error) {
      showToast(error.message || String(error), true);
    }
  });

  byId("parse-landing-socks").addEventListener("click", () => {
    try {
      applyLandingImport();
    } catch (error) {
      state.landingPreview = null;
      renderLandingPreview();
      showToast(error.message || String(error), true);
    }
  });
}

function bindActions() {
  bindAction("save-subscription", "保存订阅 A", saveSubscription, "保存中...");
  bindAction("refresh-subscription", "刷新订阅 A", refreshSubscription, "刷新中...");
  bindAction("load-a-proxies", "载入 A 节点", loadAProxies, "载入中...");
  bindAction("test-selected-a-proxy", "测试所选 A 节点", testSelectedAProxy, "测速中...");
  bindAction("test-all-a-proxies", "批量测试 A 节点", testAllAProxies, "测速中...");
  bindAction("apply-a-proxy", "应用 A 节点", applySelectedAProxy, "切换中...");

  bindAction("create-route", "新建路由", createRoute, "创建中...");
  bindAction("duplicate-route", "复制路由", duplicateRoute, "复制中...");
  bindAction("delete-route", "删除路由", deleteRoute, "删除中...");
  bindAction("save-route-landing", "保存当前路由", saveRoute, "保存中...");
  bindAction("save-route-export", "保存当前路由", saveRoute, "保存中...");
  bindAction("start-route", "启动当前路由", startRoute, "启动中...");
  bindAction("stop-route", "停止当前路由", stopRoute, "停止中...");

  bindAction("test-landing", "测试当前 B", () => testLanding(), "测试中...");
  bindAction("test-all-landings", "批量测试 B", testAllLandings, "批量测试中...");
  bindAction("test-all-landings-page", "批量测试 B", testAllLandings, "批量测试中...");

  bindAction("apply-export-proxy", "应用当前 A 节点", applySelectedAProxy, "切换中...");
  bindAction("test-gateway", "测试当前 C", () => testGateway(), "测试中...");
  bindAction("start-all-routes-page", "批量运行路由", startAllRoutes, "批量运行中...");
  bindAction("test-all-gateways", "批量测试 C", testAllGateways, "批量测试中...");
  bindAction("test-all-gateways-page", "批量测试 C", testAllGateways, "批量测试中...");

  bindAction("save-server-settings", "保存服务器设置", saveServerSettings, "保存中...");
  bindAction("install-core", "安装或更新 mihomo", installCore, "处理中...");
  bindAction("refresh-logs", "刷新日志", refreshLogs, "刷新中...");
}

function init() {
  state.testPrefs.test_url = defaultTestUrl();
  state.testPrefs.timeout_ms = defaultTimeoutMs();
  bindPageNavigation();
  bindSettingsNavigation();
  bindProxyTable();
  bindRouteTables();
  bindDraftInputs();
  bindStandaloneButtons();
  bindActions();

  setActivePage(window.location.hash.replace("#", "") || "home", false);
  setSettingsTab("server");
  refreshState().catch((error) => showToast(error.message || String(error), true));
}

init();
