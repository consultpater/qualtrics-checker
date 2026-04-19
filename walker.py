"""Walk a Qualtrics survey end-to-end with Playwright and extract question content."""
from __future__ import annotations

import asyncio
import re
from typing import List

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeoutError

from .models import FoundQuestion, LinkReport


MAX_PAGES = 60  # safety cap
PAGE_TIMEOUT_MS = 15000


async def _extract_questions(page: Page, page_index: int) -> List[FoundQuestion]:
    """Pull visible questions (text + type + options) out of the current Qualtrics page."""
    # Run one JS eval that returns serializable question objects.
    data = await page.evaluate(
        """
        () => {
          const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();

          // Qualtrics renders each question inside a wrapper with class containing 'QuestionOuter'
          // or role='listitem'. Cover both.
          const blocks = Array.from(document.querySelectorAll(
            '.QuestionOuter, [role="listitem"], .Skin .QuestionBody'
          ));

          // Deduplicate: sometimes a wrapper contains another wrapper.
          const seen = new Set();
          const results = [];

          for (const el of blocks) {
            if (seen.has(el)) continue;
            // If a child block is present, prefer the deepest unique one.
            const inner = el.querySelector('.QuestionOuter');
            const target = inner && !seen.has(inner) ? inner : el;
            if (seen.has(target)) continue;
            seen.add(target);

            const textNode = target.querySelector('.QuestionText, [class*="QuestionText"]');
            const text = clean(textNode ? textNode.innerText : '');
            if (!text) continue;

            // Classify.
            let type = 'unknown';
            const opts = [];
            if (target.querySelector('input[type="radio"]')) type = 'radio';
            else if (target.querySelector('input[type="checkbox"]')) type = 'checkbox';
            else if (target.querySelector('textarea')) type = 'textarea';
            else if (target.querySelector('input[type="text"], input[type="number"], input:not([type])')) type = 'text';
            else if (target.querySelector('select')) type = 'dropdown';
            else if (target.querySelector('[class*="Matrix"] table, table.Matrix')) type = 'matrix';
            else if (target.querySelector('[class*="Slider"]')) type = 'slider';
            else if (target.querySelector('[class*="RankOrder"], [class*="DragDrop"]')) type = 'rank';

            // Collect option labels where applicable.
            target.querySelectorAll('.LabelWrapper, label.SingleAnswer, label.MultipleAnswer, .ChoiceStructure label, select option').forEach(l => {
              const t = clean(l.innerText || l.textContent || '');
              if (t && !opts.includes(t)) opts.push(t);
            });

            const required = !!target.querySelector('.QuestionText .q-required, .q-required, [aria-required="true"]');

            results.push({ text, type, options: opts.slice(0, 40), required });
          }
          return results;
        }
        """
    )
    return [
        FoundQuestion(
            page=page_index,
            text=q["text"],
            type=q["type"],
            options=q["options"],
            required=q["required"],
        )
        for q in data
    ]


async def _fill_page(page: Page) -> None:
    """Best-effort auto-fill so we can advance past required questions."""
    try:
        # Radios: click the first choice in each radio group.
        await page.evaluate(
            """
            () => {
              const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
              const seenName = new Set();
              for (const r of radios) {
                if (seenName.has(r.name)) continue;
                seenName.add(r.name);
                if (!r.disabled) { r.click(); }
              }
              // Checkboxes: tick the first one per question block.
              document.querySelectorAll('.QuestionOuter').forEach(q => {
                const cb = q.querySelector('input[type="checkbox"]');
                if (cb && !cb.checked && !cb.disabled) cb.click();
              });
              // Textareas & text inputs: fill with 'test' if empty.
              document.querySelectorAll('textarea').forEach(t => {
                if (!t.value) {
                  t.value = 'test';
                  t.dispatchEvent(new Event('input', {bubbles: true}));
                  t.dispatchEvent(new Event('change', {bubbles: true}));
                }
              });
              document.querySelectorAll('input[type="text"], input[type="number"], input:not([type])').forEach(t => {
                if (t.type === 'radio' || t.type === 'checkbox') return;
                if (!t.value) {
                  t.value = t.type === 'number' ? '1' : 'test';
                  t.dispatchEvent(new Event('input', {bubbles: true}));
                  t.dispatchEvent(new Event('change', {bubbles: true}));
                }
              });
              // Dropdowns: pick the last option (to avoid placeholder).
              document.querySelectorAll('select').forEach(s => {
                if (s.selectedIndex <= 0 && s.options.length > 1) {
                  s.selectedIndex = s.options.length - 1;
                  s.dispatchEvent(new Event('change', {bubbles: true}));
                }
              });
              // Matrix: in each row, click the first radio.
              document.querySelectorAll('[class*="Matrix"] tr, table.Matrix tr').forEach(row => {
                const r = row.querySelector('input[type="radio"]');
                if (r && !r.checked && !r.disabled) r.click();
              });
            }
            """
        )
    except Exception:
        pass


async def _click_next(page: Page) -> bool:
    """Click the Next button. Returns True if a click happened."""
    selectors = [
        "#NextButton",
        "button#NextButton",
        "button[id*='NextButton']",
        ".NextButton",
        "input#NextButton",
        "[id^='next']",
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                return True
        except Exception:
            continue
    return False


async def _is_end_of_survey(page: Page) -> bool:
    try:
        return await page.evaluate(
            """
            () => {
              const t = document.body.innerText.toLowerCase();
              return (
                t.includes('thank you for') ||
                t.includes('survey is complete') ||
                t.includes('end of survey') ||
                t.includes('powered by qualtrics') && !document.querySelector('#NextButton')
              );
            }
            """
        )
    except Exception:
        return False


async def _has_validation_error(page: Page) -> str | None:
    try:
        err = await page.evaluate(
            """
            () => {
              const sels = ['.ValidationError', '.QuestionText .ErrorMsg', '[class*="Error"]:not(script)', '.error-message'];
              for (const s of sels) {
                const el = document.querySelector(s);
                if (el) {
                  const txt = (el.innerText || '').trim();
                  if (txt && el.offsetParent !== null) return txt;
                }
              }
              return null;
            }
            """
        )
        return err
    except Exception:
        return None


async def walk(url: str) -> LinkReport:
    report = LinkReport(url=url, ok=True, pages_visited=0)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        except PWTimeoutError:
            report.ok = False
            report.errors.append(f"Timeout loading {url}")
            await browser.close()
            return report
        except Exception as e:
            report.ok = False
            report.errors.append(f"Failed to load: {e}")
            await browser.close()
            return report

        # If the URL is clearly not a Qualtrics survey, flag it.
        page_url = page.url.lower()
        if "qualtrics" not in page_url and "qualtrics.com" not in page_url and "qtrics" not in page_url:
            # We still try — some clients use custom domains. Just note it.
            report.errors.append(f"URL does not appear to be a Qualtrics domain (landed on {page.url})")

        page_index = 0
        while page_index < MAX_PAGES:
            page_index += 1
            # Give the page a beat to render.
            try:
                await page.wait_for_selector(".QuestionOuter, .Skin, #Buttons", timeout=PAGE_TIMEOUT_MS)
            except PWTimeoutError:
                # Could be end of survey; check.
                if await _is_end_of_survey(page):
                    break
                report.errors.append(f"Page {page_index}: no question content found")
                break

            # Extract.
            qs = await _extract_questions(page, page_index)
            report.found_questions.extend(qs)

            if await _is_end_of_survey(page):
                break

            # Fill + advance.
            await _fill_page(page)
            clicked = await _click_next(page)
            if not clicked:
                # Nothing to click: either end or a problem.
                if await _is_end_of_survey(page):
                    break
                report.errors.append(f"Page {page_index}: no Next button and not end of survey")
                break

            # Wait for either navigation or next page render.
            try:
                await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
            except PWTimeoutError:
                pass

            # Check for validation error keeping us on the same page.
            err = await _has_validation_error(page)
            if err:
                report.errors.append(f"Page {page_index}: validation error — {err}")
                # Try to fill more aggressively once, then re-click.
                await _fill_page(page)
                await _click_next(page)
                try:
                    await page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS)
                except PWTimeoutError:
                    pass
                err2 = await _has_validation_error(page)
                if err2:
                    report.errors.append(f"Page {page_index}: still blocked — {err2}")
                    break

        report.pages_visited = page_index
        await browser.close()
    return report
