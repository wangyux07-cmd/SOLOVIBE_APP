import { test, expect } from '@playwright/test';

test('renders persisted route evidence and leaves unverified business facts unknown', async ({ page }) => {
  const thread = '00000000-0000-4000-8000-000000000001';
  await page.route('**/api/v1/health', route => route.fulfill({ json: { ready: true, stage: 'stage3' } }));
  await page.route('**/api/session', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/api/conversations', route => route.fulfill({ json: { conversations: [{ thread_id: thread }] } }));
  await page.route(`**/api/conversations/${thread}`, route => route.fulfill({ json: {
    thread_id: thread, snapshot: { revision: 2, constraints: { city: '上海', location_text: '徐家汇站', budget_cny: 60, available_minutes: 40 }, sources: {} },
    messages: [], pending_run: null, context_memory: { summary_revision: 0, covered_until_sequence: 0, raw_messages_retained: true },
    plan_set: { kind: 'options_ready', evidence_status: 'ok', provider_errors: [], plans: [{
      plan_id: 'amap:A1', context_revision: 2, place: { name: '徐家汇公园', address: '肇嘉浜路', category: '风景名胜', poi_id: 'A1', source_url: 'https://uri.amap.com/marker?position=121.439,31.196', observed_at: '2026-10-12T00:00:00Z' },
      route: { walking_minutes: 10, distance_meters: 750, observed_at: '2026-10-12T00:00:00Z' },
      facts: { rating: 4.2, average_cost_cny: 35, recorded_hours: '周一至周日 09:00-18:00', observed_at: '2026-10-12T00:00:00Z' },
      unknowns: ['实际消费', '当前营业状态', '到店可用性'], tradeoff: '步行约 10 分钟，750 米；预算与营业情况尚需核实。',
      web_status: 'results_unverified', web_sources: [{ title: '公园介绍', url: 'https://example.org/park', identity_status: 'unverified' }],
    }] },
  } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '可考虑的地点' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '徐家汇公园' })).toBeVisible();
  await expect(page.getByText('待核实：实际消费、当前营业状态、到店可用性')).toBeVisible();
  await expect(page.getByText('高德记录：评分 4.2 · 参考人均 35 元')).toBeVisible();
  await expect(page.getByText('网页搜索结果 · 未核实是否同一分店')).toBeVisible();
  await expect(page.getByRole('link', { name: '在高德查看地点' })).toHaveAttribute('href', /uri\.amap\.com/);
});
