import { test, expect } from '@playwright/test';

test('owner can delete a conversation and the UI starts a fresh one', async ({ page }) => {
  const oldThread = '00000000-0000-4000-8000-000000000051';
  const newThread = '00000000-0000-4000-8000-000000000052';
  const requests: string[] = [];
  const state = (thread_id: string) => ({ thread_id,
    snapshot: { revision: 0, constraints: {}, sources: {} }, messages: [],
    pending_run: null, plan_set: null, latest_action: null, saved_plans: [],
    context_memory: { summary_revision: 0, covered_until_sequence: 0, raw_messages_retained: true },
  });
  await page.route('**/api/v1/health', route => route.fulfill({ json: { ready: true, stage: 'v3-6' } }));
  await page.route('**/api/session', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/api/conversations', route => route.fulfill({ json: route.request().method() === 'GET'
    ? { conversations: [{ thread_id: oldThread }] } : state(newThread) }));
  await page.route(`**/api/conversations/${oldThread}`, route => {
    requests.push(route.request().method());
    return route.fulfill({ json: route.request().method() === 'DELETE' ? { deleted: true } : state(oldThread) });
  });
  await page.goto('/');
  await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '删除此会话' }).click();
  await expect.poll(() => requests).toContain('DELETE');
  await expect(page.getByText('数据库中的结构化状态 · 版本 0')).toBeVisible();
});
