"""Navy design tokens (navy-astro.pages.dev): Switzer, ink on cool white, square corners, no shadows."""
from __future__ import annotations

import inspect

import gradio as gr

INK, MUTED, BG, SURFACE, ACCENT, LINE = "#111428", "#585D6F", "#FAFBFF", "#EAEEFC", "#DBDFFF", "#DDE1F0"

HEAD = """
<link rel="preconnect" href="https://api.fontshare.com">
<link href="https://api.fontshare.com/v2/css?f[]=switzer@400,500,600,700&display=swap" rel="stylesheet">
<meta name="description" content="An agent that notices reality changed and safely changes its mind. Built for the DOO Adaptive Agent challenge.">
"""

# Force the light Navy look even when the OS is in dark mode.
JS = "() => { document.body.classList.remove('dark'); document.documentElement.classList.remove('dark'); }"


def navy_theme() -> gr.themes.Base:
    t = gr.themes.Base(
        font=[gr.themes.Font("Switzer"), "ui-sans-serif", "system-ui", "sans-serif"],
        font_mono=[gr.themes.Font("JetBrains Mono"), "ui-monospace", "monospace"],
        radius_size=gr.themes.sizes.radius_none,
    )
    values = dict(
        body_background_fill=BG, body_text_color=INK, body_text_color_subdued=MUTED,
        background_fill_primary="#FFFFFF", background_fill_secondary=BG,
        block_background_fill="#FFFFFF", block_border_color=LINE, block_border_width="1px", block_shadow="none",
        block_label_background_fill=BG, block_label_text_color=MUTED, block_title_text_color=INK,
        border_color_primary=LINE, border_color_accent=INK,
        input_background_fill="#FFFFFF", input_border_color=LINE, input_shadow="none",
        button_primary_background_fill=ACCENT, button_primary_background_fill_hover="#C9CFFF",
        button_primary_text_color=INK, button_primary_border_color=INK,
        button_secondary_background_fill="#FFFFFF", button_secondary_background_fill_hover=SURFACE,
        button_secondary_text_color=INK, button_secondary_border_color=LINE,
        button_shadow="none", button_shadow_hover="none", button_shadow_active="none",
        color_accent=INK, color_accent_soft=SURFACE, link_text_color=INK,
        checkbox_label_background_fill_selected=ACCENT, checkbox_label_border_color_selected=INK,
        checkbox_background_color_selected=INK,
    )
    # identical values for the dark variants: the page stays on-brand regardless of OS theme
    values.update({f"{k}_dark": v for k, v in values.items()})
    allowed = set(inspect.signature(t.set).parameters)  # tolerate theme-variable renames across Gradio versions
    return t.set(**{k: v for k, v in values.items() if k in allowed})


CSS = f"""
:root {{ --ink:{INK}; --muted:{MUTED}; --bg:{BG}; --surface:{SURFACE}; --accent:{ACCENT}; --line:{LINE};
        --ok:#1F7A4D; --bad:#B42318; --warn:#9A6700; }}
body, .gradio-container {{ background:var(--bg) !important; color:var(--ink); }}
.gradio-container {{ max-width:1280px !important; margin:0 auto; padding:0 16px !important; }}
footer {{ opacity:.6; }}
.eyebrow {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:500; margin-bottom:8px; }}
.hero {{ padding:48px 0 24px; border-bottom:1px solid var(--line); margin-bottom:8px; }}
.hero h1 {{ font-size:clamp(32px,5vw,48px); line-height:1.05; font-weight:600; letter-spacing:-.02em; margin:0 0 16px; color:var(--ink); }}
.hero h1 em, h2 em {{ font-style:italic; font-weight:500; }}
.hero p {{ font-size:17px; color:var(--muted); max-width:720px; margin:0; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--line); margin-top:24px; background:#fff; }}
.kpis div {{ padding:16px; border-right:1px solid var(--line); }} .kpis div:last-child {{ border-right:0; }}
.kpis b {{ display:block; font-size:28px; font-weight:600; }} .kpis span {{ color:var(--muted); font-size:13px; }}
@media (max-width:720px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }} .kpis div:nth-child(2) {{ border-right:0; }} }}
.story {{ background:#fff; border:1px solid var(--line); padding:16px 20px; font-size:15px; line-height:1.55; }}
.panel {{ background:#fff; border:1px solid var(--line); padding:20px; min-height:420px; }}
.panel h3 {{ margin:0 0 4px; font-size:22px; font-weight:600; }}
.panel .sub {{ color:var(--muted); font-size:13px; margin-bottom:12px; }}
.badges {{ display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 14px; }}
.badge {{ border:1px solid var(--line); padding:2px 8px; font-size:12px; background:var(--bg); white-space:nowrap; }}
.badge.live {{ background:var(--accent); border-color:var(--ink); }}
.badge.bad {{ color:var(--bad); border-color:var(--bad); }} .badge.ok {{ color:var(--ok); border-color:var(--ok); }}
ol.steps {{ list-style:none; margin:0; padding:0; border-top:1px solid var(--line); }}
ol.steps li {{ display:grid; grid-template-columns:28px 1fr auto; gap:8px; padding:9px 0; border-bottom:1px solid var(--line); font-size:14px; align-items:start; }}
ol.steps li .ico {{ font-weight:700; text-align:center; }}
ol.steps li code {{ font-size:13px; background:var(--surface); padding:1px 6px; }}
ol.steps li .desc {{ color:var(--muted); font-size:13px; display:block; margin-top:2px; }}
li.st-done .ico {{ color:var(--ok); }} li.st-running, li.st-waiting {{ background:var(--accent); }}
li.st-skipped {{ opacity:.45; text-decoration:line-through; }} li.st-blocked .ico, li.st-failed .ico {{ color:var(--bad); }}
.tag {{ font-size:11px; border:1px solid var(--ink); padding:0 5px; text-transform:uppercase; letter-spacing:.05em; }}
.tag.irr {{ border-color:var(--bad); color:var(--bad); }}
.outcome {{ margin-top:16px; padding:14px 16px; border:1px solid var(--line); border-left:4px solid var(--muted); background:var(--bg); }}
.outcome.v-success {{ border-left-color:var(--ok); }} .outcome.v-silent_failure, .outcome.v-failure {{ border-left-color:var(--bad); }}
.outcome.v-escalated, .outcome.v-degraded {{ border-left-color:var(--warn); }}
.outcome strong {{ display:block; font-size:16px; margin-bottom:6px; }}
.outcome .verdict {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; font-weight:600; }}
.v-success .verdict {{ color:var(--ok); }} .v-silent_failure .verdict, .v-failure .verdict {{ color:var(--bad); }} .v-escalated .verdict, .v-degraded .verdict {{ color:var(--warn); }}
.metrics {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-top:8px; }}
.chat {{ margin-top:14px; display:flex; flex-direction:column; gap:6px; }}
.bubble {{ background:#E7F7EE; border:1px solid #CBEBD8; padding:8px 10px; font-size:13px; max-width:92%; }}
.bubble.q {{ background:var(--surface); border-color:var(--line); }}
.bubble .ar, .rtl {{ direction:rtl; text-align:right; font-family:'Noto Naskh Arabic','Segoe UI',Tahoma,sans-serif; color:var(--muted); margin-top:4px; }}
.timeline {{ list-style:none; margin:0; padding:0; border-top:1px solid var(--line); }}
.timeline li {{ display:grid; grid-template-columns:64px 1fr; gap:12px; padding:14px 0; border-bottom:1px solid var(--line); }}
.timeline .t {{ font-variant-numeric:tabular-nums; color:var(--muted); font-size:13px; }}
.timeline .d {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }}
.timeline .d.replan, .timeline .d.precommit-replan {{ color:var(--ink); }} .timeline .d.ignore {{ color:var(--ok); }}
.timeline .d.escalate, .timeline .d.hold {{ color:var(--warn); }}
.timeline .reason {{ font-size:15px; margin:4px 0; }}
.timeline .meta {{ font-size:12px; color:var(--muted); }}
.timeline code {{ font-size:12px; background:var(--surface); padding:1px 5px; }}
table.ev {{ width:100%; border-collapse:collapse; font-size:13px; background:#fff; }}
table.ev th {{ text-align:left; font-weight:500; color:var(--muted); border-bottom:1px solid var(--ink); padding:8px; }}
table.ev td {{ border-bottom:1px solid var(--line); padding:8px; vertical-align:top; }}
table.ev td code {{ font-size:12px; }}
.h {{ font-size:12px; padding:1px 6px; border:1px solid var(--line); white-space:nowrap; }}
.h.contradiction {{ background:var(--accent); border-color:var(--ink); }} .h.unconfirmed {{ color:var(--ok); border-color:var(--ok); }}
.h.not.observed, .h.not {{ color:var(--muted); }}
.loop {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--line); background:#fff; }}
.loop div {{ padding:16px; border-right:1px solid var(--line); }} .loop div:last-child {{ border-right:0; }}
.loop h4 {{ margin:0 0 6px; font-size:17px; }} .loop p {{ margin:0; color:var(--muted); font-size:14px; }}
@media (max-width:720px) {{ .loop {{ grid-template-columns:1fr; }} .loop div {{ border-right:0; border-bottom:1px solid var(--line); }} }}
.empty {{ color:var(--muted); font-size:14px; padding:12px 0; }}
"""
