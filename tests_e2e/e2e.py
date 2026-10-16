import asyncio, json
from playwright.async_api import async_playwright
B='http://127.0.0.1:8000'; import os; os.makedirs('e2e-out', exist_ok=True); O='./e2e-out/'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width':1440,'height':1000})
        pg = await ctx.new_page(); errs=[]
        pg.on('pageerror', lambda e: errs.append('PAGEERR '+str(e)))
        pg.on('console', lambda m: errs.append(m.text) if m.type=='error' and 'openstreetmap' not in m.text and 'ERR_TUNNEL' not in m.text else None)
        await pg.goto(B+'/#map'); await pg.wait_for_selector('.card-head', timeout=20000); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=O+'1-miner-map.png')
        print('miner occ toggle present:', await pg.locator('#L-occ').count())
        # field app offline
        await pg.click('text=Plan a field check'); await pg.wait_for_selector('#ftarget')
        await ctx.set_offline(True); await pg.wait_for_timeout(300)
        await pg.fill('#mlat','-19.664'); await pg.fill('#mlon','30.012')
        await pg.click('.tile >> nth=0'); await pg.click('.tile >> nth=3')
        await pg.set_input_files('input[type=file]', 'tests_e2e/rock.jpg'); await pg.wait_for_timeout(500)
        await pg.fill('#fobs','Test group'); await pg.click('text=Save record'); await pg.wait_for_timeout(800)
        print('offline outbox:', await pg.locator('.outbox li').all_inner_texts())
        await pg.screenshot(path=O+'2-field-offline.png', full_page=True)
        await ctx.set_offline(False); await pg.wait_for_timeout(3000)
        print('after online:', await pg.locator('.outbox li').all_inner_texts())
        # geologist
        await pg.evaluate("localStorage.setItem('wana.geoKey','geo123')"); await pg.goto(B+'/#review'); await pg.reload(); await pg.wait_for_selector('table tbody tr')
        await pg.wait_for_timeout(800)
        rows = await pg.locator('table tbody tr').count(); print('review rows', rows)
        await pg.fill('td input[type=number] >> nth=0','38.5'); await pg.click('tbody button:has-text("Chrome") >> nth=0'); await pg.wait_for_timeout(300); await pg.click('tbody button:has-text("Not chrome") >> nth=0'); await pg.wait_for_timeout(600)
        await pg.click('button:has-text("Update map")'); await pg.wait_for_selector('text=Model v1:', timeout=60000)
        await pg.screenshot(path=O+'3-review.png', full_page=True)
        await pg.click('nav.tabs >> text=Wana Map'); await pg.wait_for_selector('.card-head'); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=O+'4-geo-map.png')
        await pg.click('nav.tabs >> text=Validation'); await pg.wait_for_selector('svg.curve'); await pg.screenshot(path=O+'5-val.png', full_page=True)
        await pg.click('nav.tabs >> text=Data sources'); await pg.wait_for_timeout(300); await pg.screenshot(path=O+'6-data.png', full_page=True)
        ov = await pg.evaluate('document.documentElement.scrollWidth>innerWidth'); print('overflow', ov)
        m = await b.new_page(viewport={'width':390,'height':844}, is_mobile=True)
        await m.goto(B+'/#field'); await m.wait_for_selector('.tiles'); await m.screenshot(path=O+'7-mobile-field.png', full_page=True)
        print('mobile overflow', await m.evaluate('document.documentElement.scrollWidth>innerWidth'))
        print('errors', errs)
        await b.close()
asyncio.run(main())
