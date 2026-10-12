import { test, expect } from '@playwright/test';

test('real browser receives persisted Amap options through LangGraph', async ({ page }) => {
  test.skip(process.env.SOLOVIBE_LIVE_STAGE3 !== '1', 'Requires real local model, database, Amap and optional Tavily credentials');
  await page.goto('/');
  await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible();
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('输入出行需求').fill('城市：上海。出发点：徐家汇地铁站。预算：60元。可用时间：40分钟。最多步行：25分钟。偏好：公园。请规划。');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('heading', { name: '可考虑的地点' })).toBeVisible({ timeout: 90000 });
  const links = page.getByRole('link', { name: '在高德查看地点' });
  const count = await links.count();
  expect(count).toBeGreaterThanOrEqual(1);
  expect(count).toBeLessThanOrEqual(3);
  await expect(page.getByText(/待核实：实际消费、当前营业状态、到店可用性/).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '可考虑的地点' })).toBeVisible();
  expect(await page.getByRole('link', { name: '在高德查看地点' }).count()).toBe(count);
});
