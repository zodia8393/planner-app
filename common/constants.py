"""Shared constants across planner apps."""

PRIORITY_MAP = {
    0: {"label": "긴급", "color": "red", "bg": "bg-red-100 dark:bg-red-900/30", "text": "text-red-700 dark:text-red-400", "border": "border-red-400", "dot": "bg-red-500"},
    1: {"label": "높음", "color": "orange", "bg": "bg-orange-100 dark:bg-orange-900/30", "text": "text-orange-700 dark:text-orange-400", "border": "border-orange-400", "dot": "bg-orange-500"},
    2: {"label": "보통", "color": "blue", "bg": "bg-blue-100 dark:bg-blue-900/30", "text": "text-blue-700 dark:text-blue-400", "border": "border-blue-400", "dot": "bg-blue-500"},
    3: {"label": "낮음", "color": "gray", "bg": "bg-slate-100 dark:bg-slate-800/30", "text": "text-slate-600 dark:text-slate-400", "border": "border-slate-400", "dot": "bg-slate-400"},
}

REPEAT_MAP = {
    "none": "반복 없음",
    "daily": "매일",
    "weekdays": "주중 매일",
    "weekly": "매주",
    "monthly": "매월",
    "yearly": "매년",
}

WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

ROLE_COLORS = {
    "부장": {"from": "from-slate-500", "to": "to-slate-700", "border": "border-slate-300", "hover": "hover:border-slate-500", "bg": "from-slate-50 to-slate-100", "text": "text-slate-700", "shadow": "shadow-slate-300/30"},
    "차장": {"from": "from-amber-400", "to": "to-amber-600", "border": "border-amber-200", "hover": "hover:border-amber-400", "bg": "from-amber-50 to-orange-50", "text": "text-amber-700", "shadow": "shadow-amber-300/30"},
    "대리": {"from": "from-blue-400", "to": "to-blue-600", "border": "border-blue-200", "hover": "hover:border-blue-400", "bg": "from-blue-50 to-indigo-50", "text": "text-blue-700", "shadow": "shadow-blue-300/30"},
    "주임": {"from": "from-emerald-400", "to": "to-emerald-600", "border": "border-emerald-200", "hover": "hover:border-emerald-400", "bg": "from-emerald-50 to-teal-50", "text": "text-emerald-700", "shadow": "shadow-emerald-300/30"},
}
