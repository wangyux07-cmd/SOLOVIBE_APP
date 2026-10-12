import { test, expect } from '@playwright/test';

test.skip(process.env.SOLOVIBE_LIVE !== '1', 'Requires configured real backend and model; opt in explicitly.');

test('real UI completes a graph turn and displays persisted evidence', async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto('/');
  await expect(page.getByText('数据库与模型启动检查已通过')).toBeVisible();
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('输入出行需求').fill('我在上海徐汇，预算80元，只有一小时。');
  await page.getByRole('button', { name: '发送消息' }).click();
  await expect(page.getByText('我在上海徐汇，预算80元，只有一小时。')).toBeVisible();
  await expect(page.getByText('数据库中的结构化状态 · 版本 1')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText('80', { exact: true })).toBeVisible();
  await expect(page.getByText('understand_context')).toBeVisible();
  await page.reload();
  await expect(page.getByText('数据库中的结构化状态 · 版本 1')).toBeVisible();
  await expect(page.getByText('80', { exact: true })).toBeVisible();
});
