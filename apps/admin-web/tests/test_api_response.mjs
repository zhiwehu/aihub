import {test} from 'node:test';
import assert from 'node:assert/strict';
import {failureMessage, readBody} from '../public/api-response.mjs';

const response = (status, body) => ({status, text: async () => body});

test('a plain-text 500 is reported as a status, not as a JSON syntax error', async () => {
  // aiohttp's unhandled-error body: JSON.parse would say "Unexpected
  // non-whitespace character after JSON at position 4".
  const body = '500 Internal Server Error\n\nServer got itself in trouble';
  assert.deepEqual(await readBody(response(500, body)), {value: null, parsed: false});
  assert.match(failureMessage(response(500, body)), /服务暂时不可用（HTTP 500）/);
});

test('json bodies still decode, error codes included', async () => {
  assert.deepEqual(await readBody(response(409, '{"error":{"code":"mqtt_must_stop"}}')),
    {value: {error: {code: 'mqtt_must_stop'}}, parsed: true});
});

test('empty and truncated bodies count as unreadable', async () => {
  assert.equal((await readBody(response(200, ''))).parsed, false);
  assert.equal((await readBody(response(200, '{"a":'))).parsed, false);
});

test('4xx keeps the login hint, an unparseable 2xx names the body problem', () => {
  assert.match(failureMessage(response(403, '')), /请求失败（HTTP 403）/);
  assert.match(failureMessage(response(200, '<html>')), /无法解析的内容（HTTP 200）/);
});
