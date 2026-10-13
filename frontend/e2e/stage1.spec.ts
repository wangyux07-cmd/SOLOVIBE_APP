import { test, expect } from '@playwright/test';

test('shows the actual Stage 1 service state and never invents a result', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const healthResponse = await page.request.get('/api/v1/health');
  expect(healthResponse.ok()).toBeTruthy();
  const health = await healthResponse.json();
  await page.goto('/');
  await expect(page.getByText('把当下想做的事，慢慢说清楚。')).toBeVisible();
  if (health.ready) {
    await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible();
    await expect(page.getByLabel('输入出行需求')).toBeEnabled({ timeout: 15000 });
  } else {
    await expect(page.getByText(`尚未就绪：${health.blocker.message}`)).toBeVisible();
    await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled();
  }
  expect(errors).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('clearly reports a disconnected backend', async ({ page }) => {
  await page.route('**/api/v1/health', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Failed to fetch');
  await expect(page.getByRole('button', { name: '发送消息' })).toBeDisabled();
});
