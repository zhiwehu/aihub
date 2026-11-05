// Console API responses are not always JSON. When a handler raises, aiohttp
// answers with a text/plain body ("500 Internal Server Error"), and JSON.parse
// turns that into "Unexpected non-whitespace character after JSON at position 4"
// because "500 " already parses as a number. Nobody can act on that message, so
// every console fetch goes through here: decode what is there, and describe the
// failure in terms of the HTTP status.

export function failureMessage(response) {
  if (response.status >= 500)
    return `服务暂时不可用（HTTP ${response.status}），请查看后台日志后重试。`;
  if (response.status >= 400)
    return `请求失败（HTTP ${response.status}），请检查管理员登录状态。`;
  return `服务返回了无法解析的内容（HTTP ${response.status}），请查看后台日志。`;
}

// {value, parsed}: value is the decoded body (null when empty), parsed says
// whether the body was usable JSON at all.
export async function readBody(response) {
  const text = (await response.text()).trim();
  if (!text) return {value: null, parsed: false};
  try {
    return {value: JSON.parse(text), parsed: true};
  } catch {
    return {value: null, parsed: false};
  }
}
