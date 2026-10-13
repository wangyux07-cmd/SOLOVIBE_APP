import { test, expect } from '@playwright/test';

test('real browser sample location yields full-trip options and navigation handoff', async ({ page, context }) => {
  test.skip(process.env.SOLOVIBE_LIVE_V3_1 !== '1', 'Requires real backend, model, Amap and PostgreSQL');
  test.setTimeout(240_000);
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ longitude: 121.430000, latitude: 31.190000, accuracy: 18 });
  await page.goto('/');
  await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('button', { name: '使用当前位置' }).click();
  await expect(page.getByText(/已记录：上海市/)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel('输入出行需求').fill('预算80元，可用时间120分钟，最多步行30分钟，想去公园，计划停留30分钟，返程回到原出发点，请规划。');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('heading', { name: '可考虑的地点' })).toBeVisible({ timeout: 120_000 });
  const firstPlan = page.getByRole('article').filter({ hasText: '返程步行约' }).first();
  await expect(firstPlan.getByText(/返程步行约/)).toBeVisible();
  await expect(firstPlan.getByText(/＋缓冲 10 ＝约 \d+ 分钟/)).toBeVisible();
  await expect(firstPlan.getByRole('img', { name: /高德步行道路折线示意/ }).locator('polyline')).toHaveCount(2);
  await firstPlan.getByRole('button', { name: '准备步行导航' }).click();
  await expect(page.getByRole('region', { name: '行动确认' })).toContainText('请核对地点');
  await page.getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.getByRole('link', { name: '打开高德步行导航' })).toHaveAttribute('href', /mode=walk/, { timeout: 90_000 });
});
