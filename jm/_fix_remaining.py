#!/usr/bin/env python3
"""Fix remaining dark-mode and visibility issues after bulk token conversion.

Issues addressed:
1. bg-white → style="background: var(--color-surface)" for dark mode compatibility
2. Muted helper text (text-xs without font-weight) that lost color → add color token
3. Form label elements that need muted color
4. Separator/divider text that needs faint color
5. Interactive elements minimum visibility
6. Remaining dark:hover: classes on non-slate elements (keep these)
"""
import re
import os
import glob

TEMPLATES_DIR = "/workspace/app_planners/jm/templates"
SKIP_FILES = {"login.html", "setup_pin.html", "select_profile.html"}


def add_style(tag_str, new_styles):
    """Add inline styles to a tag string, merging with existing style= if present."""
    if 'style="' in tag_str:
        # Merge into existing style
        return tag_str.replace('style="', f'style="{new_styles} ')
    else:
        # Add style before the closing >
        return tag_str.replace('>', f' style="{new_styles}">', 1)


def process_file(filepath):
    fname = os.path.basename(filepath)
    if fname in SKIP_FILES:
        return 0

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    original = content

    # =========================================================================
    # FIX 1: bg-white → var(--color-surface)
    # =========================================================================
    # Pattern: class="...bg-white..." without existing style with background
    # Replace bg-white class with inline style

    def fix_bg_white(m):
        tag = m.group(0)
        # Remove bg-white from class
        tag = tag.replace('bg-white ', '').replace(' bg-white', '').replace('bg-white', '')
        # Add background style
        if 'style="' in tag:
            tag = tag.replace('style="', 'style="background: var(--color-surface); ')
        else:
            # Find the closing of class attribute and add style after it
            tag = re.sub(r'(class="[^"]*")', r'\1 style="background: var(--color-surface);"', tag)
        return tag

    # Match opening tags that contain bg-white in class
    # But NOT tags that already have style with background
    # Be careful: only match tags where bg-white is in the class="" attribute
    content = re.sub(
        r'<(?:div|a|button|select|input|span|label|td|th|p)[^>]*class="[^"]*bg-white[^"]*"[^>]*>',
        fix_bg_white,
        content
    )

    # =========================================================================
    # FIX 2: Form/filter buttons with "border" class that need surface bg
    # These are tab-like buttons: "px-3 py-1.5 ... border ..."
    # They should have var(--color-surface) background
    # Already handled by Fix 1 for ones with bg-white
    # =========================================================================

    # =========================================================================
    # FIX 3: Modal/popup containers that had bg-white
    # e.g., "bg-white rounded-2xl shadow-2xl" for modals
    # Already handled by Fix 1
    # =========================================================================

    # =========================================================================
    # FIX 4: Muted helper text restoration
    # Elements with text-xs that are NOT bold/semibold/interactive
    # and don't have an explicit color → should be --color-text-muted
    # =========================================================================

    # Label elements: <label class="text-xs mb-1 block">
    content = re.sub(
        r'(<label\s+class="text-xs[^"]*")(>)',
        lambda m: m.group(1) + ' style="color: var(--color-text-muted);"' + m.group(2)
        if 'style=' not in m.group(0) and 'font-' not in m.group(0) and 'text-amber' not in m.group(0) and 'text-white' not in m.group(0)
        else m.group(0),
        content
    )

    # Helper/description text: <p class="text-xs ..."> without font-weight or color
    content = re.sub(
        r'(<p\s+class="text-xs[^"]*")(>)',
        lambda m: m.group(1) + ' style="color: var(--color-text-muted);"' + m.group(2)
        if 'style=' not in m.group(0) and 'font-' not in m.group(0) and 'text-amber' not in m.group(0) and 'text-white' not in m.group(0) and 'text-red' not in m.group(0) and 'text-emerald' not in m.group(0) and 'text-green' not in m.group(0)
        else m.group(0),
        content
    )

    # Span helper text: <span class="text-xs"> or <span class="text-xs ...">
    # Skip ones that have font-bold, font-semibold, or explicit colors
    content = re.sub(
        r'(<span\s+class="[^"]*text-xs[^"]*")(>)',
        lambda m: m.group(1) + ' style="color: var(--color-text-muted);"' + m.group(2)
        if 'style=' not in m.group(0)
        and 'font-bold' not in m.group(0)
        and 'font-semibold' not in m.group(0)
        and 'font-extrabold' not in m.group(0)
        and 'font-medium' not in m.group(0)
        and 'text-amber' not in m.group(0)
        and 'text-white' not in m.group(0)
        and 'text-red' not in m.group(0)
        and 'text-emerald' not in m.group(0)
        and 'text-green' not in m.group(0)
        and 'text-blue' not in m.group(0)
        and 'text-orange' not in m.group(0)
        and 'bg-amber' not in m.group(0)
        and 'bg-emerald' not in m.group(0)
        and 'hidden' not in m.group(0)
        else m.group(0),
        content
    )

    # Div helper text containers: <div class="text-xs ..."> or <div class="... text-xs ...">
    content = re.sub(
        r'(<div\s+class="[^"]*text-xs[^"]*")(>)',
        lambda m: m.group(1) + ' style="color: var(--color-text-muted);"' + m.group(2)
        if 'style=' not in m.group(0)
        and 'font-bold' not in m.group(0)
        and 'font-semibold' not in m.group(0)
        and 'text-amber' not in m.group(0)
        and 'text-white' not in m.group(0)
        and 'hidden' not in m.group(0)
        else m.group(0),
        content
    )

    # =========================================================================
    # FIX 5: Separator pipes "|" - these should be faint
    # Pattern: <span class="text-xs">|</span>
    # =========================================================================
    content = content.replace(
        'class="text-xs">|</span>',
        'class="text-xs" style="color: var(--color-text-faint);">|</span>'
    )
    # Already-fixed ones: avoid double style
    content = content.replace(
        'style="color: var(--color-text-muted);">|</span>',
        'style="color: var(--color-text-faint);">|</span>'
    )

    # =========================================================================
    # FIX 6: stat-label class should be muted if not already styled
    # =========================================================================
    content = re.sub(
        r'(<p\s+class="stat-label[^"]*")(>)',
        lambda m: m.group(1) + ' style="color: var(--color-text-muted);"' + m.group(2)
        if 'style=' not in m.group(0)
        else m.group(0),
        content
    )

    # =========================================================================
    # FIX 7: Date/time metadata spans that should be muted
    # Pattern: <span class="text-xs truncate">
    # =========================================================================
    # Already handled by Fix 4 (span text-xs)

    # =========================================================================
    # FIX 8: Buttons/links with "border" that need border-color token
    # Pattern: class="...border..." without style with border-color
    # =========================================================================
    # This is handled by base.html mobile overrides for most cases
    # But standalone "border" class on buttons/links may need it
    # Actually Tailwind's "border" class uses border-color: currentColor or
    # the default border color. With dark mode, we need explicit border token.
    # However, doing this globally is risky. Let's focus on specific patterns.

    # =========================================================================
    # FIX 9: Clean up double-style artifacts
    # If we added style="" to something that already had style="" via Fix 1
    # =========================================================================
    # Remove duplicate "background: var(--color-surface);" if it appears twice
    content = content.replace(
        'background: var(--color-surface); background: var(--color-surface);',
        'background: var(--color-surface);'
    )

    # Clean up empty class attributes
    content = re.sub(r'class="\s*"', '', content)
    # Clean up multiple spaces
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
