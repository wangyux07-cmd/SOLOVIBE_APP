import { test, expect } from '@playwright/test';

test('browser location is explicit and route sketch uses provider points', async ({ page, context }) => {
  const thread = '00000000-0000-4000-8000-000000000071';
  let revision = 0;
  let originCalls = 0;
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ longitude: 121.435, latitude: 31.193, accuracy: 500 });
  const plan = { plan_id: 'amap:A1', context_revision: 1,
    place: { name: '徐家汇公园', address: '肇嘉浜路', category: '公园', poi_id: 'A1',
      source_url: 'https://uri.amap.com/marker?position=121.439,31.196', observed_at: '2026-10-13T12:00:00Z' },
    route: { walking_minutes: 8, distance_meters: 592, observed_at: '2026-10-13T12:00:00Z',
      polyline: ['121.436000,31.194000', '121.437000,31.195000', '121.439000,31.196000'] },
    return_route: { walking_minutes: 9, distance_meters: 610, observed_at: '2026-10-13T12:00:00Z',
      polyline: ['121.439000,31.196000', '121.438000,31.194500', '121.436000,31.194000'] },
    time_breakdown: { outbound_minutes: 8, dwell_minutes: 30, return_minutes: 9,
      buffer_minutes: 10, total_minutes: 57, dwell_source: 'user_selected' },
    facts: null, unknowns: ['实际消费'], tradeoff: '完整行程约 57 分钟', web_status: 'empty', web_sources: [] };
  await page.route('**/api/v1/health', route => route.fulfill({ json: { ready: true, stage: 'v3-1' } }));
  await page.route('**/api/session', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/api/conversations', route => route.fulfill({ json: { conversations: [{ thread_id: thread }] } }));
  await page.route(`**/api/conversations/${thread}`, route => route.fulfill({ json: {
    thread_id: thread, snapshot: { revision, constraints: revision ? { city: '上海市', location_text: '上海市徐汇区虹桥路1号' } : {}, sources: {} },
    messages: [], pending_run: null,
    plan_set: revision ? { plan_set_id: '00000000-0000-4000-8000-000000000072',
      kind: 'options_ready', evidence_status: 'ok', provider_errors: [], plans: [plan] } : null,
    context_memory: { summary_revision: 0, covered_until_sequence: 0, raw_messages_retained: true },
  } }));
  await page.route(`**/api/conversations/${thread}/origin`, route => {
    const body = route.request().postDataJSON();
    expect(body.longitude).toBeCloseTo(121.435);
    expect(body.latitude).toBeCloseTo(31.193);
    expect(body.accuracy_m).toBe(18);
    expect(body.expected_revision).toBe(0);
    originCalls += 1;
    revision = 1;
    return route.fulfill({ json: { snapshot: { revision: 1 },
      origin: { city: '上海市', address: '上海市徐汇区虹桥路1号', accuracy_m: 18 } } });
  });
  await page.goto('/');
  expect(originCalls).toBe(0);
  await page.getByRole('button', { name: '使用当前位置' }).click();
  await expect(page.getByRole('alert')).toContainText('定位精度超过 300 米');
  expect(originCalls).toBe(0);
  await expect(page.getByLabel('输入出行需求')).toBeEnabled();
  await context.setGeolocation({ longitude: 121.435, latitude: 31.193, accuracy: 18 });
  await page.getByRole('button', { name: '使用当前位置' }).click();
  await expect(page.getByText(/已记录：上海市徐汇区虹桥路1号/)).toBeVisible();
  expect(originCalls).toBe(1);
  await expect(page.getByText(/约 57 分钟/).first()).toBeVisible();
  await expect(page.getByRole('img', { name: /高德步行道路折线示意/ }).locator('polyline')).toHaveCount(2);
});
