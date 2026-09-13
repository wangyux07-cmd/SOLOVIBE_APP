import { test, expect } from '@playwright/test';

test('real proxy and backend report not-ready without synthetic recommendations', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('前端 → API → 后端，已连通')).toBeVisible();
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/chat'));
  await page.getByRole('button', { name: '验证聊天入口' }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(503);
  expect((await response.json()).error.code).toBe('AGENT_NOT_IMPLEMENTED');
  await expect(page.getByText('前后端已连通。当前正在建设 Agent，暂未执行模型、地图或网页查询。')).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: '../.runtime/baseline-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: '验证聊天入口' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../.runtime/baseline-mobile.png', fullPage: true });
});

test('unavailable backend clears prior success and disables the chat check', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('前端 → API → 后端，已连通')).toBeVisible();
  await page.route('**/api/v1/health', route => route.abort());
  await page.getByRole('button', { name: '刷新服务状态' }).click();
  await expect(page.getByText('后端尚未连接')).toBeVisible();
  await expect(page.getByRole('button', { name: '验证聊天入口' })).toBeDisabled();
  await expect(page.getByText('前端 → API → 后端，已连通')).toHaveCount(0);
});
