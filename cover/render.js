const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    headless: true,
    args: ['--no-sandbox', '--force-color-profile=srgb'],
  });
  const page = await browser.newPage({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 2,
  });
  await page.goto('file:///Volumes/WD%20Drive/%E9%A1%B9%E7%9B%AE/%E7%83%AD%E9%BA%A6%E5%8D%A1%E8%B7%AF%E9%87%8C/cover/cover-v2.html');
  await page.waitForTimeout(600);
  await page.screenshot({ path: '/Volumes/WD Drive/项目/热麦卡路里/cover/cover-v2.png' });
  await browser.close();
  console.log('rendered');
})();
