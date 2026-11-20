/**
 * Comprehensive Mobile-First Playwright QA & Screenshot Tool for RunSummarizer
 *
 * Viewports:
 *   - iPhone (375x812) - Key stress test for small screens
 *   - Android (412x915) - Standard Android screen
 *
 * Themes:
 *   - Light Mode & Dark Mode
 *
 * Views & States:
 *   - /home
 *   - /activities (default & filters opened)
 *   - /activities/run-101 (default & edit laps mode)
 *   - /trends
 *   - /calendar
 *
 * Automated Assertions:
 *   - Horizontal overflow detection (scrollWidth > innerWidth or elements extending beyond viewport)
 */

const { chromium } = require('../node_modules/playwright');
const fs = require('fs');
const path = require('path');

const VIEWPORTS = [
  { name: 'iphone-375', width: 375, height: 812 },
  { name: 'android-412', width: 412, height: 915 },
];

const THEMES = ['light', 'dark'];

const BASE_URL = process.env.URL || 'http://localhost:5173';
const OUT_DIR = path.resolve(__dirname, '../../screenshots/mobile');

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

async function checkHorizontalOverflow(page, viewName) {
  return await page.evaluate((name) => {
    const docWidth = document.documentElement.scrollWidth;
    const bodyWidth = document.body.scrollWidth;
    const winWidth = window.innerWidth;
    const hasDocOverflow = docWidth > winWidth || bodyWidth > winWidth;

    const overflowingElements = [];
    const elements = document.querySelectorAll('*');
    for (const el of elements) {
      const rect = el.getBoundingClientRect();
      // Ignore hidden or fixed/backdrop elements that don't cause scroll
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.right > winWidth + 1.5) {
        overflowingElements.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || undefined,
          className: (el.className && typeof el.className === 'string') ? el.className.split(' ').slice(0, 4).join(' ') : undefined,
          overflowPx: Math.round(rect.right - winWidth),
        });
      }
    }

    return {
      viewName: name,
      hasOverflow: hasDocOverflow || overflowingElements.length > 0,
      docWidth,
      winWidth,
      elements: overflowingElements.slice(0, 3),
    };
  }, viewName);
}

async function applyTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('runsummarizer-theme', t);
    if (t === 'dark') {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
      document.documentElement.style.colorScheme = 'dark';
    } else {
      document.documentElement.classList.remove('dark');
      document.documentElement.classList.add('light');
      document.documentElement.style.colorScheme = 'light';
    }
  }, theme);
  await page.waitForTimeout(300);
}

async function runMobileAudit() {
  console.log(`[Mobile QA] Launching Chrome against ${BASE_URL}...`);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const overflowIssues = [];

  for (const vp of VIEWPORTS) {
    console.log(`\n========================================`);
    console.log(`📱 VIEWPORT: ${vp.name} (${vp.width}x${vp.height})`);
    console.log(`========================================`);

    for (const theme of THEMES) {
      console.log(`\n--- Theme: ${theme.toUpperCase()} ---`);

      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
      });
      const page = await context.newPage();

      // 1. Home Page
      {
        await page.goto(`${BASE_URL}/home`, { waitUntil: 'networkidle', timeout: 15000 });
        await applyTheme(page, theme);
        const check = await checkHorizontalOverflow(page, 'home');
        if (check.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...check });
        const filePath = path.join(OUT_DIR, `home-${vp.name}-${theme}.png`);
        await page.screenshot({ path: filePath, fullPage: true });
        console.log(`  ✓ Home saved: ${path.basename(filePath)} (Overflow: ${check.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);
      }

      // 2. Activities List (Default)
      {
        await page.goto(`${BASE_URL}/activities`, { waitUntil: 'networkidle', timeout: 15000 });
        await applyTheme(page, theme);
        const check = await checkHorizontalOverflow(page, 'activities');
        if (check.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...check });
        const filePath = path.join(OUT_DIR, `activities-${vp.name}-${theme}.png`);
        await page.screenshot({ path: filePath, fullPage: true });
        console.log(`  ✓ Activities saved: ${path.basename(filePath)} (Overflow: ${check.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);

        // 2b. Activities Filter Toggled Open
        try {
          const filterBtn = await page.$('button[aria-controls="activity-filters"]');
          if (filterBtn) {
            await filterBtn.click();
            await page.waitForTimeout(300);
            const filterCheck = await checkHorizontalOverflow(page, 'activities-filters-open');
            if (filterCheck.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...filterCheck });
            const filterFilePath = path.join(OUT_DIR, `activities-filters-open-${vp.name}-${theme}.png`);
            await page.screenshot({ path: filterFilePath, fullPage: true });
            console.log(`  ✓ Activities Filters Open saved: ${path.basename(filterFilePath)} (Overflow: ${filterCheck.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);
          }
        } catch (e) {
          console.warn('    Could not toggle filters:', e.message);
        }
      }

      // 3. Activity Detail (Default)
      {
        await page.goto(`${BASE_URL}/activities/run-101`, { waitUntil: 'networkidle', timeout: 15000 });
        await applyTheme(page, theme);
        const check = await checkHorizontalOverflow(page, 'activity-detail');
        if (check.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...check });
        const filePath = path.join(OUT_DIR, `activity-detail-${vp.name}-${theme}.png`);
        await page.screenshot({ path: filePath, fullPage: true });
        console.log(`  ✓ Activity Detail saved: ${path.basename(filePath)} (Overflow: ${check.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);

        // 3b. Activity Detail Edit Lap Types Toggled
        try {
          const editBtn = await page.getByRole('button', { name: /Edit Lap Types/i });
          if (await editBtn.isVisible()) {
            await editBtn.click();
            await page.waitForTimeout(300);
            const editCheck = await checkHorizontalOverflow(page, 'activity-detail-edit-laps');
            if (editCheck.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...editCheck });
            const editFilePath = path.join(OUT_DIR, `activity-detail-edit-laps-${vp.name}-${theme}.png`);
            await page.screenshot({ path: editFilePath, fullPage: true });
            console.log(`  ✓ Activity Detail Edit Laps saved: ${path.basename(editFilePath)} (Overflow: ${editCheck.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);
          }
        } catch (e) {
          console.warn('    Could not click Edit Lap Types:', e.message);
        }
      }

      // 4. Trends Page
      {
        await page.goto(`${BASE_URL}/trends`, { waitUntil: 'networkidle', timeout: 15000 });
        await applyTheme(page, theme);
        const check = await checkHorizontalOverflow(page, 'trends');
        if (check.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...check });
        const filePath = path.join(OUT_DIR, `trends-${vp.name}-${theme}.png`);
        await page.screenshot({ path: filePath, fullPage: true });
        console.log(`  ✓ Trends saved: ${path.basename(filePath)} (Overflow: ${check.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);
      }

      // 5. Calendar Page
      {
        await page.goto(`${BASE_URL}/calendar`, { waitUntil: 'networkidle', timeout: 15000 });
        await applyTheme(page, theme);
        const check = await checkHorizontalOverflow(page, 'calendar');
        if (check.hasOverflow) overflowIssues.push({ vp: vp.name, theme, ...check });
        const filePath = path.join(OUT_DIR, `calendar-${vp.name}-${theme}.png`);
        await page.screenshot({ path: filePath, fullPage: true });
        console.log(`  ✓ Calendar saved: ${path.basename(filePath)} (Overflow: ${check.hasOverflow ? 'FAIL ❌' : 'PASS ✅'})`);
      }

      await context.close();
    }
  }

  await browser.close();

  console.log(`\n========================================`);
  console.log(`OVERFLOW AUDIT SUMMARY:`);
  console.log(`========================================`);
  if (overflowIssues.length === 0) {
    console.log(`✅ ZERO horizontal overflow issues detected across all mobile viewports!`);
  } else {
    console.warn(`❌ Detected ${overflowIssues.length} horizontal overflow issues:`);
    console.dir(overflowIssues, { depth: null });
  }
}

runMobileAudit().catch((err) => {
  console.error(err);
  process.exit(1);
});
