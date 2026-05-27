#!/usr/bin/env python3
"""
Bulk convert Tailwind hardcoded slate colors to CSS design tokens across ALL templates.

Strategy:
  Phase A: Remove dark: counterpart classes (CSS tokens auto-switch)
  Phase B: Convert hover:bg-slate-* to .hover-surface utility class
  Phase C: Convert bg-slate-* / text-slate-* / border-slate-* to inline style or token class
  Phase D: Convert form input styling patterns
  Phase E: Clean up doubled spaces from removals

Rules:
  - login.html, setup_pin.html, select_profile.html: SKIP (standalone pages)
  - Semantic colors (text-red-*, text-emerald-*, text-blue-*, text-amber-*, bg-amber-*, bg-red-*, bg-green-*, bg-emerald-*, bg-blue-*): PRESERVE
  - text-white: PRESERVE
  - Only color-related Tailwind classes are replaced
  - Layout classes untouched
"""
import re
import os
import glob

TEMPLATES_DIR = "/workspace/app_planners/jm/templates"
SKIP_FILES = {"login.html", "setup_pin.html", "select_profile.html"}

def process_file(filepath):
    fname = os.path.basename(filepath)
    if fname in SKIP_FILES:
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    original = content
    changes = 0

    # ====== A: Remove dark: counterpart classes ======
    # dark:text-slate-NNN
    content, n = re.subn(r' ?dark:text-slate-\d{2,3}\b', '', content)
    changes += n
    # dark:bg-slate-NNN and dark:bg-slate-NNN/NN
    content, n = re.subn(r' ?dark:bg-slate-\d{2,3}(?:/\d{1,3})?\b', '', content)
    changes += n
    # dark:border-slate-NNN and /NN
    content, n = re.subn(r' ?dark:border-slate-\d{2,3}(?:/\d{1,3})?\b', '', content)
    changes += n
    # dark:hover:bg-slate-NNN
    content, n = re.subn(r' ?dark:hover:bg-slate-\d{2,3}(?:/\d{1,3})?\b', '', content)
    changes += n
    # dark:hover:text-slate-NNN
    content, n = re.subn(r' ?dark:hover:text-slate-\d{2,3}\b', '', content)
    changes += n
    # dark:ring-offset-slate-NNN
    content, n = re.subn(r' ?dark:ring-offset-slate-\d{2,3}\b', '', content)
    changes += n

    # ====== B: Convert hover classes ======
    # hover:bg-slate-50 / hover:bg-slate-100 / hover:bg-slate-200 -> hover-surface
    content, n = re.subn(r'hover:bg-slate-(?:50|100|200)\b', 'hover-surface', content)
    changes += n
    # hover:bg-red-50 -> hover-surface (for delete button backgrounds)
    # Keep these as they have semantic meaning

    # hover:text-slate-NNN -> hover-text (so text becomes --color-text on hover)
    content, n = re.subn(r'hover:text-slate-(?:600|700|800)\b', 'hover-text', content)
    changes += n

    # hover:bg-slate-50/50 -> hover-surface
    content, n = re.subn(r'hover:bg-slate-50/50\b', 'hover-surface', content)
    changes += n

    # ====== C: Convert standalone color classes that don't have existing style ======
    # Pattern: class="... text-slate-NNN ..." where there's NO style="" on the same element
    # We'll do targeted replacements for common patterns

    # -- text-slate-800 / text-slate-700 -> replace class with style inline --
    # These are rare on their own, most are paired with dark: which we already removed

    # -- bg-white dark:bg-slate-800 -> bg-white (dark handled by token) --
    # After removing dark:bg-slate-800, bg-white remains which is fine for light mode
    # but in dark mode we need var(--color-surface)
    # Strategy: Replace "bg-white" (when it was paired with dark:bg-slate-800)
    # with style="background: var(--color-surface)"
    # But this is tricky. Let's handle the common button pattern instead.

    # ====== Common button pattern: bg-white ... text-slate-600 ... border border-slate-200 ======
    # These are filter/view toggle buttons. Replace with token equivalents.

    # Active/inactive toggle buttons pattern
    # inactive: bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700
    # After phase A: bg-white text-slate-600 border border-slate-200

    # Replace: "bg-white text-slate-600 border border-slate-200"
    # With inline style
    def replace_inactive_btn(m):
        return m.group(0).replace(
            'bg-white text-slate-600 border border-slate-200',
            'border'
        ).rstrip('"') + '" style="background: var(--color-surface); color: var(--color-text-muted); border-color: var(--color-border);"'

    # Actually, this is getting too complex with regex on HTML. Let me do simpler, safer replacements.

    # -- Simple class-only replacements for text colors --
    # text-slate-400 -> text color faint (using style merge would be complex)
    # Instead, leave these and handle them with the mobile CSS override that already exists in base.html

    # -- Form input backgrounds: bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 --
    # After phase A removal: bg-slate-50 border border-slate-200
    # These should use input-premium class or inline styles

    # Let's do targeted replacements for the most impactful patterns:

    # Pattern: "bg-slate-50 ... border border-slate-200" in form inputs
    # Replace bg-slate-50 with nothing (inputs will use var(--color-surface) from base)
    content, n = re.subn(r'bg-slate-50\b', '', content)
    changes += n

    # bg-white (only when it was a button/panel background, not a text-on-accent)
    # This is too broad - skip it to avoid breaking things

    # border-slate-200 -> (remove, base.html input styles handle it)
    content, n = re.subn(r'border-slate-200\b', '', content)
    changes += n

    # border-slate-100 -> remove (handled by token borders)
    content, n = re.subn(r'border-slate-100\b', '', content)
    changes += n

    # border-slate-300 -> remove
    content, n = re.subn(r'border-slate-300\b', '', content)
    changes += n

    # border-slate-500 -> remove
    content, n = re.subn(r'border-slate-500\b', '', content)
    changes += n

    # border-slate-600 -> remove
    content, n = re.subn(r'border-slate-600\b', '', content)
    changes += n

    # border-slate-700 -> remove (already handled border-subtle/border in style)
    content, n = re.subn(r'border-slate-700(?:/50)?\b', '', content)
    changes += n

    # bg-slate-100 -> remove (will fallback to card/surface backgrounds)
    content, n = re.subn(r'bg-slate-100(?:/50)?\b', '', content)
    changes += n

    # bg-slate-50/50 -> remove
    content, n = re.subn(r'bg-slate-50/50\b', '', content)
    changes += n

    # bg-slate-700 -> remove
    content, n = re.subn(r'bg-slate-700(?:/\d{1,2})?\b', '', content)
    changes += n

    # bg-slate-800 -> remove
    content, n = re.subn(r'bg-slate-800(?:/\d{1,2})?\b', '', content)
    changes += n

    # bg-slate-600 -> remove
    content, n = re.subn(r'bg-slate-600\b', '', content)
    changes += n

    # bg-white -> keep (it's a valid light-mode base, but for buttons that need dark mode support...)
    # Actually bg-white needs to stay for some elements. Let's be selective.

    # text-slate-800 -> remove (body color is already var(--color-text))
    content, n = re.subn(r'text-slate-800\b', '', content)
    changes += n

    # text-slate-700 -> remove (same as text, body inherits)
    content, n = re.subn(r'text-slate-700\b', '', content)
    changes += n

    # text-slate-600 -> keep for now (muted but visible text - will be close to --color-text-muted)
    # Actually let's remove and let body color handle it
    content, n = re.subn(r'text-slate-600\b', '', content)
    changes += n

    # text-slate-500 -> remove (muted, will inherit or be handled by inline)
    content, n = re.subn(r'text-slate-500\b', '', content)
    changes += n

    # text-slate-400 -> keep (faint text, already boosted by mobile CSS)
    # Actually remove - these should be --color-text-faint inline or inherit
    content, n = re.subn(r'text-slate-400\b', '', content)
    changes += n

    # text-slate-300 -> remove
    content, n = re.subn(r'text-slate-300\b', '', content)
    changes += n

    # text-slate-200 -> remove
    content, n = re.subn(r'text-slate-200\b', '', content)
    changes += n

    # bg-slate-200 -> remove
    content, n = re.subn(r'bg-slate-200\b', '', content)
    changes += n

    # hover:border-amber-300 / hover:border-amber-400 -> keep (accent hover)

    # ====== D: Clean up ======
    # Remove doubled/tripled spaces in class attributes
    content = re.sub(r'(class="[^"]*)"', lambda m: m.group(0).replace('  ', ' ').replace('  ', ' '), content)
    # Remove trailing spaces before closing quote in class
    content = re.sub(r' +"', '"', content)
    # Remove leading spaces after opening quote in class
    content = re.sub(r'class=" +', 'class="', content)
    # Remove empty class=""
    content = re.sub(r' class=""', '', content)
    # Remove empty border-only classes like "border border " -> "border"
    content = re.sub(r'border\s+border\b', 'border', content)

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return changes
    return 0


def main():
    files = sorted(glob.glob(os.path.join(TEMPLATES_DIR, "**", "*.html"), recursive=True))
    total = 0
    for fp in files:
        n = process_file(fp)
        if n > 0:
            rel = os.path.relpath(fp, TEMPLATES_DIR)
            print(f"  {rel}: {n} replacements")
            total += n
    print(f"\nTotal: {total} replacements across {len(files)} files")


if __name__ == "__main__":
    main()
