#!/usr/bin/env python3
"""Fix conditional tab buttons where bg-white was replaced incorrectly.

The pattern is: {% if condition %}bg-amber-600 text-white{% else %}bg-white border{% endif %}
After fix scripts, it became: {% if condition %}bg-amber-600 text-white{% else %}border{% endif %}" style="background: var(--color-surface);"

Problem: The inline style overrides bg-amber-600 when active.
Solution: Remove the inline background and put it in the else branch only.
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

    # Pattern 1: class="...{% if X %}bg-amber-600 text-white{% else %}border {% endif %}" style="background: var(--color-surface);"
    # Fix: Remove style="background:..." and add inline style only in else branch
    # Target: ...{% else %}border {% endif %}" style="background: var(--color-surface);">
    # Replace with: ...{% else %}border" style="background: var(--color-surface);{% endif %}">

    # More specifically, we need to restructure so the style is conditional
    # But Jinja inside style="" is messy. Better approach: use Jinja to conditionally output style.

    # Pattern A: ...{% else %}border {% endif %}" style="background: var(--color-surface);">
    content = content.replace(
        '{% else %}border {% endif %}" style="background: var(--color-surface);">',
        '{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )

    # Pattern A2: with shadow-sm
    content = content.replace(
        'shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);">',
        'shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )

    # Pattern B: ...{% else %}border {% endif %}" style="background: var(--color-surface); color: var(--color-text-muted);">
    # (This variant was produced by the first hint fix)
    content = content.replace(
        '{% else %}border {% endif %}" style="background: var(--color-surface); color: var(--color-text-muted);">',
        '{% else %}border" style="background: var(--color-surface); color: var(--color-text-muted);{% endif %}">'
    )

    # Pattern C: memos.html variant with text-white shadow-sm{% else %}border {% endif %}
    content = content.replace(
        'text-white shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);">',
        'text-white shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )

    # Pattern D: kanban.html - same as A2
    # Pattern E: todos.html - energy filter variants
    # These use different colors like bg-green-600, bg-blue-600, bg-red-600
    for color in ['green', 'blue', 'red']:
        content = content.replace(
            f'bg-{color}-600 text-white shadow-sm{{% else %}}border {{% endif %}}" style="background: var(--color-surface);">',
            f'bg-{color}-600 text-white shadow-sm{{% else %}}border" style="background: var(--color-surface);{{% endif %}}">'
        )

    # Pattern F: Plans.html already had proper conditional in Fix 1's output
    # {% else %}border" style="background: var(--color-surface); color: var(--color-text-muted); border-color: var(--color-border);{% endif %}">
    # This is fine.

    # Pattern G: category tabs with dynamic bg- class
    # {% if current_category_id == cat.id %}text-white shadow-sm{% else %}border {% endif %}"
    # These don't have bg-white directly but had "style="background: var(--color-surface);" added
    # The bg color is set via style="background:{{ cat.color }}" which should be separate
    content = content.replace(
        'text-white shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);"',
        'text-white shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}"'
    )

    # Also handle: {% if not X %}bg-amber-600... patterns (inverted condition)
    content = content.replace(
        '{% if not current_category_id %}bg-amber-600 text-white shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);">',
        '{% if not current_category_id %}bg-amber-600 text-white shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )
    content = content.replace(
        '{% if not current_energy %} text-white shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);">',
        '{% if not current_energy %} text-white shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )

    # Handle current_category_id is none
    content = content.replace(
        '{% if current_category_id is none %}bg-amber-600 text-white shadow-sm{% else %}border {% endif %}" style="background: var(--color-surface);">',
        '{% if current_category_id is none %}bg-amber-600 text-white shadow-sm{% else %}border" style="background: var(--color-surface);{% endif %}">'
    )

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
