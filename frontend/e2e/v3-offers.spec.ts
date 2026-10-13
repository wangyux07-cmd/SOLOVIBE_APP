import { test, expect } from '@playwright/test';

test('expired offer disappears from decision and blocks old confirmation', async ({ page }) => {
  const thread = '00000000-0000-4000-8000-000000000003';
  const old = new Date(Date.now() - 60_000).toISOString();
  await page.route('**/api/v1/health', route => route.fulfill({ json: { ready: true, stage: 'v3-3' } }));
  await page.route('**/api/session', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/api/conversations', route => route.fulfill({ json: { conversations: [{ thread_id: thread }] } }));
  await page.route(`**/api/conversations/${thread}`, route => route.fulfill({ json: {
    thread_id: thread, snapshot: { revision: 2, constraints: { city: '上海市', budget_cny: 50 }, sources: {} },
    messages: [], pending_run: null, context_memory: { summary_revision: 0, covered_until_sequence: 0, raw_messages_retained: true },
    plan_set: { plan_set_id: '00000000-0000-4000-8000-000000000004', kind: 'options_ready',
      evidence_status: 'success', provider_errors: [], plans: [{
        plan_id: 'amap:A1', context_revision: 2,
        place: { name: '样例面馆(美罗城店)', address: '肇嘉浜路1111号', category: '餐饮', poi_id: 'A1',
          source_url: 'https://uri.amap.com/marker', observed_at: old },
        route: { walking_minutes: 8, distance_meters: 500, observed_at: old }, facts: null,
        budget_option: 'known_offer_within_limit',
        public_info: { status: 'success', sources: [{ url: 'https://official.example/offer',
          observed_at: old, scope: 'branch', source_domain: 'official.example', extract_status: 'success', field_scope: 'offer' }],
          brand_menu_items: [], branch_menu_items: [], admission_prices: [], offers: [{
            claim_id: 'C1', description: '午餐套餐', price_cny: 38, terms: '仅堂食', applies_to: '样例面馆(美罗城店)',
            valid_until: old, source_url: 'https://official.example/offer', observed_at: old,
            budget_option: 'within_limit' }] },
        unknowns: ['实际消费', '当前营业状态'], tradeoff: '路线已核实', web_status: 'empty', web_sources: [],
      }] },
  } }));
  await page.goto('/');
  await expect(page.getByText('套餐证据已过期，请重新生成方案后再确认。')).toBeVisible();
  await expect(page.getByText('本地点有条件套餐 · 请按条款核对')).toHaveCount(0);
  await expect(page.getByText('有来源套餐价格不超过预算')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '保存此方案' })).toBeDisabled();
});
