#!/usr/bin/env python3
"""Fix usage hint patterns and remaining interactive element visibility issues."""
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

    # ====== Fix 1: Usage hint summary -- add style for text color ======
    # Pattern: <summary class="inline-flex items-center gap-1.5 text-xs hover:text-amber-500 cursor-pointer transition-colors select-none">
    # Missing: color (was text-slate-400, removed by script)
    # Fix: Add style="color: var(--color-text-faint)"
    content = content.replace(
        'class="inline-flex items-center gap-1.5 text-xs hover:text-amber-500 cursor-pointer transition-colors select-none">',
        'class="inline-flex items-center gap-1.5 text-xs hover:text-amber-500 cursor-pointer transition-colors select-none" style="color: var(--color-text-faint);">'
    )

    # ====== Fix 1b: Usage hint icon size: w-3.5 h-3.5 -> w-4 h-4 ======
    # Only inside summary elements that contain "사용법"
    # Pattern: <svg class="w-3.5 h-3.5" ... >...사용법
    # This is tricky to target precisely with regex. Let's target the specific SVG pattern.
    content = content.replace(
        'class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0',
        'class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0'
    )

    # ====== Fix 2: Usage hint content div -- add token styles ======
    # Pattern: bg-amber-50/50 dark:bg-amber-900/10 ... border-amber-100 dark:border-amber-800/30
    # Replace with: style="background: var(--color-accent-soft); border-color: var(--color-accent-soft);"
    # The class still has rounded-xl text-xs leading-relaxed space-y-1

    # After the script removed text-slate-600 and dark: classes, the div looks like:
    # "mt-2 p-3 bg-amber-50/50 dark:bg-amber-900/10 border-amber-100 dark:border-amber-800/30 rounded-xl text-xs leading-relaxed space-y-1"
    # But script only removed dark:bg-slate-* and dark:text-slate-*, NOT dark:bg-amber-* or dark:border-amber-*
    # So it should still have those. Let me handle the whole pattern.

    content = content.replace(
        'bg-amber-50/50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/30 rounded-xl text-xs leading-relaxed space-y-1',
        'border rounded-xl text-xs leading-relaxed space-y-1" style="background: var(--color-accent-soft); border-color: var(--color-accent-soft); color: var(--color-text-muted);'
    )

    # Handle variant without "border border-amber-100" but with "border-amber-100"
    content = content.replace(
        'bg-amber-50/50 dark:bg-amber-900/10 border-amber-100 dark:border-amber-800/30 rounded-xl text-xs leading-relaxed space-y-1',
        'border rounded-xl text-xs leading-relaxed space-y-1" style="background: var(--color-accent-soft); border-color: var(--color-accent-soft); color: var(--color-text-muted);'
    )

    # ====== Fix 3: Bold labels inside hints -- add color token ======
    # <b class="text-slate-700 dark:text-slate-300"> was cleaned to <b class="">
    # Fix: add style for contrast
    content = re.sub(
        r'<b class=""?>',
        '<b style="color: var(--color-text);">',
        content
    )
    # Also handle <b> without class at all (some may have been already clean)
    # Leave those as-is, they inherit

    # ====== Fix 4: "옵션 더보기" / filter summary patterns ======
    # Similar to usage hints but slightly different patterns
    # <summary class="inline-flex items-center gap-1.5 text-xs hover:text-amber-500 ...">
    # These were also cleaned. Check for ones that lost color.

    # ====== Fix 5: Divider text (separator "|") ======
    # text-slate-300 dark:text-slate-600 was cleaned to just "text-xs"
    # These had class="text-slate-300 dark:text-slate-600 text-xs"
    # After cleaning: class="text-xs"
    # Fine - these dividers will inherit body color, which is acceptable

    # ====== Fix 6: bg-white buttons that lost dark mode ======
    # Many buttons had: bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700
    # After cleaning: bg-white border
    # These need proper token styling. Add inline style.
    # Pattern: class="... bg-white ... border ..." without any style=""

    # Actually, these buttons have various structures. Let me handle the most common patterns:
    # "bg-white border hover:border-amber-300" or "bg-white border hover:border-amber-400"
    content = content.replace(
        'bg-white border hover:border-amber-300',
        'border" style="background: var(--color-surface); color: var(--color-text-muted); border-color: var(--color-border);'
    )
    content = content.replace(
        'bg-white border hover:border-amber-400',
        'border" style="background: var(--color-surface); color: var(--color-text-muted); border-color: var(--color-border);'
    )

    # Simple: bg-white border (in buttons)
    # This is too broad, many uses. Skip.

    # ====== Fix 7: Input field styling ======
    # Inputs had: bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600
    # After cleaning: border
    # These inputs should use input-premium class or inherit base.html mobile overrides
    # The mobile CSS already forces proper input styling, so this is fine

    # ====== Fix 8: Empty spaces in class after bg-white ======
    # "bg-white border" -> just "bg-white border" is fine for light mode
    # In dark mode, bg-white would be wrong. We need it to be var(--color-surface).
    # But replacing ALL bg-white is dangerous. Let's only target button patterns.

    # Fix class="" cleanup
    content = re.sub(r'class=" +', 'class="', content)
    content = re.sub(r' +"', '"', content)
    content = re.sub(r'  +', ' ', content)

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return 1
    return 0


def main():
    files = sorted(glob.glob(os.path.join(TEMPLATES_DIR, "**", "*.html"), recursive=True))
    modified = 0
    for fp in files:
        if process_file(fp):
            print(f"  Fixed: {os.path.relpath(fp, TEMPLATES_DIR)}")
            modified += 1
    print(f"\nModified {modified} files")


if __name__ == "__main__":
    main()
