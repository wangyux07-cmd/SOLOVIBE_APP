import { test, expect } from '@playwright/test';

test('real browser shows official brand menu with source and no branch claim', async ({ page, context }) => {
  test.skip(process.env.SOLOVIBE_LIVE_V3_2 !== '1', 'Requires real backend, model, Amap, Tavily and PostgreSQL');
  test.setTimeout(240_000);
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ longitude: 121.435, latitude: 31.193, accuracy: 18 });
  await page.goto('/');
  await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('button', { name: '使用当前位置' }).click();
  await expect(page.getByText(/已记录：上海市/)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel('输入出行需求').fill('预算80元，可用时间120分钟，最多步行30分钟，只想去星巴克喝咖啡，计划停留30分钟，请规划。');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByRole('heading', { name: '可考虑的地点' })).toBeVisible({ timeout: 120_000 });
  const source = page.getByRole('region', { name: '公开来源资料' }).first();
  await expect(source.getByText('品牌菜单示例 · 未证实本分店有售或现价')).toBeVisible();
  await expect(source.getByRole('link', { name: '查看 www.starbucks.com.cn 原始页' })).toHaveAttribute('href',
    'https://www.starbucks.com.cn/menu/food/great-breakfast/');
  await expect(source.getByText('本分店菜单资料 · 来源已匹配门店')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('region', { name: '公开来源资料' }).first()
    .getByText('品牌菜单示例 · 未证实本分店有售或现价')).toBeVisible({ timeout: 30_000 });
});
