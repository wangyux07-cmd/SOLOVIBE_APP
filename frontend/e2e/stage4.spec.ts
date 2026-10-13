import { test, expect } from '@playwright/test';

test('requires review before navigation handoff and restores receipt after reload', async ({ page }) => {
  const thread = '00000000-0000-4000-8000-000000000041';
  const planSetId = '00000000-0000-4000-8000-000000000042';
  const actionId = '00000000-0000-4000-8000-000000000043';
  const plan = { plan_id: 'amap:A1', context_revision: 2,
    place: { name: '徐家汇公园', address: '肇嘉浜路', category: '公园', poi_id: 'A1', source_url: 'https://uri.amap.com/marker?position=121.439,31.196', observed_at: '2026-10-12T00:00:00Z' },
    route: { walking_minutes: 10, distance_meters: 750, observed_at: '2026-10-12T00:00:00Z' },
    facts: null, unknowns: ['实际消费', '当前营业状态', '到店可用性'], tradeoff: '步行约 10 分钟', web_status: 'empty', web_sources: [] };
  const base = { action_id: actionId, plan_id: plan.plan_id, kind: 'navigate', proposal_version: 1,
    proposal_digest: 'a'.repeat(64), plan_snapshot: plan, expires_at: '2026-10-12T12:00:00Z' };
  let latest: object | null = null;
  await page.route('**/api/v1/health', route => route.fulfill({ json: { ready: true, stage: 'stage4' } }));
  await page.route('**/api/session', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/api/conversations', route => route.fulfill({ json: { conversations: [{ thread_id: thread }] } }));
  await page.route(`**/api/conversations/${thread}`, route => route.fulfill({ json: {
    thread_id: thread, snapshot: { revision: 2, constraints: {}, sources: {} }, messages: [], pending_run: null,
    plan_set: { plan_set_id: planSetId, kind: 'options_ready', evidence_status: 'ok', provider_errors: [], plans: [plan] },
    latest_action: latest, context_memory: { summary_revision: 0, covered_until_sequence: 0, raw_messages_retained: true },
  } }));
  await page.route(`**/api/conversations/${thread}/actions`, route => {
    latest = { ...base, status: 'awaiting_confirmation', receipt: null };
    return route.fulfill({ json: latest });
  });
  await page.route(`**/api/actions/${actionId}/decision`, async route => {
    const request = route.request().postDataJSON();
    expect(request.approve).toBe(true);
    expect(request.proposal_digest).toBe(base.proposal_digest);
    latest = { ...base, status: 'completed', receipt: { kind: 'navigation_handoff_ready',
      url: 'https://uri.amap.com/navigation?from=121.436%2C31.194&to=121.439%2C31.196&mode=walk' } };
    return route.fulfill({ json: latest });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '准备步行导航' }).click();
  await expect(page.getByRole('region', { name: '行动确认' })).toContainText('请核对地点');
  await expect(page.getByRole('link', { name: '打开高德步行导航' })).toHaveCount(0);
  await page.getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.getByRole('link', { name: '打开高德步行导航' })).toHaveAttribute('href', /mode=walk/);
  await page.reload();
  await expect(page.getByRole('link', { name: '打开高德步行导航' })).toBeVisible();
});
