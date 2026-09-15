"""Write the sketch-pass wireframes (compositions/frames/NN-*.html) and mark storyboard frames built.

Run from the project root: python tools/build_sketches.py
Sketches carry the real words, plain blocks, the frame.md canvas + ink, and one Blue Slate accent
on the focal. Palette: Obsidian Chrome light theme (Onyx #0A0A0A, Blue Slate #536878,
Alabaster Grey #E5E4E2) with a soft chrome gradient.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TPL = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>__TITLE__ (sketch)</title>
  </head>
  <body>
    <template>
      <style>
        #root {
          position: absolute; inset: 0; overflow: hidden; color: #0A0A0A; font-family: system-ui, sans-serif;
          background:
            radial-gradient(42% 48% at 96% -6%, rgba(10, 10, 10, 0.38) 0%, rgba(10, 10, 10, 0) 70%),
            radial-gradient(62% 62% at 80% 0%, rgba(83, 104, 120, 0.48) 0%, rgba(83, 104, 120, 0) 72%),
            radial-gradient(55% 60% at 0% 100%, rgba(255, 255, 255, 0.75) 0%, rgba(255, 255, 255, 0) 70%),
            #E5E4E2;
        }
        #root .pad { position: absolute; inset: 0; padding: 90px 120px; box-sizing: border-box; display: flex; flex-direction: column; gap: 36px; }
        #root .label { font-size: 24px; letter-spacing: 0.12em; text-transform: uppercase; color: rgba(10, 10, 10, 0.62); }
        #root .h1 { font-size: 88px; font-weight: 800; line-height: 1.05; letter-spacing: -0.02em; }
        #root .h2 { font-size: 56px; font-weight: 700; line-height: 1.1; }
        #root .body { font-size: 34px; line-height: 1.3; color: rgba(10, 10, 10, 0.84); }
        #root .src { font-size: 22px; line-height: 1.3; color: rgba(10, 10, 10, 0.6); }
        #root .box { border: 3px solid rgba(10, 10, 10, 0.14); background: rgba(255, 255, 255, 0.45); border-radius: 24px; padding: 32px; box-sizing: border-box; }
        #root .ph { border: 3px dashed rgba(10, 10, 10, 0.3); border-radius: 24px; display: flex; align-items: center; justify-content: center; font-size: 24px; color: rgba(10, 10, 10, 0.6); text-align: center; padding: 12px; box-sizing: border-box; }
        #root .accent { color: #536878; }
        #root .focal { border-color: #536878; }
        #root .row { display: flex; gap: 32px; }
        #root .col { display: flex; flex-direction: column; }
        #root .mono { font-family: ui-monospace, monospace; }
__CSS__
      </style>
      <div id="root" data-composition-id="__ID__" data-width="1920" data-height="1080">
__BODY__
      </div>
      <script>
        const tl = gsap.timeline({ paused: true });
        window.__timelines["__ID__"] = tl;
      </script>
    </template>
  </body>
</html>
"""

FRAMES = []

FRAMES.append(("01-hook", "Hook: 3 P.M.", "", """
        <div class="pad" style="flex-direction: row; align-items: center; gap: 80px;">
          <div class="col" style="flex: 1.1; gap: 24px;">
            <div class="label">Weekday · at work</div>
            <div class="mono accent" style="font-size: 180px; font-weight: 800; line-height: 1;">3:00 PM</div>
          </div>
          <div class="col" style="flex: 1; gap: 48px;">
            <div class="row" style="align-items: center;"><div class="ph" style="width: 150px; height: 150px; flex: none;">outlet glyph</div><div class="h2">Is the TV still on?</div></div>
            <div class="row" style="align-items: center;"><div class="ph" style="width: 150px; height: 150px; flex: none;">map pin</div><div class="h2">Where is your child?</div></div>
          </div>
        </div>"""))

FRAMES.append(("02-title", "Title, objectives and outline", "", """
        <div class="pad" style="justify-content: center; gap: 44px;">
          <div class="row" style="align-items: center; gap: 48px;">
            <div class="ph" style="width: 200px; height: 200px; flex: none;">MAYA logo</div>
            <div class="col" style="gap: 12px;">
              <div class="accent" style="font-size: 132px; font-weight: 800; line-height: 1; letter-spacing: -0.02em;">MAYA</div>
              <div class="body" style="font-size: 40px; max-width: 1300px;">A Family-Centred AIoT Ecosystem for Smarter and Safer Home Management</div>
            </div>
          </div>
          <div class="label">Project ID · CBN8426079</div>
          <div class="row" style="gap: 24px;">
            <div class="box" style="flex: 1;"><div class="label">Objective 01</div><div class="body">Independent outlet control</div></div>
            <div class="box" style="flex: 1;"><div class="label">Objective 02</div><div class="body">AI voice &amp; chat assistant</div></div>
            <div class="box" style="flex: 1;"><div class="label">Objective 03</div><div class="body">Child location &amp; screen-time tracking</div></div>
            <div class="box" style="flex: 1;"><div class="label">Objective 04</div><div class="body">Secure Open API</div></div>
          </div>
          <div class="src" style="letter-spacing: 0.12em;">PROBLEM · SOLUTION · IMPACT · PROOF</div>
        </div>"""))

FRAMES.append(("03-problem", "The problem: parents are stretched", "", """
        <div class="pad" style="gap: 40px;">
          <div class="label">The problem · parents are stretched</div>
          <div class="row" style="flex: 1; gap: 48px;">
            <div class="box focal col" style="flex: 1; justify-content: center; gap: 16px;">
              <div class="accent" style="font-size: 170px; font-weight: 800; line-height: 1;">56.6%</div>
              <div class="body">Record female labour-force participation in Malaysia</div>
              <div class="src">Source: DOSM, Q4 2025</div>
            </div>
            <div class="box col" style="flex: 1; justify-content: center; gap: 16px;">
              <div style="font-size: 170px; font-weight: 800; line-height: 1;">80%</div>
              <div class="body">of children spend 2+ hours a day unsupervised</div>
              <div class="src">MAYA survey · n=73 working parents · Klang Valley</div>
            </div>
          </div>
          <div class="ph" style="height: 90px;">Day timeline 8 AM → 6 PM · the unsupervised window fills</div>
        </div>"""))

FRAMES.append(("04-pain", "The problem: app fatigue and wasted power", "", """
        <div class="pad">
          <div class="label">The problem · app fatigue &amp; wasted power</div>
          <div class="row" style="flex: 1; gap: 48px;">
            <div class="box" style="flex: 1.2; display: flex; gap: 32px; align-items: center;">
              <div class="ph" style="width: 260px; height: 460px; flex: none;">Phone buried in app tiles: plug · map · chat · camera · timer</div>
              <div class="col" style="gap: 16px;">
                <div class="accent" style="font-size: 150px; font-weight: 800; line-height: 1;">70%</div>
                <div class="body">of parents feel app fatigue often or very often</div>
                <div class="src">MAYA survey · n=73</div>
              </div>
            </div>
            <div class="box col" style="flex: 1; justify-content: center; gap: 16px;">
              <div class="ph" style="height: 120px;">Standby power meter</div>
              <div style="font-size: 130px; font-weight: 800; line-height: 1;">≈10%</div>
              <div class="body">of home electricity used by devices left on standby</div>
              <div class="src">Lawrence Berkeley National Laboratory, cited by US DOE</div>
            </div>
          </div>
        </div>"""))

FRAMES.append(("05-shortcomings", "Current shortcomings", """
        #root .tbl { display: flex; flex-direction: column; border: 3px solid rgba(10, 10, 10, 0.14); background: rgba(255, 255, 255, 0.45); border-radius: 24px; overflow: hidden; }
        #root .tr { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; }
        #root .tr > div { padding: 18px 28px; font-size: 30px; border-top: 2px solid rgba(10, 10, 10, 0.1); }
        #root .th > div { font-size: 22px; text-transform: uppercase; letter-spacing: 0.1em; color: rgba(10, 10, 10, 0.62); border-top: none; }
        #root .ghost > div { color: #536878; border-top: 3px dashed #536878; }""", """
        <div class="pad" style="gap: 32px;">
          <div class="label">Current shortcomings</div>
          <div class="h1" style="font-size: 72px;">Why current options fall short</div>
          <div class="tbl">
            <div class="tr th"><div>Solution</div><div>Per-outlet control</div><div>Understands you</div><div>Parental tools</div></div>
            <div class="tr"><div>Smart plugs &amp; extensions <span class="src">e.g. SHAS</span></div><div>Partial</div><div>✗</div><div>✗</div></div>
            <div class="tr"><div>Voice assistants <span class="src">e.g. Alexa</span></div><div>✗</div><div>Voice commands</div><div>✗</div></div>
            <div class="tr"><div>LLM home agents <span class="src">e.g. IoTGPT</span></div><div>Via 3rd-party devices</div><div>✓</div><div>✗</div></div>
            <div class="tr"><div>Parental control apps</div><div>✗</div><div>✗</div><div>✓</div></div>
            <div class="tr ghost"><div>MAYA (revealed in frame 6)</div><div>?</div><div>?</div><div>?</div></div>
          </div>
          <div class="src">Case-study comparison · MAYA FYP report</div>
        </div>"""))

FRAMES.append(("06-concept", "The potential solution: one family hub", "", """
        <div class="pad" style="gap: 24px;">
          <div class="label">The potential solution · one family hub</div>
          <div style="position: relative; flex: 1;">
            <div class="box col" style="position: absolute; left: 590px; top: 0; width: 500px; height: 160px; justify-content: center;"><div class="h2" style="font-size: 44px;">Home</div><div class="src">Smart extension · device state</div></div>
            <div class="ph" style="position: absolute; left: 700px; top: 185px; width: 280px; height: 90px;">device state ↓</div>
            <div class="box focal col" style="position: absolute; left: 640px; top: 300px; width: 400px; height: 220px; align-items: center; justify-content: center; gap: 8px;"><div class="accent" style="font-size: 84px; font-weight: 800; line-height: 1;">MAYA</div><div class="src">family-centred hub</div></div>
            <div class="ph" style="position: absolute; left: 330px; top: 440px; width: 280px; height: 90px;">commands · alerts</div>
            <div class="ph" style="position: absolute; left: 1070px; top: 440px; width: 280px; height: 90px;">screen time · location</div>
            <div class="box col" style="position: absolute; left: 0; top: 560px; width: 520px; height: 170px; justify-content: center;"><div class="h2" style="font-size: 44px;">Parent</div><div class="src">Parent app · @maya assistant</div></div>
            <div class="box col" style="position: absolute; left: 1160px; top: 560px; width: 520px; height: 170px; justify-content: center;"><div class="h2" style="font-size: 44px;">Child</div><div class="src">Companion app · permissions</div></div>
            <div class="ph" style="position: absolute; left: 340px; top: 760px; width: 1000px; height: 80px; font-size: 28px;">MAYA row lands: per-outlet ✓ · understands you ✓ · parental tools ✓</div>
          </div>
        </div>"""))

FRAMES.append(("07-hardware", "Your product: the smart extension", """
        #root .st .body { font-size: 30px; }""", """
        <div class="pad" style="gap: 40px;">
          <div class="label">Your product · how it works</div>
          <div class="h1" style="font-size: 72px;">ESP32 smart extension · 3 independent outlets</div>
          <div class="row st" style="flex: 1; gap: 28px; align-items: stretch;">
            <div class="box focal col" style="flex: 1.3; gap: 18px;"><div class="label accent">01 · Smart extension</div><div class="ph" style="flex: 1;">3-channel socket (hardware block diagram)</div><div class="body">CH1 TV · CH2 Decoder · CH3 Wi-Fi router</div></div>
            <div class="box col" style="flex: 1; gap: 18px;"><div class="label">02 · Bluetooth setup</div><div class="ph" style="flex: 1;">phone ⇄ socket</div><div class="body">One-time Wi-Fi provisioning</div></div>
            <div class="box col" style="flex: 1; gap: 18px;"><div class="label">03 · Cloud server</div><div class="ph" style="flex: 1;">server</div><div class="body">FastAPI on Fly.io · real-time sync</div></div>
            <div class="box col" style="flex: 1; gap: 18px;"><div class="label">04 · Family apps</div><div class="ph" style="flex: 1;">parent + child phones</div><div class="body">Every phone updates instantly</div></div>
          </div>
          <div class="src">Camera pans station to station →</div>
        </div>"""))

FRAMES.append(("08-ai-child", "Your product: @maya AI and child app", "", """
        <div class="pad" style="gap: 32px;">
          <div class="label">Your product · @maya AI + child app</div>
          <div class="row" style="flex: 1; gap: 48px;">
            <div class="box focal row" style="flex: 1.25; gap: 28px; align-items: stretch;">
              <div class="ph" style="width: 330px; flex: none;">Real app screen · ui-dashboard.png (Home: Smart Socket D82C34C, Ps5 · Tv · Channel 3, Ask Maya…)</div>
              <div class="col" style="flex: 1; gap: 20px; justify-content: center;">
                <div class="label accent">Ask Maya · Parent app</div>
                <div class="box" style="align-self: flex-end; font-size: 34px;">@maya turn off the TV</div>
                <div class="ph" style="height: 80px;">tool call · control_device → Tv · OFF</div>
                <div class="box" style="align-self: flex-start; font-size: 34px;">Done — I turned off the TV.</div>
              </div>
            </div>
            <div class="box col" style="flex: 1; gap: 22px;">
              <div class="label">Child app · Ali</div>
              <div class="row" style="align-items: center; gap: 28px;"><div class="ph" style="width: 200px; height: 200px; border-radius: 50%; flex: none;">screen-time ring</div><div class="col"><div style="font-size: 64px; font-weight: 800;">1h 42m</div><div class="body">of a 2h daily limit</div></div></div>
              <div class="box"><div class="label">Last location</div><div class="body">Home · 3:02 PM</div></div>
              <div class="box"><div class="label">Outlet permissions</div><div class="body">Tv off · Ps5 off · Channel 3 allowed</div></div>
            </div>
          </div>
        </div>"""))

FRAMES.append(("09-benefits", "User benefits", """
        #root .grid5 { display: grid; grid-template-columns: 1.3fr 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 28px; flex: 1; }
        #root .grid5 .box { display: flex; flex-direction: column; justify-content: flex-end; gap: 12px; }
        #root .grid5 .lead { grid-row: span 2; }""", """
        <div class="pad" style="gap: 40px;">
          <div class="label">User benefits</div>
          <div class="h1" style="font-size: 80px;">What families gain</div>
          <div class="grid5">
            <div class="box focal lead"><div class="label accent">01</div><div class="h2" style="font-size: 64px;">One app instead of many</div><div class="body">Power, chat, screen time and location together</div></div>
            <div class="box"><div class="label">02</div><div class="h2" style="font-size: 44px;">Hands-free control</div><div class="src">Just ask @maya</div></div>
            <div class="box"><div class="label">03</div><div class="h2" style="font-size: 44px;">Peace of mind at work</div><div class="src">Screen time &amp; location at a glance</div></div>
            <div class="box"><div class="label">04</div><div class="h2" style="font-size: 44px;">Less wasted power</div><div class="src">Switch off standby loads</div></div>
            <div class="box"><div class="label">05</div><div class="h2" style="font-size: 44px;">No rewiring</div><div class="src">Plug-and-play extension</div></div>
          </div>
        </div>"""))

FRAMES.append(("10-sdg-esg", "Impact: SDGs and ESG, equal weight", """
        #root .panel { flex: 1; display: flex; flex-direction: column; gap: 20px; }
        #root .tile { display: flex; gap: 24px; align-items: center; border: 3px solid rgba(10, 10, 10, 0.14); background: rgba(255, 255, 255, 0.4); border-radius: 20px; padding: 18px 24px; height: 150px; box-sizing: border-box; }
        #root .num { width: 108px; height: 108px; flex: none; border-radius: 16px; background: rgba(10, 10, 10, 0.08); display: flex; align-items: center; justify-content: center; font-size: 54px; font-weight: 800; }
        #root .tname { font-size: 30px; font-weight: 700; line-height: 1.15; }
        #root .tsub { font-size: 24px; line-height: 1.25; color: rgba(10, 10, 10, 0.7); }""", """
        <div class="pad" style="gap: 32px;">
          <div class="label">Impact · SDGs and ESG, side by side</div>
          <div class="row" style="flex: 1; gap: 48px;">
            <div class="box panel">
              <div class="h2" style="font-size: 44px;">UN Sustainable Development Goals</div>
              <div class="tile focal"><div class="num accent">11</div><div class="col"><div class="tname">Sustainable Cities &amp; Communities · Primary</div><div class="tsub">Safer homes and communities</div></div></div>
              <div class="tile"><div class="num">3</div><div class="col"><div class="tname">Good Health &amp; Well-being</div><div class="tsub">Child safety, parent well-being</div></div></div>
              <div class="tile"><div class="num">7</div><div class="col"><div class="tname">Affordable &amp; Clean Energy</div><div class="tsub">Cuts standby power</div></div></div>
              <div class="tile"><div class="num">12</div><div class="col"><div class="tname">Responsible Consumption &amp; Production</div><div class="tsub">Responsible household energy use</div></div></div>
            </div>
            <div class="box panel">
              <div class="h2" style="font-size: 44px;">ESG Pillars</div>
              <div class="tile"><div class="num">E</div><div class="col"><div class="tname">Environmental</div><div class="tsub">Less standby waste, responsible energy use</div></div></div>
              <div class="tile"><div class="num">S</div><div class="col"><div class="tname">Social</div><div class="tsub">Safer children, supported working parents, affordable access</div></div></div>
              <div class="tile"><div class="num">G</div><div class="col"><div class="tname">Governance</div><div class="tsub">Apache 2.0 open source · secure auth · parent-set permissions</div></div></div>
            </div>
          </div>
        </div>"""))

FRAMES.append(("11-market", "Market value and opportunity", """
        #root .mcol { flex: 1; display: flex; flex-direction: column; gap: 14px; }
        #root .bars { flex: 1; display: flex; align-items: flex-end; gap: 24px; min-height: 200px; }
        #root .bar { flex: 1; border: 3px dashed rgba(10, 10, 10, 0.3); border-radius: 12px 12px 0 0; display: flex; align-items: flex-end; justify-content: center; padding-bottom: 8px; font-size: 22px; color: rgba(10, 10, 10, 0.6); box-sizing: border-box; }""", """
        <div class="pad" style="gap: 32px;">
          <div class="label">Market value &amp; opportunity</div>
          <div class="row" style="flex: 1; gap: 40px; align-items: stretch;">
            <div class="box focal mcol">
              <div class="label accent">Global smart homes</div>
              <div class="bars"><div class="bar" style="height: 47%;">2025</div><div class="bar" style="height: 100%;">2032</div></div>
              <div style="font-size: 64px; font-weight: 800;">US$450.2B</div>
              <div class="body">by 2032, from US$213.7B · CAGR 11.8%</div>
              <div class="src">MarketsandMarkets, 2026</div>
            </div>
            <div class="box mcol">
              <div class="label">Smart plugs</div>
              <div class="bars"><div class="bar" style="height: 12%;">2024</div><div class="bar" style="height: 100%;">2034</div></div>
              <div style="font-size: 64px; font-weight: 800;">US$30.5B</div>
              <div class="body">by 2034, from US$3.5B · CAGR 24.1%</div>
              <div class="src">Market.us, 2025</div>
            </div>
            <div class="box mcol">
              <div class="label">Parental control software</div>
              <div class="bars"><div class="bar" style="height: 38%;">2025</div><div class="bar" style="height: 100%;">2034</div></div>
              <div style="font-size: 64px; font-weight: 800;">US$4.12B</div>
              <div class="body">by 2034, from US$1.57B · CAGR 11.2%</div>
              <div class="src">Fortune Business Insights, 2026</div>
            </div>
          </div>
          <div class="src">Asia-Pacific is the fastest-growing smart-home region (~17% CAGR) · ASEAN smart homes US$5.29B (2025) → US$12.56B (2031), Mordor Intelligence 2026</div>
        </div>"""))

FRAMES.append(("12-evidence", "Evidence, social proof and active development", """
        #root .ring { width: 100px; height: 100px; border-radius: 50%; flex: none; }
        #root .iter { display: grid; grid-template-columns: repeat(4, 1fr) 1.6fr; gap: 14px; }
        #root .step { border: 3px solid rgba(10, 10, 10, 0.14); background: rgba(255, 255, 255, 0.4); border-radius: 16px; padding: 14px 16px; font-size: 22px; line-height: 1.25; box-sizing: border-box; }""", """
        <div class="pad" style="flex-direction: row; gap: 40px;">
          <div class="col" style="flex: 1; gap: 24px; min-width: 0;">
            <div class="label">Evidence, social proof &amp; active development</div>
            <div class="row" style="gap: 20px;">
              <div class="box row" style="flex: 1; align-items: center; gap: 18px;"><div class="ph ring">ring</div><div class="col"><div style="font-size: 56px; font-weight: 800; line-height: 1;">84%</div><div class="body" style="font-size: 26px;">find smart extensions useful</div></div></div>
              <div class="box row" style="flex: 1; align-items: center; gap: 18px;"><div class="ph ring">ring</div><div class="col"><div style="font-size: 56px; font-weight: 800; line-height: 1;">82%</div><div class="body" style="font-size: 26px;">would install a child monitoring app</div></div></div>
              <div class="box row" style="flex: 1; align-items: center; gap: 18px;"><div class="ph ring">ring</div><div class="col"><div style="font-size: 56px; font-weight: 800; line-height: 1;">62%</div><div class="body" style="font-size: 26px;">prefer AI automation over manual rules</div></div></div>
            </div>
            <div class="src">MAYA survey · n=73 working parents</div>
            <div class="row" style="gap: 20px;">
              <div class="box focal" style="flex: 1;"><div class="accent" style="font-size: 72px; font-weight: 800; line-height: 1;">40/40</div><div class="body" style="font-size: 28px;">tests passed · incl. UAT with a client user</div></div>
              <div class="box" style="flex: 1.2;"><div class="label">Real cost</div><div class="h2" style="font-size: 44px;">≈RM95 hardware</div><div class="body" style="font-size: 28px;">≈RM2/month hosting · live on Fly.io</div></div>
            </div>
            <div class="iter">
              <div class="step">1 · Hardware control ✓</div>
              <div class="step">2 · Profiles &amp; permissions ✓</div>
              <div class="step">3 · AI agent &amp; Open API ✓</div>
              <div class="step">3.5 · Voice &amp; screen-time automation ✓</div>
              <div class="step" style="border-style: dashed;">4 · Device Protocol v2: sensors &amp; hubs · in progress</div>
            </div>
          </div>
          <div class="col" style="width: 440px; flex: none; gap: 14px;">
            <div class="ph" style="flex: 1;">Real photo · user-photo-2026-09-15.jpeg (MAYA prototype on show at UNISEL)</div>
            <div class="src">MAYA prototype on show at the UNISEL showcase</div>
          </div>
        </div>"""))

FRAMES.append(("13-ip", "IP and research", "", """
        <div class="pad" style="flex-direction: row; align-items: center; gap: 48px;">
          <div class="box focal col" style="flex: 1.3; gap: 22px; padding: 56px;">
            <div class="label">Intellectual property</div>
            <div class="accent" style="font-size: 88px; font-weight: 800; line-height: 1.05;">Apache License 2.0</div>
            <div class="body">Open source · free to use, modify and distribute</div>
            <div class="mono" style="font-size: 30px;">github.com/zlen2024/Maya-Smarthome-AI</div>
          </div>
          <div class="box col" style="flex: 1; gap: 22px; padding: 56px;">
            <div class="label">Research</div>
            <div class="h2" style="font-size: 48px;">Universiti Selangor (UNISEL)</div>
            <div class="body">Final Year Project · Bachelor of Software Engineering</div>
            <div class="body">Survey of 73 working parents · 40 documented test cases</div>
          </div>
        </div>"""))

FRAMES.append(("14-close", "Conclusion: the X-factor", "", """
        <div class="pad" style="justify-content: center; align-items: center; gap: 44px; text-align: center;">
          <div class="body" style="font-size: 40px;">Other smart homes switch things on and off.</div>
          <div class="h1" style="font-size: 96px;">MAYA understands your family.</div>
          <div class="row" style="gap: 40px; justify-content: center;"><div class="h2">Affordable</div><div class="h2">·</div><div class="h2">Intelligent</div><div class="h2">·</div><div class="h2">Open</div></div>
          <div class="row" style="align-items: center; gap: 36px; justify-content: center;">
            <div class="ph" style="width: 150px; height: 150px; flex: none;">logo</div>
            <div class="col" style="text-align: left;"><div class="accent" style="font-size: 96px; font-weight: 800; line-height: 1;">MAYA</div><div class="body">home, handled.</div></div>
          </div>
          <div class="src">MAYA: A Family-Centred AIoT Ecosystem for Smarter and Safer Home Management · Project ID CBN8426079 · Thank you</div>
        </div>"""))

VOICES = {1: "Sulafat", 2: "Puck", 3: "Sulafat", 4: "Sulafat", 5: "Puck", 6: "Sulafat", 7: "Puck",
          8: "Puck", 9: "Sulafat", 10: "Puck (SDGs) + Sulafat (ESG)", 11: "Puck", 12: "Puck",
          13: "Sulafat", 14: "Sulafat + Puck, alternating"}

ASSETS = {8: "assets/media/ui-dashboard.png (real app Home screens, user-supplied)",
          12: "assets/media/user-photo-2026-09-15.jpeg (prototype at UNISEL showcase, user-supplied)"}

DESIGN_LINE = ("design: frame.md (Obsidian Chrome light theme — Alabaster Grey #E5E4E2 canvas, Onyx #0A0A0A ink, "
               "Blue Slate #536878 accent, soft chrome gradient; user feedback 2026-09-15)")


def write_sketches():
    out_dir = os.path.join(ROOT, "compositions", "frames")
    os.makedirs(out_dir, exist_ok=True)
    for slug, title, css, body in FRAMES:
        cid = "f" + slug
        html = (TPL.replace("__TITLE__", title).replace("__ID__", cid)
                .replace("__CSS__", css.strip("\n")).replace("__BODY__", body.strip("\n")))
        with io.open(os.path.join(out_dir, f"{slug}.html"), "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
    print("wrote", len(FRAMES), "sketches")


def mark_storyboard():
    path = os.path.join(ROOT, "STORYBOARD.md")
    text = io.open(path, encoding="utf-8").read()
    text = re.sub(r"(?m)^design: .*$", lambda m: DESIGN_LINE, text, count=1)
    parts = re.split(r"(?m)^(?=## Frame \d+ — )", text)
    out = [parts[0]]
    for part in parts[1:]:
        n = int(re.match(r"## Frame (\d+)", part).group(1))
        part = part.replace("- status: outline", "- status: built", 1)
        if "- voice:" not in part:
            part = re.sub(r"(?m)^(- voiceover: .*)$", lambda m: m.group(1) + f"\n- voice: {VOICES[n]}", part, count=1)
        if n in ASSETS and "- asset:" not in part:
            part = re.sub(r"(?m)^(- src: .*)$", lambda m: m.group(1) + f"\n- asset: {ASSETS[n]}", part, count=1)
        out.append(part)
    io.open(path, "w", encoding="utf-8", newline="\n").write("".join(out))
    print("storyboard: frames marked built with voices, assets and the frame.md design line")


if __name__ == "__main__":
    write_sketches()
    mark_storyboard()
